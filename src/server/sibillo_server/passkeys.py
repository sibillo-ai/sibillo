"""Passkeys, a second factor on top of the password (AUTH-010, UX-026, ADR-0065, ADR-0094).

Passkeys are bound to the instance's configured origin, and unavailable
without one. Every challenge is valid for 5 minutes and used once, whatever
the outcome. Registering or removing one's own passkey needs the password
again; tenant admins count and remove a user's passkeys, never see their
names. The WebAuthn checks are py_webauthn's, run in a worker thread.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from typing import Any, cast

import webauthn
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from webauthn.helpers import options_to_json_dict, parse_authentication_credential_json
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine, check_password, record_attempt, request_source
from sibillo_server.config import ApiConfiguration
from sibillo_server.credentials import uuid7
from sibillo_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction

router = APIRouter()

RELYING_PARTY_NAME = "Sibillo"
CHALLENGE_BYTES = 32
CEREMONY_MILLISECONDS = 5 * 60 * 1000
ALGORITHMS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.EDDSA,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
]
TRANSPORTS = {transport.value: transport for transport in AuthenticatorTransport}
PASSKEY_COLUMNS = "id, name, created_at, last_used_at"


def configuration_of(request: Request) -> ApiConfiguration:
    configuration = request.app.state.configuration
    if not isinstance(configuration, ApiConfiguration):
        raise TypeError("the API's configuration is not set")
    return configuration


def relying_party(request: Request) -> tuple[str, str]:
    """The origin and relying party ID passkeys are checked against, or `auth.passkeys_unavailable`."""
    configuration = configuration_of(request)
    if configuration.public_origin is None or configuration.relying_party_id is None:
        raise errors.passkeys_unavailable()
    return configuration.public_origin, configuration.relying_party_id


def _descriptors(rows: list[Any]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(
            id=bytes(row.credential_id),
            transports=[TRANSPORTS[name] for name in row.transports if name in TRANSPORTS] or None,
        )
        for row in rows
    ]


async def credentials_of(connection: AsyncConnection, user_id: uuid.UUID) -> list[Any]:
    """The passkeys of a user; the caller's request context must allow them."""
    return list(
        (
            await connection.execute(
                text(
                    "SELECT id, credential_id, public_key, sign_count, transports FROM passkeys"
                    " WHERE user_id = :user ORDER BY created_at, id"
                ),
                {"user": user_id},
            )
        ).all()
    )


async def sign_in_challenge(
    engine: AsyncEngine, user: Identity, rows: list[Any], rp_id: str, token_hash: bytes
) -> dict[str, Any]:
    """Store the challenge of a sign-in's passkey step; its WebAuthn request options."""
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    async with transaction(engine, user) as connection:
        await connection.execute(
            text(
                "INSERT INTO passkey_challenges (id, tenant_id, user_id, purpose, token_hash, challenge, created_at,"
                " expires_at) VALUES (:id, :tenant_id, :user_id, 'sign_in', :token_hash, :challenge, now(),"
                " now() + interval '5 minutes')"
            ),
            {
                "id": uuid7(),
                "tenant_id": user.tenant_id,
                "user_id": user.user_id,
                "token_hash": token_hash,
                "challenge": challenge,
            },
        )
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=CEREMONY_MILLISECONDS,
        allow_credentials=_descriptors(rows),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json_dict(options)


async def verify_assertion(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    credential: dict[str, Any],
    challenge: bytes,
    origin: str,
    rp_id: str,
) -> tuple[uuid.UUID, int] | None:
    """The passkey that signed `credential` and its new counter, when it verifies; else `None`."""
    try:
        parsed = parse_authentication_credential_json(credential)
    except (WebAuthnException, ValueError, TypeError, KeyError):
        return None
    if parsed.response.user_handle is not None and parsed.response.user_handle != user_id.bytes:
        return None
    row = (
        await connection.execute(
            text("SELECT id, public_key, sign_count FROM passkeys WHERE user_id = :user AND credential_id = :id"),
            {"user": user_id, "id": parsed.raw_id},
        )
    ).one_or_none()
    if row is None:
        return None
    try:
        verified = await asyncio.to_thread(
            webauthn.verify_authentication_response,
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(row.public_key),
            credential_current_sign_count=int(row.sign_count),
            require_user_verification=False,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError):
        return None
    return row.id, verified.new_sign_count


async def _confirm_password(request: Request, engine: AsyncEngine, identity: Identity, password: str) -> None:
    """The user's own password, checked and rate-limited like a sign-in (ADR-0094)."""
    async with transaction(engine, identity) as connection:
        username = (
            await connection.execute(text("SELECT username FROM users WHERE id = :id"), {"id": identity.user_id})
        ).scalar_one()
    account = await check_password(engine, username, password)
    succeeded = account is not None and account.user_id == identity.user_id
    await record_attempt(engine, username, request_source(request), succeeded)
    if not succeeded:
        raise errors.wrong_password()


def _transports(credential: dict[str, Any]) -> list[str]:
    """The transports a registering device reported, those WebAuthn defines."""
    response: object = credential.get("response")
    reported: object = cast("dict[str, object]", response).get("transports") if isinstance(response, dict) else None
    if not isinstance(reported, list):
        return []
    return [name for name in cast("list[object]", reported) if isinstance(name, str) and name in TRANSPORTS]


def _passkey(row: Any) -> schemas.Passkey:
    return schemas.Passkey(id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at)


@router.get("/me/passkeys", response_model=schemas.PasskeyList)
async def list_my_passkeys(request: Request, identity: Authenticated, engine: Engine) -> schemas.PasskeyList:
    async with transaction(engine, identity) as connection:
        # Tenant admins may see others' passkeys: only the user's own are theirs.
        rows = (
            await connection.execute(
                text(f"SELECT {PASSKEY_COLUMNS} FROM passkeys WHERE user_id = :user ORDER BY created_at, id"),  # noqa: S608
                {"user": identity.user_id},
            )
        ).all()
    return schemas.PasskeyList(
        available=configuration_of(request).public_origin is not None, items=[_passkey(row) for row in rows]
    )


@router.post(
    "/me/passkeys/registrations", status_code=status.HTTP_201_CREATED, response_model=schemas.PasskeyRegistration
)
async def start_passkey_registration(
    body: schemas.PasswordConfirmation, request: Request, identity: Authenticated, engine: Engine
) -> schemas.PasskeyRegistration:
    _, rp_id = relying_party(request)
    await _confirm_password(request, engine, identity, body.password)
    challenge, registration_id = secrets.token_bytes(CHALLENGE_BYTES), uuid7()
    async with transaction(engine, identity) as connection:
        user = (
            await connection.execute(
                text("SELECT username, display_name FROM users WHERE id = :id"), {"id": identity.user_id}
            )
        ).one()
        rows = await credentials_of(connection, identity.user_id)
        await connection.execute(
            text("DELETE FROM passkey_challenges WHERE user_id = :user AND expires_at <= now()"),
            {"user": identity.user_id},
        )
        await connection.execute(
            text(
                "INSERT INTO passkey_challenges (id, tenant_id, user_id, purpose, challenge, created_at, expires_at)"
                " VALUES (:id, :tenant_id, :user_id, 'registration', :challenge, now(), now() + interval '5 minutes')"
            ),
            {
                "id": registration_id,
                "tenant_id": identity.tenant_id,
                "user_id": identity.user_id,
                "challenge": challenge,
            },
        )
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RELYING_PARTY_NAME,
        user_name=user.username,
        # The user's identifier, never their username (ADR-0094).
        user_id=identity.user_id.bytes,
        user_display_name=user.display_name,
        challenge=challenge,
        timeout=CEREMONY_MILLISECONDS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=_descriptors(rows),
        supported_pub_key_algs=ALGORITHMS,
    )
    return schemas.PasskeyRegistration(registration_id=registration_id, options=options_to_json_dict(options))


@router.post("/me/passkeys", status_code=status.HTTP_201_CREATED, response_model=schemas.Passkey)
async def add_my_passkey(
    body: schemas.AddPasskeyRequest, request: Request, identity: Authenticated, engine: Engine
) -> schemas.Passkey:
    origin, rp_id = relying_party(request)
    # The registration is taken, and used, in a transaction of its own: whatever follows (ADR-0094).
    async with transaction(engine, identity) as connection:
        registration = (
            await connection.execute(
                text(
                    "DELETE FROM passkey_challenges WHERE id = :id AND user_id = :user AND purpose = 'registration'"
                    " RETURNING challenge, expires_at > now() AS valid"
                ),
                {"id": body.registration_id, "user": identity.user_id},
            )
        ).one_or_none()
    if registration is None or not registration.valid:
        raise errors.passkey_rejected()
    try:
        verified = await asyncio.to_thread(
            webauthn.verify_registration_response,
            credential=body.credential,
            expected_challenge=bytes(registration.challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=False,
            supported_pub_key_algs=ALGORITHMS,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError):
        raise errors.passkey_rejected() from None
    transports = _transports(body.credential)
    try:
        async with transaction(engine, identity) as connection:
            row = (
                await connection.execute(
                    text(
                        "INSERT INTO passkeys (id, tenant_id, user_id, credential_id, public_key, sign_count,"  # noqa: S608 - constant columns
                        " transports, name, created_at) VALUES (:id, :tenant_id, :user_id, :credential_id,"
                        f" :public_key, :sign_count, :transports, :name, now()) RETURNING {PASSKEY_COLUMNS}"
                    ),
                    {
                        "id": uuid7(),
                        "tenant_id": identity.tenant_id,
                        "user_id": identity.user_id,
                        "credential_id": verified.credential_id,
                        "public_key": verified.credential_public_key,
                        "sign_count": verified.sign_count,
                        "transports": transports,
                        "name": body.name,
                    },
                )
            ).one()
    except DBAPIError as error:
        # A passkey registered already, by this user or anyone.
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise errors.passkey_rejected() from None
        raise
    return _passkey(row)


@router.post("/me/passkeys/{passkey_id}/remove", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def remove_my_passkey(
    passkey_id: uuid.UUID, body: schemas.PasswordConfirmation, request: Request, identity: Authenticated, engine: Engine
) -> Response:
    await _confirm_password(request, engine, identity, body.password)
    async with transaction(engine, identity) as connection:
        result = await connection.execute(
            text("DELETE FROM passkeys WHERE id = :id AND user_id = :user"),
            {"id": passkey_id, "user": identity.user_id},
        )
    # Another user's passkey is not this user's to remove, so it is reported as not found (TEN-006).
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _tenant_user(connection: AsyncConnection, identity: Identity, user_id: uuid.UUID) -> None:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    # Row-level security shows only the users of the admin's tenant (TEN-006).
    if (await connection.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id})).one_or_none() is None:
        raise errors.not_found()


@router.get("/tenant/users/{user_id}/passkeys", response_model=schemas.PasskeyCount)
async def count_user_passkeys(user_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.PasskeyCount:
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, identity, user_id)
        count = (
            await connection.execute(text("SELECT count(*) FROM passkeys WHERE user_id = :user"), {"user": user_id})
        ).scalar_one()
    return schemas.PasskeyCount(count=int(count))


@router.delete("/tenant/users/{user_id}/passkeys", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def remove_user_passkeys(user_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, identity, user_id)
        await connection.execute(text("DELETE FROM passkeys WHERE user_id = :user"), {"user": user_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
