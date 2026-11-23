"""Signing in: the password, then a passkey for a user who has one (AUTH-001, AUTH-006, AUTH-010, ADR-0094).

The password step is answered with a device session, or, for a user with
passkeys, with a sign-in token and WebAuthn request options. The passkey step
takes the token, which is used once whatever the outcome, and the device's
answer. Both steps count toward the rate limits (ADR-0047).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from sibillo_server import errors, passkeys, schemas
from sibillo_server.auth import Engine, check_attempt, check_password, open_session, record_attempt, request_source
from sibillo_server.credentials import new_token, token_hash, uuid7
from sibillo_server.database import Identity, transaction

router = APIRouter()


@router.post(
    "/auth/login",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.LoginResponse | schemas.PasskeyRequired,
)
async def login(
    body: schemas.LoginRequest, request: Request, response: Response, engine: Engine
) -> schemas.LoginResponse | schemas.PasskeyRequired:
    source = request_source(request)
    # An attempt over the limits is refused before its password costs a hash (ADR-0118).
    await check_attempt(engine, body.username, source)
    account = await check_password(engine, body.username, body.password)
    # The answer to a refused attempt does not depend on the password (ADR-0047).
    await record_attempt(engine, body.username, source, account is not None)
    if account is None:
        raise errors.invalid_credentials()
    user = Identity(uuid7(), account.user_id, account.tenant_id, account.role, account.instance_admin)
    async with transaction(engine, user) as connection:
        rows = await passkeys.credentials_of(connection, user.user_id)
    if not rows:
        return await open_session(engine, user, body.device_name, body.session_delivery, response)
    _, rp_id = passkeys.relying_party(request)
    sign_in_token = new_token()
    options = await passkeys.sign_in_challenge(engine, user, rows, rp_id, token_hash(sign_in_token))
    response.status_code = status.HTTP_200_OK
    return schemas.PasskeyRequired(sign_in_token=sign_in_token, options=options)


@router.post("/auth/login/passkey", status_code=status.HTTP_201_CREATED, response_model=schemas.LoginResponse)
async def login_with_passkey(
    body: schemas.PasskeyLoginRequest, request: Request, response: Response, engine: Engine
) -> schemas.LoginResponse:
    origin, rp_id = passkeys.relying_party(request)
    async with transaction(engine, None) as connection:
        taken = (
            await connection.execute(
                text(
                    "SELECT user_id, tenant_id, username, role, instance_admin, disabled, challenge,"
                    " expires_at > now() AS valid FROM auth_take_sign_in(:token_hash)"
                ),
                {"token_hash": token_hash(body.sign_in_token)},
            )
        ).one_or_none()
    user = (
        None if taken is None else Identity(uuid7(), taken.user_id, taken.tenant_id, taken.role, taken.instance_admin)
    )
    verified = None
    if taken is not None and user is not None and taken.valid and not taken.disabled:
        async with transaction(engine, user) as connection:
            verified = await passkeys.verify_assertion(
                connection, user.user_id, body.credential, bytes(taken.challenge), origin, rp_id
            )
    # An unknown token counts for the source address only.
    await record_attempt(engine, taken.username if taken else "", request_source(request), verified is not None)
    if verified is None or user is None:
        raise errors.invalid_credentials()
    passkey_id, sign_count = verified
    async with transaction(engine, user) as connection:
        await connection.execute(
            text("UPDATE passkeys SET sign_count = :count, last_used_at = now() WHERE id = :id"),
            {"id": passkey_id, "count": sign_count},
        )
    return await open_session(engine, user, body.device_name, body.session_delivery, response)
