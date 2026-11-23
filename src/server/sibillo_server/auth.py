"""Device sessions, logout, passwords, and what signing in shares (AUTH-001, AUTH-004, AUTH-006, AUTH-011, AUTH-012).

See ADR-0025, ADR-0049 and ADR-0105.

Before a session is verified there is no request context: the login and the
token check go through the pre-authentication functions of the database
contract. Everything after runs with the context of the session's user.
Signing in itself, with a password and a passkey, is in `sign_in`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.credentials import hash_password, new_token, token_hash, verify_password
from sibillo_server.database import Identity, transaction
from sibillo_server.network import Address, source_address

router = APIRouter()

# The web app's session cookie, and the header its changes carry (AUTH-005, ADR-0067).
SESSION_COOKIE = "sibillo_session"
REQUEST_HEADER = "x-sibillo-request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Browsers keep a cookie at most 400 days; the session's own expiry still applies.
COOKIE_MAX_AGE_SECONDS = 400 * 24 * 60 * 60

USER_COLUMNS = "id, tenant_id, username, display_name, role, instance_admin, password_change_required, created_at"


def engine_of(request: Request) -> AsyncEngine:
    engine = request.app.state.engine
    if not isinstance(engine, AsyncEngine):
        raise RuntimeError("the database engine is not started")
    return engine


type Engine = Annotated[AsyncEngine, Depends(engine_of)]


def _presented_token(request: Request) -> str | None:
    """The session token of a request: its bearer token, or else its session cookie.

    A change authenticated by the cookie must carry the request header, which a
    cross-site request cannot set (AUTH-005).
    """
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, token = header.partition(" ")
        return token.strip() if scheme.lower() == "bearer" and token.strip() else None
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    if request.method not in SAFE_METHODS and REQUEST_HEADER not in request.headers:
        return None
    return cookie


async def authenticate_any(request: Request, engine: Engine) -> Identity:
    """The identity of the request's device session, also while its user must replace an initial password.

    Only reading one's account, changing one's password and signing out use it
    directly (AUTH-012, ADR-0105); every other operation uses `authenticate`.
    """
    token = _presented_token(request)
    if token is None:
        raise errors.unauthenticated()
    async with transaction(engine, None) as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT session_id, user_id, tenant_id, role, instance_admin, password_change_required"
                    " FROM auth_find_session(:token_hash) WHERE NOT revoked AND expires_at > now()"
                ),
                {"token_hash": token_hash(token.strip())},
            )
        ).one_or_none()
        if row is None:
            raise errors.unauthenticated()
        # The session is in use: renew it (ADR-0049).
        await connection.execute(text("SELECT auth_touch_session(:session_id)"), {"session_id": row.session_id})
    return Identity(
        row.session_id, row.user_id, row.tenant_id, row.role, row.instance_admin, row.password_change_required
    )


async def authenticate(request: Request, engine: Engine) -> Identity:
    """The identity of the request's device session; anything else is unauthenticated.

    A user who must replace an initial password is refused (AUTH-012).
    """
    identity = await authenticate_any(request, engine)
    if identity.password_change_required:
        raise errors.password_change_required()
    return identity


type Authenticated = Annotated[Identity, Depends(authenticate)]
# Also while the user must replace an initial password (AUTH-012).
type SignedIn = Annotated[Identity, Depends(authenticate_any)]


def user_response(row: Any) -> schemas.User:
    return schemas.User(
        id=row.id,
        tenant_id=row.tenant_id,
        username=row.username,
        display_name=row.display_name,
        role=row.role,
        instance_admin=row.instance_admin,
        password_change_required=row.password_change_required,
        created_at=row.created_at,
    )


def request_source(request: Request) -> Address | None:
    """The source address of a request, for rate limits (ADR-0050)."""
    return source_address(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        request.app.state.configuration.trusted_proxies,
    )


async def check_attempt(engine: AsyncEngine, username: str, source: Address | None) -> None:
    """Refuse an attempt over the limits before its password is checked, recording nothing (ADR-0118)."""
    async with transaction(engine, None) as connection:
        limit = (
            await connection.execute(
                text("SELECT allowed, retry_after_seconds FROM auth_check_login_attempt(:username, :source)"),
                {"username": username, "source": source},
            )
        ).one()
    if not limit.allowed:
        raise errors.rate_limited(limit.retry_after_seconds)


async def record_attempt(engine: AsyncEngine, username: str, source: Address | None, succeeded: bool) -> None:
    """Count a sign-in attempt; over the limits it is refused, whatever its outcome (ADR-0047)."""
    async with transaction(engine, None) as connection:
        limit = (
            await connection.execute(
                text(
                    "SELECT allowed, retry_after_seconds FROM auth_record_login_attempt(:username, :source, :success)"
                ),
                {"username": username, "source": source, "success": succeeded},
            )
        ).one()
    if not limit.allowed:
        raise errors.rate_limited(limit.retry_after_seconds)


async def confirm_password(request: Request, engine: AsyncEngine, identity: Identity, password: str) -> None:
    """The user's own password, checked and rate-limited like a sign-in (ADR-0094, ADR-0105)."""
    async with transaction(engine, identity) as connection:
        username = (
            await connection.execute(text("SELECT username FROM users WHERE id = :id"), {"id": identity.user_id})
        ).scalar_one()
    source = request_source(request)
    await check_attempt(engine, username, source)
    account = await check_password(engine, username, password)
    succeeded = account is not None and account.user_id == identity.user_id
    await record_attempt(engine, username, source, succeeded)
    if not succeeded:
        raise errors.wrong_password()


async def check_password(engine: AsyncEngine, username: str, password: str) -> Any | None:
    """The account of `username` when `password` is its own and it is enabled; else `None`, in the same time."""
    async with transaction(engine, None) as connection:
        account = (
            await connection.execute(
                text(
                    "SELECT user_id, tenant_id, password_hash, role, instance_admin, disabled"
                    " FROM auth_find_login(:username)"
                ),
                {"username": username},
            )
        ).one_or_none()
    password_matches = await verify_password(account.password_hash if account else None, password)
    return account if account is not None and password_matches and not account.disabled else None


async def open_session(
    engine: AsyncEngine,
    user: Identity,
    device_name: str,
    delivery: Literal["token", "cookie"],
    response: Response,
) -> schemas.LoginResponse:
    """A new device session of `user`, delivered by token or cookie (AUTH-004, ADR-0067)."""
    token = new_token()
    async with transaction(engine, user) as connection:
        session = (
            await connection.execute(
                text(
                    "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at,"
                    " last_used_at, expires_at)"
                    " VALUES (:id, :tenant_id, :user_id, :token_hash, :device_name, now(), now(),"
                    " now() + interval '90 days')"
                    " RETURNING id, device_name, created_at, last_used_at, expires_at"
                ),
                {
                    "id": user.session_id,
                    "tenant_id": user.tenant_id,
                    "user_id": user.user_id,
                    "token_hash": token_hash(token),
                    "device_name": device_name,
                },
            )
        ).one()
        row = (
            await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": user.user_id})  # noqa: S608
        ).one()
    if delivery == "cookie":
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=COOKIE_MAX_AGE_SECONDS,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
    return schemas.LoginResponse(
        token=token if delivery == "token" else None,
        session=schemas.DeviceSession(
            id=session.id,
            device_name=session.device_name,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            current=True,
        ),
        user=user_response(row),
    )


async def _forget_subscription(connection: AsyncConnection, session_id: uuid.UUID) -> None:
    """A revoked session is notified no more: its notification subscription goes with it (UX-004, ADR-0101)."""
    await connection.execute(
        text("DELETE FROM notification_subscriptions WHERE device_session_id = :id"), {"id": session_id}
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(identity: SignedIn, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text("UPDATE device_sessions SET revoked_at = now() WHERE id = :id"), {"id": identity.session_id}
        )
        await _forget_subscription(connection, identity.session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/me", response_model=schemas.User)
async def get_me(identity: SignedIn, engine: Engine) -> schemas.User:
    async with transaction(engine, identity) as connection:
        row = (
            await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": identity.user_id})  # noqa: S608
        ).one_or_none()
    if row is None:
        raise errors.unauthenticated()
    return user_response(row)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def change_my_password(
    body: schemas.PasswordChange, request: Request, identity: SignedIn, engine: Engine
) -> Response:
    """Replace the user's password, ending their other sessions (AUTH-011, AUTH-012, ADR-0105)."""
    await confirm_password(request, engine, identity, body.current_password)
    password_hash = await hash_password(body.new_password)
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text("UPDATE users SET password_hash = :hash, password_change_required = false WHERE id = :id"),
            {"hash": password_hash, "id": identity.user_id},
        )
        # Row-level security limits the sessions to the user's own.
        revoked = (
            await connection.execute(
                text(
                    "UPDATE device_sessions SET revoked_at = now() WHERE id <> :current AND revoked_at IS NULL"
                    " RETURNING id"
                ),
                {"current": identity.session_id},
            )
        ).scalars()
        for session_id in list(revoked):
            await _forget_subscription(connection, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/sessions", response_model=schemas.DeviceSessionList)
async def list_my_sessions(identity: Authenticated, engine: Engine) -> schemas.DeviceSessionList:
    # Row-level security limits the rows to the user's own sessions.
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT id, device_name, created_at, last_used_at, expires_at FROM device_sessions"
                    " WHERE revoked_at IS NULL AND expires_at > now() ORDER BY created_at, id"
                )
            )
        ).all()
    return schemas.DeviceSessionList(
        items=[
            schemas.DeviceSession(
                id=row.id,
                device_name=row.device_name,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                current=row.id == identity.session_id,
            )
            for row in rows
        ]
    )


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def revoke_my_session(session_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        result = await connection.execute(
            text("UPDATE device_sessions SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
            {"id": session_id},
        )
        await _forget_subscription(connection, session_id)
    # Another user's session is invisible, so it is reported as not found (TEN-006).
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
