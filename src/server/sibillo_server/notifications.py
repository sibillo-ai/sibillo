"""Notifications on the user's devices, through Web Push (UX-004, ADR-0039, ADR-0101).

A device session has at most one subscription, saved when the user turns
notifications on in that client. At the end of a run that no client follows,
the worker sends each valid subscription of the run's owner a content-free
payload: the kind, the conversation and the run. Payloads are encrypted for
the browser (RFC 8291) and signed with a VAPID key derived from the
instance's secret key (RFC 8292). Endpoints are accepted only on the push
services of ADR-0101, and checked again before each send (T-39).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Literal
from urllib.parse import urlsplit

import anyio
import httpx
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.credentials import uuid7
from sibillo_server.database import Identity, transaction
from sibillo_server.passkeys import configuration_of

logger = logging.getLogger(__name__)
router = APIRouter()

type Kind = Literal["run_finished", "run_failed", "approval_pending", "question_pending"]

# The push services of ADR-0101; a host under `WINDOWS_DOMAIN` is Windows' push service.
PUSH_HOSTS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"})
WINDOWS_DOMAIN = ".notify.windows.com"
# A client following a run refreshes its row this often; a row older than the window does not count.
FOLLOW_REFRESH_SECONDS = 10
FOLLOW_WINDOW_SECONDS = 30
# A notification lives as long as an approval request (AGT-007).
TIME_TO_LIVE_SECONDS = 24 * 60 * 60
# The VAPID token is valid for less than the 24 hours RFC 8292 allows.
TOKEN_SECONDS = 12 * 60 * 60
SEND_TIMEOUT_SECONDS = 10
RECORD_SIZE = 4096
_KEY_LABEL = b"sibillo notifications: VAPID key"
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _from_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def vapid_key(secret_key: bytes) -> ec.EllipticCurvePrivateKey:
    """The instance's VAPID key, derived from its secret key, so that operators configure nothing (ADR-0101)."""
    material = HKDF(algorithm=hashes.SHA256(), length=48, salt=None, info=_KEY_LABEL).derive(secret_key)
    # 48 bytes reduced modulo the order: a uniform scalar from 1 to n - 1.
    scalar = int.from_bytes(material, "big") % (_P256_ORDER - 1) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key(secret_key: bytes) -> str:
    """The `applicationServerKey` browsers subscribe with: the uncompressed point, base64url."""
    return _b64url(_point(vapid_key(secret_key).public_key()))


def allowed_endpoint(endpoint: str) -> bool:
    """Whether `endpoint` is an `https` URL on a push service of ADR-0101, without credentials or another port."""
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and "@" not in parts.netloc
        and (host in PUSH_HOSTS or (host.endswith(WINDOWS_DOMAIN) and len(host) > len(WINDOWS_DOMAIN)))
    )


def _browser_keys(keys: schemas.NotificationKeys) -> tuple[bytes, bytes] | None:
    """The browser's public key and authentication secret, when they are well formed."""
    try:
        point, secret = _from_b64url(keys.p256dh), _from_b64url(keys.auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except (binascii.Error, ValueError):
        return None
    if len(point) != 65 or len(secret) != 16:
        return None
    return point, secret


def encrypt(payload: bytes, browser_key: bytes, auth_secret: bytes) -> bytes:
    """`payload` encrypted for one subscription, as one `aes128gcm` record (RFC 8291, RFC 8188)."""
    browser = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), browser_key)
    sender = ec.generate_private_key(ec.SECP256R1())
    sender_key = _point(sender.public_key())
    shared = sender.exchange(ec.ECDH(), browser)
    info = b"WebPush: info\x00" + browser_key + sender_key
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret, info=info).derive(shared)
    salt = os.urandom(16)
    key = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    sealed = AESGCM(key).encrypt(nonce, payload + b"\x02", None)
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(sender_key)]) + sender_key + sealed


def vapid_authorization(secret_key: bytes, endpoint: str, contact: str) -> str:
    """The `Authorization` header for `endpoint`: a token for its origin, signed by the instance (RFC 8292)."""
    parts = urlsplit(endpoint)
    header = _b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    # The push service's origin; endpoints are on port 443 only, which an origin leaves out.
    claims = {"aud": f"https://{parts.hostname}", "exp": int(time.time()) + TOKEN_SECONDS, "sub": contact}
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    key = vapid_key(secret_key)
    r, s = decode_dss_signature(key.sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    signature = _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{body}.{signature}, k={_b64url(_point(key.public_key()))}"


def _public_origin(request: Request) -> str | None:
    return configuration_of(request).public_origin


async def _settings(request: Request, identity: Identity, engine: AsyncEngine) -> schemas.NotificationSettings:
    if _public_origin(request) is None:
        return schemas.NotificationSettings(available=False, subscribed=False)
    async with transaction(engine, identity) as connection:
        subscribed = (
            await connection.execute(
                text("SELECT 1 FROM notification_subscriptions WHERE device_session_id = :id"),
                {"id": identity.session_id},
            )
        ).one_or_none() is not None
    return schemas.NotificationSettings(
        available=True, subscribed=subscribed, public_key=public_key(configuration_of(request).secret_key)
    )


@router.get("/me/notifications", response_model=schemas.NotificationSettings, response_model_exclude_none=True)
async def get_my_notifications(
    request: Request, identity: Authenticated, engine: Engine
) -> schemas.NotificationSettings:
    return await _settings(request, identity, engine)


@router.put("/me/notifications", response_model=schemas.NotificationSettings, response_model_exclude_none=True)
async def subscribe_to_notifications(
    body: schemas.NotificationSubscription, request: Request, identity: Authenticated, engine: Engine
) -> schemas.NotificationSettings:
    if _public_origin(request) is None:
        raise errors.notifications_unavailable()
    if not allowed_endpoint(body.endpoint):
        raise errors.notification_endpoint_refused()
    if _browser_keys(body.keys) is None:
        raise errors.invalid("/keys", "invalid_key")
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO notification_subscriptions"
                " (tenant_id, owner_id, device_session_id, endpoint, p256dh, auth, created_at)"
                " VALUES (:tenant, :owner, :session, :endpoint, :p256dh, :auth, now())"
                " ON CONFLICT (device_session_id) DO UPDATE SET endpoint = EXCLUDED.endpoint,"
                " p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, created_at = EXCLUDED.created_at"
            ),
            {
                "tenant": identity.tenant_id,
                "owner": identity.user_id,
                "session": identity.session_id,
                "endpoint": body.endpoint,
                "p256dh": body.keys.p256dh,
                "auth": body.keys.auth,
            },
        )
    return await _settings(request, identity, engine)


@router.delete("/me/notifications", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def unsubscribe_from_notifications(identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text("DELETE FROM notification_subscriptions WHERE device_session_id = :id"), {"id": identity.session_id}
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Following a run: one row per open event stream (ADR-0101, point 2).


async def add_follower(connection: AsyncConnection, identity: Identity, run_id: uuid.UUID) -> uuid.UUID:
    """Record an event stream of `run_id` that is about to open; return its row's ID."""
    follower_id = uuid7()
    await connection.execute(
        text(
            "INSERT INTO run_followers (id, tenant_id, owner_id, run_id, seen_at)"
            " VALUES (:id, :tenant, :owner, :run, now())"
        ),
        {"id": follower_id, "tenant": identity.tenant_id, "owner": identity.user_id, "run": run_id},
    )
    return follower_id


async def following(
    events: AsyncIterator[str], engine: AsyncEngine, identity: Identity, follower_id: uuid.UUID
) -> AsyncIterator[str]:
    """`events`, while the follower's row is refreshed; the row is deleted when the stream closes."""

    async def refresh() -> None:
        while True:
            await asyncio.sleep(FOLLOW_REFRESH_SECONDS)
            try:
                async with transaction(engine, identity) as connection:
                    await connection.execute(
                        text("UPDATE run_followers SET seen_at = now() WHERE id = :id"), {"id": follower_id}
                    )
            except Exception:
                logger.warning("a run's follower could not be refreshed")

    refreshing = asyncio.create_task(refresh())
    try:
        async for event in events:
            yield event
    finally:
        refreshing.cancel()
        # Also when the client went away and the stream is being cancelled.
        with anyio.CancelScope(shield=True):
            try:
                async with transaction(engine, identity) as connection:
                    await connection.execute(text("DELETE FROM run_followers WHERE id = :id"), {"id": follower_id})
            except Exception:
                logger.warning(
                    "a run's follower could not be removed; it stops counting after %s seconds", FOLLOW_WINDOW_SECONDS
                )


async def is_followed(engine: AsyncEngine, identity: Identity, run_id: uuid.UUID) -> bool:
    """Whether a client follows the run now: one of its streams was seen within the window."""
    async with transaction(engine, identity) as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT 1 FROM run_followers WHERE run_id = :run"
                    " AND seen_at > now() - make_interval(secs => :window) LIMIT 1"
                ),
                {"run": run_id, "window": FOLLOW_WINDOW_SECONDS},
            )
        ).one_or_none()
    return row is not None


# Sending, from the worker.


async def notify(
    engine: AsyncEngine,
    identity: Identity,
    *,
    secret_key: bytes,
    contact: str | None,
    kind: Kind,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
) -> None:
    """Send `kind` to every valid subscription of the run's owner; best effort, once each (ADR-0101, point 6)."""
    if contact is None:
        return
    try:
        await _notify(engine, identity, secret_key, contact, kind, conversation_id, run_id)
    except Exception:
        logger.exception("run %s: notifications could not be sent", run_id)


async def _notify(
    engine: AsyncEngine,
    identity: Identity,
    secret_key: bytes,
    contact: str,
    kind: Kind,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
) -> None:
    async with transaction(engine, identity) as connection:
        # The subscriptions of sessions that are no longer valid, and those not on a push service, go (T-39).
        rows = (
            await connection.execute(
                text(
                    "SELECT n.device_session_id, n.endpoint, n.p256dh, n.auth,"
                    " (s.revoked_at IS NULL AND s.expires_at > now() AND u.disabled_at IS NULL) AS valid"
                    " FROM notification_subscriptions n"
                    " JOIN device_sessions s ON s.id = n.device_session_id"
                    " JOIN users u ON u.tenant_id = n.tenant_id AND u.id = n.owner_id"
                    " WHERE n.owner_id = :owner"
                ),
                {"owner": identity.user_id},
            )
        ).all()
        stale = [row.device_session_id for row in rows if not row.valid or not allowed_endpoint(row.endpoint)]
        if stale:
            await connection.execute(
                text("DELETE FROM notification_subscriptions WHERE device_session_id = ANY(:ids)"), {"ids": stale}
            )
    payload = json.dumps(
        {"kind": kind, "conversation_id": str(conversation_id), "run_id": str(run_id)}, separators=(",", ":")
    ).encode()
    urgency = "high" if kind in ("approval_pending", "question_pending") else "normal"
    gone: list[uuid.UUID] = []
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for row in rows:
            if row.device_session_id in stale:
                continue
            keys = _browser_keys(schemas.NotificationKeys(p256dh=row.p256dh, auth=row.auth))
            if keys is None:
                gone.append(row.device_session_id)
                continue
            try:
                response = await client.post(
                    row.endpoint,
                    content=encrypt(payload, *keys),
                    headers={
                        "Authorization": vapid_authorization(secret_key, row.endpoint, contact),
                        "Content-Encoding": "aes128gcm",
                        "Content-Type": "application/octet-stream",
                        "TTL": str(TIME_TO_LIVE_SECONDS),
                        "Urgency": urgency,
                    },
                )
            except (httpx.HTTPError, InvalidKey) as error:
                logger.warning("run %s: a notification was not delivered: %s", run_id, type(error).__name__)
                continue
            if response.status_code in (404, 410):
                gone.append(row.device_session_id)
            elif response.status_code >= 400:
                logger.warning("run %s: a push service answered %s", run_id, response.status_code)
    if gone:
        async with transaction(engine, identity) as connection:
            await connection.execute(
                text("DELETE FROM notification_subscriptions WHERE device_session_id = ANY(:ids)"), {"ids": gone}
            )
