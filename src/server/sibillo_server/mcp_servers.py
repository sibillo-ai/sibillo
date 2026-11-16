"""Remote MCP servers of a household, their reviewed tools, and each user's credential (AGT-019, AGT-028 to AGT-031).

A tenant admin adds, changes and removes the household's servers and accepts
their tools (ADR-0099); row-level security enforces it, and the role checks
here only choose between `403` and trying. Each user gives a token of their
own or signs in with OAuth (ADR-0100): their credential is a private row,
which no one else reads. A new address, authentication or OAuth client starts
a new generation of a server, and credentials of an older one are not used.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.connections import SecretKey
from sibillo_server.credentials import uuid7
from sibillo_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction
from sibillo_server.encryption import decrypt, decrypt_labelled, encrypt, encrypt_labelled
from sibillo_server.mcp_client import Listing, ServerError, Target, digest, list_tools, problems, reviewed
from sibillo_server.mcp_oauth import (
    OAuthError,
    OAuthSettings,
    authorization_url,
    exchange,
    new_verifier,
    renew,
    same_address,
    settings_for,
)
from sibillo_server.permissions import permissions_of

router = APIRouter()

MAX_SERVERS = 20
CONNECTIONS_PER_MINUTE = 20
SIGN_IN_MINUTES = 10
# An access token expiring this soon is renewed before it is used (ADR-0100, point 7).
RENEW_BEFORE_SECONDS = 60
SERVER_COLUMNS = (
    "id, name, prefix, url, auth, generation, oauth, oauth_client_secret_ciphertext, private_network, enabled,"
    " server_name, server_version, listed_at, created_at, updated_at"
)


class _ConnectionLimit:
    """At most `CONNECTIONS_PER_MINUTE` connections to servers per tenant and minute, per API process (T-31)."""

    def __init__(self) -> None:
        self._times: dict[uuid.UUID, collections.deque[float]] = collections.defaultdict(collections.deque)

    def take(self, tenant_id: uuid.UUID) -> None:
        now = time.monotonic()
        times = self._times[tenant_id]
        while times and times[0] <= now - 60:
            times.popleft()
        if len(times) >= CONNECTIONS_PER_MINUTE:
            raise errors.rate_limited(max(1, int(times[0] + 60 - now) + 1))
        times.append(now)


_LIMIT = _ConnectionLimit()


@dataclass(frozen=True)
class Server:
    """A row of `mcp_servers`."""

    id: uuid.UUID
    name: str
    prefix: str
    url: str
    auth: str
    generation: uuid.UUID
    oauth: OAuthSettings | None
    client_secret_ciphertext: bytes | None
    private_network: bool
    enabled: bool
    server_name: str | None
    server_version: str | None
    listed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @property
    def target(self) -> Target:
        return Target(self.url, self.private_network)

    @property
    def host(self) -> str:
        return self.target.host

    def client_secret(self, key: bytes) -> str | None:
        if self.client_secret_ciphertext is None:
            return None
        return decrypt(key, self.id, self.client_secret_ciphertext)


def _server(row: Any) -> Server:
    return Server(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        url=row.url,
        auth=row.auth,
        generation=row.generation,
        oauth=None if row.oauth is None else OAuthSettings.from_json(row.oauth),
        client_secret_ciphertext=None
        if row.oauth_client_secret_ciphertext is None
        else bytes(row.oauth_client_secret_ciphertext),
        private_network=row.private_network,
        enabled=row.enabled,
        server_name=row.server_name,
        server_version=row.server_version,
        listed_at=row.listed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def servers_of(connection: AsyncConnection, *, enabled_only: bool = False) -> list[Server]:
    """The household's servers, by name; row-level security scopes them to the tenant."""
    where = " WHERE enabled" if enabled_only else ""
    rows = (await connection.execute(text(f"SELECT {SERVER_COLUMNS} FROM mcp_servers{where} ORDER BY name, id"))).all()  # noqa: S608
    return [_server(row) for row in rows]


async def find_server(connection: AsyncConnection, server_id: uuid.UUID, *, lock: bool = False) -> Server:
    row = (
        await connection.execute(
            text(f"SELECT {SERVER_COLUMNS} FROM mcp_servers WHERE id = :id{' FOR UPDATE' if lock else ''}"),  # noqa: S608
            {"id": server_id},
        )
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return _server(row)


# --- Credentials (AGT-030, ADR-0099 point 3) ---


@dataclass(frozen=True)
class Credential:
    id: uuid.UUID
    kind: str
    status: str
    expires_at: datetime.datetime | None


async def credential_of(connection: AsyncConnection, server: Server) -> Credential | None:
    """The user's credential for the server, of its current generation; an older one is deleted."""
    row = (
        await connection.execute(
            text("SELECT id, kind, status, expires_at, server_generation FROM mcp_credentials WHERE server_id = :id"),
            {"id": server.id},
        )
    ).one_or_none()
    if row is None:
        return None
    if row.server_generation != server.generation:
        await connection.execute(text("DELETE FROM mcp_credentials WHERE id = :id"), {"id": row.id})
        return None
    return Credential(row.id, row.kind, row.status, row.expires_at)


async def credential_state(connection: AsyncConnection, server: Server) -> schemas.McpCredentialState:
    if server.auth == "none":
        return "not_needed"
    credential = await credential_of(connection, server)
    if credential is None:
        return "missing"
    return "expired" if credential.status == "expired" else "valid"


async def _store_credential(
    connection: AsyncConnection,
    identity: Identity,
    server: Server,
    key: bytes,
    kind: str,
    access: str,
    refresh: str | None,
    expires_in: int | None,
) -> None:
    await connection.execute(text("DELETE FROM mcp_credentials WHERE server_id = :id"), {"id": server.id})
    credential_id = uuid7()
    await connection.execute(
        text(
            "INSERT INTO mcp_credentials (id, tenant_id, owner_id, server_id, server_generation, kind,"
            " access_token_ciphertext, refresh_token_ciphertext, expires_at, status, created_at, updated_at)"
            " VALUES (:id, :tenant, :owner, :server, :generation, :kind, :access, :refresh,"
            " CASE WHEN CAST(:expires_in AS integer) IS NULL THEN NULL"
            " ELSE now() + make_interval(secs => CAST(:expires_in AS integer)) END, 'valid', now(), now())"
        ),
        {
            "id": credential_id,
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "server": server.id,
            "generation": server.generation,
            "kind": kind,
            "access": encrypt_labelled(key, credential_id, "access", access),
            "refresh": None if refresh is None else encrypt_labelled(key, credential_id, "refresh", refresh),
            "expires_in": expires_in,
        },
    )


async def token_for(
    engine: AsyncEngine, identity: Identity, server: Server, key: bytes, *, refused: bool = False
) -> str | None:
    """The user's token for the server, renewed first when it expires soon, or when the server `refused` it.

    The renewal holds a lock on the credential's row, so that two runs of the
    user renew it once; a renewal that fails, or a refused token that cannot
    be renewed, leaves the credential expired (ADR-0100, point 7).
    """
    if server.auth == "none":
        return None
    async with transaction(engine, identity) as connection:
        if await credential_of(connection, server) is None:
            return None
        row = (
            await connection.execute(
                text(
                    "SELECT id, kind, status, access_token_ciphertext, refresh_token_ciphertext,"
                    " expires_at <= now() + make_interval(secs => :before) AS expiring FROM mcp_credentials"
                    " WHERE server_id = :id FOR UPDATE"
                ),
                {"id": server.id, "before": RENEW_BEFORE_SECONDS},
            )
        ).one()
        if row.status == "expired":
            return None
        access = decrypt_labelled(key, row.id, "access", bytes(row.access_token_ciphertext))
        if not refused and not row.expiring:
            return access
        expired = text("UPDATE mcp_credentials SET status = 'expired', updated_at = now() WHERE id = :id")
        if row.kind != "oauth" or server.oauth is None or row.refresh_token_ciphertext is None:
            if refused:
                await connection.execute(expired, {"id": row.id})
                return None
            return access
        refresh = decrypt_labelled(key, row.id, "refresh", bytes(row.refresh_token_ciphertext))
        try:
            tokens = await renew(server.oauth, server.client_secret(key), server.url, server.private_network, refresh)
        except OAuthError:
            await connection.execute(expired, {"id": row.id})
            return None
        await connection.execute(
            text(
                "UPDATE mcp_credentials SET access_token_ciphertext = :access,"
                " refresh_token_ciphertext = coalesce(CAST(:refresh AS bytea), refresh_token_ciphertext),"
                " expires_at = CASE WHEN CAST(:expires_in AS integer) IS NULL THEN NULL"
                " ELSE now() + make_interval(secs => CAST(:expires_in AS integer)) END,"
                " status = 'valid', updated_at = now() WHERE id = :id"
            ),
            {
                "id": row.id,
                "access": encrypt_labelled(key, row.id, "access", tokens.access_token),
                "refresh": None
                if tokens.refresh_token is None
                else encrypt_labelled(key, row.id, "refresh", tokens.refresh_token),
                "expires_in": tokens.expires_in,
            },
        )
        return tokens.access_token


# --- What the API answers ---


def _definition(listed: dict[str, Any], *, annotations: bool) -> schemas.McpToolDefinition:
    return schemas.McpToolDefinition(
        title=listed.get("title"),
        description=listed.get("description"),
        input_schema=cast(dict[str, Any], listed.get("inputSchema") or {}),
        annotations=cast(dict[str, Any] | None, listed.get("annotations")) if annotations else None,
    )


def tool_status(listed: dict[str, Any] | None, accepted: dict[str, Any] | None, problem: str | None) -> str:
    """Whether a tool is offered, and if not, why (AGT-028)."""
    if accepted is not None:
        if listed is None:
            return "gone"
        return "accepted" if problem is None and reviewed(listed) == accepted else "changed"
    return "unusable" if problem is not None else "not_accepted"


async def _tools(connection: AsyncConnection, server: Server) -> list[schemas.McpServerTool]:
    rows = (
        await connection.execute(
            text(
                "SELECT name, listed, accepted, problem, accepted_at FROM mcp_server_tools WHERE server_id = :id"
                " ORDER BY name"
            ),
            {"id": server.id},
        )
    ).all()
    return [
        schemas.McpServerTool(
            name=row.name,
            model_name=f"{server.prefix}__{row.name}",
            status=cast(Any, tool_status(row.listed, row.accepted, row.problem)),
            listed=None if row.listed is None else _definition(row.listed, annotations=True),
            accepted=None if row.accepted is None else _definition(row.accepted, annotations=False),
            digest=None if row.listed is None else digest(row.listed),
            problem=row.problem,
            accepted_at=row.accepted_at,
        )
        for row in rows
    ]


async def _view(connection: AsyncConnection, server: Server) -> schemas.McpServer:
    oauth = server.oauth
    return schemas.McpServer(
        id=server.id,
        name=server.name,
        prefix=server.prefix,
        url=server.url,
        auth=cast(Any, server.auth),
        oauth=None
        if oauth is None
        else schemas.McpOAuth(
            issuer=oauth.issuer,
            client_id=oauth.client_id,
            client_registration=cast(Any, oauth.client_registration),
            has_client_secret=server.client_secret_ciphertext is not None,
            scope=oauth.scope,
        ),
        credential=await credential_state(connection, server),
        private_network=server.private_network,
        enabled=server.enabled,
        server=None
        if server.server_name is None
        else schemas.McpServerInfo(name=server.server_name, version=server.server_version or ""),
        tools=await _tools(connection, server),
        listed_at=server.listed_at,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


async def store_listing(connection: AsyncConnection, server: Server, tenant_id: uuid.UUID, listing: Listing) -> None:
    """Keep the tools as just listed: `listed` and `problem` for every tool (ADR-0099, point 6)."""
    found = problems(server.prefix, listing.tools)
    for listed in listing.tools:
        await connection.execute(
            text(
                "INSERT INTO mcp_server_tools (tenant_id, server_id, name, listed, problem)"
                " VALUES (:tenant, :server, :name, CAST(:listed AS jsonb), :problem)"
                " ON CONFLICT (server_id, name) DO UPDATE SET listed = EXCLUDED.listed, problem = EXCLUDED.problem"
            ),
            {
                "tenant": tenant_id,
                "server": server.id,
                "name": listed.name,
                "listed": json.dumps(listed.listed()),
                "problem": found[listed.name],
            },
        )
    names = [listed.name for listed in listing.tools]
    await connection.execute(
        text(
            "UPDATE mcp_server_tools SET listed = NULL, problem = NULL WHERE server_id = :server"
            " AND NOT (name = ANY(:names))"
        ),
        {"server": server.id, "names": names},
    )
    await connection.execute(
        text("DELETE FROM mcp_server_tools WHERE server_id = :server AND listed IS NULL AND accepted IS NULL"),
        {"server": server.id},
    )
    await connection.execute(
        text("UPDATE mcp_servers SET server_name = :name, server_version = :version, listed_at = now() WHERE id = :id"),
        {"id": server.id, "name": listing.server_name, "version": listing.server_version},
    )


# --- Errors ---


def _refused(code: str, title: str, detail: str) -> errors.ApiError:
    return errors.ApiError(422, code, title, detail=detail)


def _unreachable(error: ServerError) -> errors.ApiError:
    if error.unauthorized:
        return _refused("mcp_server.unauthorized", "Credential refused", str(error))
    return _refused("mcp_server.unreachable", "Server unreachable", str(error))


def _oauth_unsupported(detail: str) -> errors.ApiError:
    return _refused("mcp_server.oauth_unsupported", "Sign-in unsupported", detail)


def _sign_in_failed(detail: str) -> errors.ApiError:
    return _refused("mcp_server.sign_in_failed", "Sign-in failed", detail)


def _check_admin(identity: Identity) -> None:
    if not identity.tenant_admin:
        raise errors.permission_denied()


def _public_origin(request: Request) -> str | None:
    origin = request.app.state.configuration.public_origin
    return origin if isinstance(origin, str) and origin else None


def _check_address(url: str, identity: Identity) -> None:
    """An address set by a user who is not the instance admin is `https` (ADR-0099, point 4)."""
    if not identity.instance_admin and urlsplit(url).scheme != "https":
        raise errors.invalid("/url", "https_required")


async def _list(target: Target, token: str | None) -> Listing:
    try:
        return await list_tools(target, token)
    except ServerError as error:
        raise _unreachable(error) from None


async def _oauth_settings(
    request: Request, url: str, private_network: bool, client_id: str | None, client_secret: str | None
) -> tuple[OAuthSettings, str | None]:
    origin = _public_origin(request)
    if origin is None:
        raise _oauth_unsupported("SIBILLO_PUBLIC_ORIGIN is not set, so sign-ins cannot come back")
    try:
        return await settings_for(url, private_network, origin, client_id, client_secret)
    except OAuthError as error:
        raise _oauth_unsupported(str(error)) from None


def _unique(error: DBAPIError) -> errors.ApiError | None:
    return errors.conflict() if sqlstate(error) == UNIQUE_VIOLATION else None


# --- The household's servers, for tenant admins (AGT-019, AGT-028) ---


@router.post("/tenant/mcp-servers", status_code=status.HTTP_201_CREATED, response_model=schemas.McpServer)
async def create_mcp_server(
    body: schemas.CreateMcpServerRequest, request: Request, identity: Authenticated, engine: Engine, key: SecretKey
) -> schemas.McpServer:
    _check_admin(identity)
    url = str(body.url)
    _check_address(url, identity)
    if body.auth != "oauth" and (body.oauth_client_id is not None or body.oauth_client_secret is not None):
        raise errors.invalid("/oauth_client_id", "only_for_oauth")
    if body.oauth_client_secret is not None and body.oauth_client_id is None:
        raise errors.invalid("/oauth_client_secret", "without_client_id")
    async with transaction(engine, identity) as connection:
        count = (await connection.execute(text("SELECT count(*) FROM mcp_servers"))).scalar_one()
        taken = (
            await connection.execute(
                text("SELECT 1 FROM mcp_servers WHERE prefix = :prefix OR name = :name"),
                {"prefix": body.prefix, "name": body.name},
            )
        ).first()
    if count >= MAX_SERVERS or taken is not None:
        raise errors.conflict()
    target = Target(url, identity.instance_admin)
    listing: Listing | None = None
    oauth: OAuthSettings | None = None
    client_secret: str | None = None
    if body.auth == "none":
        _LIMIT.take(identity.tenant_id)
        listing = await _list(target, None)
    elif body.auth == "oauth":
        _LIMIT.take(identity.tenant_id)
        oauth, client_secret = await _oauth_settings(
            request, url, target.private_network, body.oauth_client_id, body.oauth_client_secret
        )
    server_id = uuid7()
    try:
        async with transaction(engine, identity) as connection:
            await connection.execute(
                text(
                    "INSERT INTO mcp_servers (id, tenant_id, name, prefix, url, auth, generation, oauth,"
                    " oauth_client_secret_ciphertext, private_network, enabled, created_at, updated_at) VALUES (:id,"
                    " :tenant, :name, :prefix, :url, :auth, :generation, CAST(:oauth AS jsonb), :secret,"
                    " :private_network, true, now(), now())"
                ),
                {
                    "id": server_id,
                    "tenant": identity.tenant_id,
                    "name": body.name,
                    "prefix": body.prefix,
                    "url": url,
                    "auth": body.auth,
                    "generation": uuid.uuid4(),
                    "oauth": None if oauth is None else json.dumps(oauth.to_json()),
                    "secret": None if client_secret is None else encrypt(key, server_id, client_secret),
                    "private_network": target.private_network,
                },
            )
            server = await find_server(connection, server_id)
            if listing is not None:
                await store_listing(connection, server, identity.tenant_id, listing)
                server = await find_server(connection, server_id)
            return await _view(connection, server)
    except DBAPIError as error:
        if (refusal := _unique(error)) is not None:
            raise refusal from None
        raise


@router.get("/tenant/mcp-servers", response_model=schemas.McpServerList)
async def list_mcp_servers(identity: Authenticated, engine: Engine) -> schemas.McpServerList:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        return schemas.McpServerList(items=[await _view(connection, server) for server in await servers_of(connection)])


@router.get("/tenant/mcp-servers/{server_id}", response_model=schemas.McpServer)
async def get_mcp_server(server_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.McpServer:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        return await _view(connection, await find_server(connection, server_id))


@router.patch("/tenant/mcp-servers/{server_id}", response_model=schemas.McpServer)
async def update_mcp_server(
    server_id: uuid.UUID,
    body: schemas.UpdateMcpServerRequest,
    request: Request,
    identity: Authenticated,
    engine: Engine,
    key: SecretKey,
) -> schemas.McpServer:
    _check_admin(identity)
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    for name in ("name", "url", "auth", "enabled"):
        if name in present and getattr(body, name) is None:
            raise errors.invalid(f"/{name}", "null")
    async with transaction(engine, identity) as connection:
        server = await find_server(connection, server_id)
    url = str(body.url) if "url" in present else server.url
    if "url" in present:
        _check_address(url, identity)
    auth = body.auth if "auth" in present and body.auth is not None else server.auth
    moved = "url" in present and not same_address(url, server.url)
    client_changed = bool(present & {"oauth_client_id", "oauth_client_secret"})
    if client_changed and auth != "oauth":
        raise errors.invalid("/oauth_client_id", "only_for_oauth")
    new_generation = moved or auth != server.auth or client_changed
    # A new address is private only when the instance admin sets it (ADR-0099, point 4).
    target = Target(url, identity.instance_admin if moved else server.private_network)
    listing: Listing | None = None
    oauth, client_secret_ciphertext = server.oauth, server.client_secret_ciphertext
    if new_generation and auth == "none":
        _LIMIT.take(identity.tenant_id)
        listing = await _list(target, None)
    if new_generation and auth == "oauth":
        client_id = (
            body.oauth_client_id
            if "oauth_client_id" in present
            else (oauth.client_id if oauth is not None and oauth.client_registration == "given" else None)
        )
        secret = body.oauth_client_secret if "oauth_client_secret" in present else server.client_secret(key)
        if client_id is None:
            secret = None
        _LIMIT.take(identity.tenant_id)
        oauth, plain = await _oauth_settings(request, url, target.private_network, client_id, secret)
        client_secret_ciphertext = None if plain is None else encrypt(key, server_id, plain)
    if auth != "oauth":
        oauth, client_secret_ciphertext = None, None
    try:
        async with transaction(engine, identity) as connection:
            await connection.execute(
                text(
                    "UPDATE mcp_servers SET name = :name, url = :url, auth = :auth, enabled = :enabled,"
                    " private_network = :private_network, oauth = CAST(:oauth AS jsonb),"
                    " oauth_client_secret_ciphertext = :secret,"
                    " generation = CASE WHEN :new_generation THEN gen_random_uuid() ELSE generation END,"
                    " updated_at = now() WHERE id = :id"
                ),
                {
                    "id": server_id,
                    "name": body.name if "name" in present else server.name,
                    "url": url,
                    "auth": auth,
                    "enabled": body.enabled if "enabled" in present else server.enabled,
                    "private_network": target.private_network,
                    "oauth": None if oauth is None else json.dumps(oauth.to_json()),
                    "secret": client_secret_ciphertext,
                    "new_generation": new_generation,
                },
            )
            if moved:
                # It may be another server: nothing of the old one is accepted (ADR-0099, point 6).
                await connection.execute(
                    text("UPDATE mcp_server_tools SET accepted = NULL, accepted_at = NULL WHERE server_id = :id"),
                    {"id": server_id},
                )
                await connection.execute(
                    text("UPDATE mcp_servers SET listed_at = NULL WHERE id = :id"), {"id": server_id}
                )
                if listing is None:
                    await connection.execute(
                        text("DELETE FROM mcp_server_tools WHERE server_id = :id"), {"id": server_id}
                    )
            if new_generation:
                await connection.execute(text("DELETE FROM mcp_sign_ins WHERE server_id = :id"), {"id": server_id})
            server = await find_server(connection, server_id)
            if listing is not None:
                await store_listing(connection, server, identity.tenant_id, listing)
                server = await find_server(connection, server_id)
            return await _view(connection, server)
    except DBAPIError as error:
        if (refusal := _unique(error)) is not None:
            raise refusal from None
        raise


@router.delete("/tenant/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_mcp_server(server_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        await find_server(connection, server_id)
        await connection.execute(
            text("DELETE FROM tool_permissions WHERE subject_kind = 'server' AND subject = :id"), {"id": str(server_id)}
        )
        await connection.execute(text("DELETE FROM mcp_servers WHERE id = :id"), {"id": server_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tenant/mcp-servers/{server_id}/refresh", response_model=schemas.McpServer)
async def refresh_mcp_server(
    server_id: uuid.UUID, identity: Authenticated, engine: Engine, key: SecretKey
) -> schemas.McpServer:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        server = await find_server(connection, server_id)
    _LIMIT.take(identity.tenant_id)
    token = await token_for(engine, identity, server, key)
    if server.auth != "none" and token is None:
        raise _refused(
            "mcp_server.credential_missing",
            "No credential",
            "connect your own account to the server to list its tools",
        )
    try:
        listing = await list_tools(server.target, token)
    except ServerError as error:
        if not error.unauthorized or server.auth != "oauth":
            raise _unreachable(error) from None
        token = await token_for(engine, identity, server, key, refused=True)
        if token is None:
            raise _unreachable(error) from None
        listing = await _list(server.target, token)
    async with transaction(engine, identity) as connection:
        await store_listing(connection, server, identity.tenant_id, listing)
        return await _view(connection, await find_server(connection, server_id))


@router.put("/tenant/mcp-servers/{server_id}/accepted-tools", response_model=schemas.McpServer)
async def set_accepted_mcp_tools(
    server_id: uuid.UUID, body: schemas.AcceptedMcpToolsRequest, identity: Authenticated, engine: Engine
) -> schemas.McpServer:
    _check_admin(identity)
    names = [item.name for item in body.tools]
    if len(set(names)) != len(names):
        raise errors.invalid("/tools", "an item is listed twice")
    async with transaction(engine, identity) as connection:
        server = await find_server(connection, server_id, lock=True)
        rows = {
            row.name: row
            for row in await connection.execute(
                text("SELECT name, listed, problem FROM mcp_server_tools WHERE server_id = :id"), {"id": server_id}
            )
        }
        for item in body.tools:
            row = rows.get(item.name)
            # Refused when the listing changed since the admin saw it, or the tool cannot be accepted (AGT-028).
            if row is None or row.listed is None or row.problem is not None or digest(row.listed) != item.digest:
                raise errors.conflict()
        await connection.execute(
            text(
                "UPDATE mcp_server_tools SET accepted = NULL, accepted_at = NULL"
                " WHERE server_id = :id AND NOT (name = ANY(:names))"
            ),
            {"id": server_id, "names": names},
        )
        for item in body.tools:
            await connection.execute(
                text(
                    "UPDATE mcp_server_tools SET accepted = CAST(:accepted AS jsonb), accepted_at = now()"
                    " WHERE server_id = :id AND name = :name"
                ),
                {"id": server_id, "name": item.name, "accepted": json.dumps(reviewed(rows[item.name].listed))},
            )
        await connection.execute(
            text("DELETE FROM mcp_server_tools WHERE server_id = :id AND listed IS NULL AND accepted IS NULL"),
            {"id": server_id},
        )
        return await _view(connection, server)


# --- The household's servers, for each user (AGT-029 to AGT-031) ---


async def _summary(connection: AsyncConnection, server: Server, denied: bool) -> schemas.McpServerSummary:
    rows = (
        await connection.execute(
            text(
                "SELECT name, listed, accepted, problem FROM mcp_server_tools WHERE server_id = :id"
                " AND accepted IS NOT NULL ORDER BY name"
            ),
            {"id": server.id},
        )
    ).all()
    return schemas.McpServerSummary(
        id=server.id,
        name=server.name,
        prefix=server.prefix,
        host=server.host,
        auth=cast(Any, server.auth),
        credential=await credential_state(connection, server),
        denied=denied,
        tools=[
            schemas.McpSummaryTool(
                model_name=f"{server.prefix}__{row.name}",
                title=row.accepted.get("title"),
                description=row.accepted.get("description"),
            )
            for row in rows
            if tool_status(row.listed, row.accepted, row.problem) == "accepted"
        ],
    )


@router.get("/mcp-servers", response_model=schemas.McpServerSummaryList)
async def list_my_mcp_servers(identity: Authenticated, engine: Engine) -> schemas.McpServerSummaryList:
    async with transaction(engine, identity) as connection:
        permissions = await permissions_of(connection, identity.user_id)
        return schemas.McpServerSummaryList(
            items=[
                await _summary(connection, server, permissions.denies_server(str(server.id)))
                for server in await servers_of(connection, enabled_only=True)
            ]
        )


async def _usable(connection: AsyncConnection, identity: Identity, server_id: uuid.UUID, auth: str) -> Server:
    """A server the user may connect to: switched on, not denied to them, and of that authentication."""
    server = await find_server(connection, server_id)
    if not server.enabled:
        raise errors.not_found()
    if (await permissions_of(connection, identity.user_id)).denies_server(str(server.id)):
        raise errors.permission_denied()
    if server.auth != auth:
        raise errors.conflict()
    return server


async def _summary_of(engine: AsyncEngine, identity: Identity, server_id: uuid.UUID) -> schemas.McpServerSummary:
    async with transaction(engine, identity) as connection:
        server = await find_server(connection, server_id)
        permissions = await permissions_of(connection, identity.user_id)
        return await _summary(connection, server, permissions.denies_server(str(server.id)))


@router.put("/mcp-servers/{server_id}/credential", response_model=schemas.McpServerSummary)
async def set_mcp_credential(
    server_id: uuid.UUID, body: schemas.McpCredentialRequest, identity: Authenticated, engine: Engine, key: SecretKey
) -> schemas.McpServerSummary:
    async with transaction(engine, identity) as connection:
        server = await _usable(connection, identity, server_id, "token")
    _LIMIT.take(identity.tenant_id)
    # Tried first; nothing of the listing is kept (AGT-030).
    await _list(server.target, body.token)
    async with transaction(engine, identity) as connection:
        await _store_credential(connection, identity, server, key, "token", body.token, None, None)
    return await _summary_of(engine, identity, server_id)


@router.delete("/mcp-servers/{server_id}/credential", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_mcp_credential(server_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await find_server(connection, server_id)
        # The tokens are forgotten, not revoked at the service (ADR-0100, point 8).
        await connection.execute(text("DELETE FROM mcp_credentials WHERE server_id = :id"), {"id": server_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _state_hash(state: str) -> bytes:
    return hashlib.sha256(state.encode()).digest()


@router.post("/mcp-servers/{server_id}/sign-in", response_model=schemas.McpSignInStarted)
async def start_mcp_sign_in(
    server_id: uuid.UUID, request: Request, identity: Authenticated, engine: Engine
) -> schemas.McpSignInStarted:
    origin = _public_origin(request)
    async with transaction(engine, identity) as connection:
        server = await _usable(connection, identity, server_id, "oauth")
        if origin is None or server.oauth is None:
            raise errors.conflict()
        await connection.execute(text("DELETE FROM mcp_sign_ins WHERE expires_at < now()"))
        state, verifier = secrets.token_urlsafe(32), new_verifier()
        expires_at = (
            await connection.execute(
                text(
                    "INSERT INTO mcp_sign_ins (id, tenant_id, owner_id, server_id, server_generation, state_hash,"
                    " code_verifier, created_at, expires_at) VALUES (:id, :tenant, :owner, :server, :generation,"
                    " :hash, :verifier, now(), now() + make_interval(mins => :minutes)) RETURNING expires_at"
                ),
                {
                    "id": uuid7(),
                    "tenant": identity.tenant_id,
                    "owner": identity.user_id,
                    "server": server.id,
                    "generation": server.generation,
                    "hash": _state_hash(state),
                    "verifier": verifier,
                    "minutes": SIGN_IN_MINUTES,
                },
            )
        ).scalar_one()
    return schemas.McpSignInStarted(
        authorization_url=authorization_url(server.oauth, server.url, origin, state, verifier), expires_at=expires_at
    )


@router.post("/mcp-sign-in", response_model=schemas.McpServerSummary)
async def complete_mcp_sign_in(
    body: schemas.CompleteMcpSignInRequest, request: Request, identity: Authenticated, engine: Engine, key: SecretKey
) -> schemas.McpServerSummary:
    origin = _public_origin(request)
    async with transaction(engine, identity) as connection:
        # Only a pending sign-in of the same user, used up at once (ADR-0100, point 5).
        found = (
            await connection.execute(
                text(
                    "DELETE FROM mcp_sign_ins WHERE state_hash = :hash"
                    " RETURNING server_id, server_generation, code_verifier, expires_at > now() AS pending"
                ),
                {"hash": _state_hash(body.state)},
            )
        ).one_or_none()
        server = None if found is None else await find_server(connection, found.server_id)
    if found is None or server is None or not found.pending:
        raise _sign_in_failed("no pending sign-in of yours has this state")
    if server.generation != found.server_generation or server.oauth is None or origin is None:
        raise _sign_in_failed("the server changed since the sign-in started")
    if body.error is not None or body.code is None:
        raise _sign_in_failed(f"the service answered {body.error or 'without a code'}")
    if (body.iss is not None or server.oauth.iss_parameter_supported) and not same_address(
        body.iss or "", server.oauth.issuer
    ):
        raise _sign_in_failed("the redirect came from another issuer")
    _LIMIT.take(identity.tenant_id)
    try:
        tokens = await exchange(
            server.oauth,
            server.client_secret(key),
            server.url,
            server.private_network,
            origin,
            body.code,
            found.code_verifier,
        )
    except OAuthError as error:
        raise _sign_in_failed(str(error)) from None
    try:
        await list_tools(server.target, tokens.access_token)
    except ServerError as error:
        raise _sign_in_failed(str(error)) from None
    async with transaction(engine, identity) as connection:
        await _store_credential(
            connection, identity, server, key, "oauth", tokens.access_token, tokens.refresh_token, tokens.expires_in
        )
    return await _summary_of(engine, identity, server.id)
