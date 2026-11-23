"""Signing in to remote MCP servers with OAuth (AGT-031, ADR-0100).

Discovery as the MCP authorization specification describes it: the server's
401 names its protected resource metadata (RFC 9728), which names an
authorization server, whose metadata (RFC 8414, or OpenID Connect discovery)
gives its endpoints. Sibillo signs each user in with the authorization code
flow and PKCE (`S256`), for the resource the server's metadata names, which
is the server or contains it (`resource`, RFC 8707), and renews their
tokens. Every request it makes itself follows the server's address rules
(`mcp_http`).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any, cast
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx2

from sibillo_server.mcp_http import mcp_http_client

SECONDS = 15
# The page of the web app the redirect lands on (ADR-0100, point 4).
REDIRECT_PATH = "/mcp-sign-in"
# Where the API serves Sibillo's Client ID Metadata Document (ADR-0100, point 3).
CLIENT_METADATA_PATH = "/v1/mcp-client"
CLIENT_NAME = "Sibillo"
DETAIL_CHARS = 300
# How a client authenticates to the token endpoint with a secret (RFC 6749).
BASIC, POST = "client_secret_basic", "client_secret_post"
_PARAMETER = re.compile(r'([A-Za-z_]+)\s*=\s*(?:"([^"]*)"|([^\s,]+))')


@dataclass
class OAuthError(Exception):
    """What sign-in needs is missing, or a step failed: which, and why."""

    step: str
    detail: str

    def __str__(self) -> str:
        return f"{self.step}: {self.detail}"


@dataclass(frozen=True)
class OAuthSettings:
    """What discovery found, and the client: `mcp_servers.oauth`."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    iss_parameter_supported: bool
    scope: str | None
    client_id: str
    client_registration: str
    token_endpoint_auth_method: str
    # The resource tokens are asked for; none in settings kept before it was, which ask for the server's address.
    resource: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: Any) -> OAuthSettings:
        return cls(**cast(dict[str, Any], value))


@dataclass(frozen=True)
class Discovered:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    iss_parameter_supported: bool
    auth_methods: tuple[str, ...]
    scope: str | None
    resource: str
    # The authorization server reads Client ID Metadata Documents.
    metadata_documents: bool = False


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_in: int | None


def same_address(first: str, second: str) -> bool:
    """Two addresses name the same resource, but for a final slash and the case of the scheme and host."""

    def normal(address: str) -> tuple[str, str, str, str]:
        parts = urlsplit(address.strip())
        return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query)

    return normal(first) == normal(second)


def contains(resource: str, url: str) -> bool:
    """A resource names the server's address or contains it: same origin, no query, a path prefix at a `/`."""
    outer, inner = urlsplit(resource.strip()), urlsplit(url.strip())
    if (outer.scheme.lower(), outer.netloc.lower()) != (inner.scheme.lower(), inner.netloc.lower()):
        return False
    if outer.query or outer.fragment:
        return same_address(resource, url)
    prefix, path = outer.path.rstrip("/"), inner.path.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def redirect_uri(public_origin: str, server_id: uuid.UUID) -> str:
    """The redirect address of one server's sign-ins: each server has its own (ADR-0122)."""
    return f"{public_origin.rstrip('/')}{REDIRECT_PATH}/{server_id}"


def client_metadata_url(public_origin: str, server_id: uuid.UUID) -> str | None:
    """The address of Sibillo's Client ID Metadata Document for one server, which is its client ID there; none
    without `https` (ADR-0122)."""
    if urlsplit(public_origin).scheme != "https":
        return None
    return f"{public_origin.rstrip('/')}{CLIENT_METADATA_PATH}/{server_id}"


def client_metadata(public_origin: str, server_id: uuid.UUID) -> dict[str, Any]:
    """Sibillo as the OAuth client of one server (RFC 7591): what registration sends, and what its document says,
    naming that server's redirect address alone (ADR-0122)."""
    metadata: dict[str, Any] = {
        "client_name": CLIENT_NAME,
        "client_uri": public_origin.rstrip("/"),
        "redirect_uris": [redirect_uri(public_origin, server_id)],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    document = client_metadata_url(public_origin, server_id)
    return metadata if document is None else {"client_id": document, **metadata}


def sign_in_client_id(settings: OAuthSettings, public_origin: str, server_id: uuid.UUID) -> str:
    """The client ID of a new sign-in: for Sibillo's documents, the document of the server's ID now (ADR-0122)."""
    if settings.client_registration == "metadata_document":
        return client_metadata_url(public_origin, server_id) or settings.client_id
    return settings.client_id


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


def _challenge_parameters(header: str) -> dict[str, str]:
    """The parameters of a `Bearer` challenge in `WWW-Authenticate`."""
    if not header.lower().startswith("bearer"):
        return {}
    return {match[0].lower(): match[1] or match[2] for match in _PARAMETER.findall(header[6:])}


def _check_scheme(address: str, private_network: bool, step: str) -> None:
    scheme = urlsplit(address).scheme
    if scheme != "https" and not (private_network and scheme == "http"):
        raise OAuthError(step, f"{urlsplit(address).hostname or address} is not an https address")


def _well_known(address: str, suffix: str) -> list[str]:
    """The well-known addresses of a URL, with its path first, then without (RFC 8414, RFC 9728)."""
    parts = urlsplit(address)
    path = parts.path.rstrip("/")
    found = [urlunsplit((parts.scheme, parts.netloc, f"/.well-known/{suffix}{path}", "", ""))] if path else []
    found.append(urlunsplit((parts.scheme, parts.netloc, f"/.well-known/{suffix}", "", "")))
    return found


async def _json(client: httpx2.AsyncClient, address: str, step: str) -> dict[str, Any] | None:
    try:
        response = await client.get(address, headers={"Accept": "application/json"})
    except httpx2.HTTPError as error:
        raise OAuthError(step, f"{urlsplit(address).hostname}: {str(error)[:DETAIL_CHARS]}") from None
    if response.status_code != 200:
        return None
    try:
        value = response.json()
    except ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


async def discover(url: str, private_network: bool) -> Discovered:
    """Find the server's authorization server, and check it offers what sign-in needs (ADR-0100, point 2)."""
    async with mcp_http_client(private_network=private_network, timeout=SECONDS) as client:
        try:
            response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": CLIENT_NAME, "version": "1"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
        except httpx2.HTTPError as error:
            raise OAuthError("connect", str(error)[:DETAIL_CHARS]) from None
        if response.status_code != 401:
            raise OAuthError("challenge", f"the server answered {response.status_code} without asking to sign in")
        challenge = _challenge_parameters(response.headers.get("www-authenticate", ""))
        candidates = [challenge["resource_metadata"]] if "resource_metadata" in challenge else []
        candidates += _well_known(url, "oauth-protected-resource")
        resource: dict[str, Any] | None = None
        for candidate in candidates:
            _check_scheme(candidate, private_network, "resource_metadata")
            resource = await _json(client, candidate, "resource_metadata")
            if resource is not None:
                break
        if resource is None:
            raise OAuthError("resource_metadata", "the server publishes no protected resource metadata")
        named = str(resource.get("resource", ""))
        if not contains(named, url):
            raise OAuthError("resource_metadata", "the metadata is of another resource")
        servers = resource.get("authorization_servers")
        if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
            raise OAuthError("resource_metadata", "the metadata names no authorization server")
        issuer = str(cast(list[Any], servers)[0])
        _check_scheme(issuer, private_network, "authorization_server")
        metadata: dict[str, Any] | None = None
        # In the order of the MCP authorization specification: RFC 8414, then OpenID Connect discovery.
        addresses = (
            _well_known(issuer, "oauth-authorization-server")[:1] + _well_known(issuer, "openid-configuration")[:1]
        )
        if urlsplit(issuer).path.rstrip("/"):
            addresses.append(issuer.rstrip("/") + "/.well-known/openid-configuration")
        for address in addresses:
            metadata = await _json(client, address, "authorization_server")
            if metadata is not None:
                break
    if metadata is None:
        raise OAuthError("authorization_server", "the authorization server publishes no metadata")
    if not same_address(str(metadata.get("issuer", "")), issuer):
        raise OAuthError("authorization_server", "the metadata is of another issuer")
    if "S256" not in cast(list[Any], metadata.get("code_challenge_methods_supported") or []):
        raise OAuthError("authorization_server", "the authorization server does not offer PKCE with S256")
    response_types = metadata.get("response_types_supported")
    if isinstance(response_types, list) and "code" not in response_types:
        raise OAuthError("authorization_server", "the authorization server does not offer the code flow")
    endpoints: list[str] = []
    for name in ("authorization_endpoint", "token_endpoint"):
        value = metadata.get(name)
        if not isinstance(value, str) or not value:
            raise OAuthError("authorization_server", f"the metadata has no {name}")
        _check_scheme(value, private_network, "authorization_server")
        endpoints.append(value)
    registration = metadata.get("registration_endpoint")
    if isinstance(registration, str) and registration:
        _check_scheme(registration, private_network, "authorization_server")
    else:
        registration = None
    scope = challenge.get("scope")
    if not scope:
        supported = resource.get("scopes_supported")
        scope = " ".join(str(item) for item in cast(list[Any], supported)) if isinstance(supported, list) else None
    methods = metadata.get("token_endpoint_auth_methods_supported")
    return Discovered(
        issuer=issuer,
        authorization_endpoint=endpoints[0],
        token_endpoint=endpoints[1],
        registration_endpoint=registration,
        iss_parameter_supported=metadata.get("authorization_response_iss_parameter_supported") is True,
        auth_methods=tuple(str(item) for item in cast(list[Any], methods))
        if isinstance(methods, list)
        else ("client_secret_basic",),
        scope=scope or None,
        resource=named.strip(),
        metadata_documents=metadata.get("client_id_metadata_document_supported") is True,
    )


async def settings_for(
    url: str,
    private_network: bool,
    public_origin: str,
    server_id: uuid.UUID,
    client_id: str | None,
    client_secret: str | None,
) -> tuple[OAuthSettings, str | None]:
    """Discover the authorization server, and use the given client or register one: the settings, and a secret."""
    found = await discover(url, private_network)
    if client_id is not None:
        if client_secret is None:
            method = "none"
        elif "client_secret_basic" in found.auth_methods or "client_secret_post" not in found.auth_methods:
            method = "client_secret_basic"
        else:
            method = "client_secret_post"
        registration, secret = "given", client_secret
    elif found.metadata_documents and (document := client_metadata_url(public_origin, server_id)) is not None:
        # The authorization server fetches Sibillo's document: nothing to register (ADR-0100, point 3).
        client_id, secret, method, registration = document, None, "none", "metadata_document"
    else:
        if found.registration_endpoint is None:
            raise OAuthError("register", "the authorization server registers no clients: give a client ID")
        client_id, secret, method = await _register(
            found.registration_endpoint, private_network, public_origin, server_id
        )
        registration = "dynamic"
    settings = OAuthSettings(
        issuer=found.issuer,
        authorization_endpoint=found.authorization_endpoint,
        token_endpoint=found.token_endpoint,
        iss_parameter_supported=found.iss_parameter_supported,
        scope=found.scope,
        client_id=client_id,
        client_registration=registration,
        token_endpoint_auth_method=method,
        resource=found.resource,
    )
    return settings, secret


async def _register(
    endpoint: str, private_network: bool, public_origin: str, server_id: uuid.UUID
) -> tuple[str, str | None, str]:
    """Register Sibillo as a client, dynamically (RFC 7591)."""
    async with mcp_http_client(private_network=private_network, timeout=SECONDS) as client:
        try:
            response = await client.post(
                endpoint,
                json={
                    name: value
                    for name, value in client_metadata(public_origin, server_id).items()
                    if name != "client_id"
                },
            )
        except httpx2.HTTPError as error:
            raise OAuthError("register", str(error)[:DETAIL_CHARS]) from None
    try:
        answer = response.json() if response.status_code in (200, 201) else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or not isinstance(cast(dict[str, Any], answer).get("client_id"), str):
        raise OAuthError("register", f"the authorization server answered {response.status_code}")
    registered = cast(dict[str, Any], answer)
    secret = registered.get("client_secret")
    secret = secret if isinstance(secret, str) and secret else None
    method = str(registered.get("token_endpoint_auth_method") or ("client_secret_basic" if secret else "none"))
    if method not in ("none", "client_secret_basic", "client_secret_post"):
        method = "client_secret_basic" if secret else "none"
    return str(registered["client_id"]), secret, method


def authorization_url(
    settings: OAuthSettings, url: str, public_origin: str, server_id: uuid.UUID, state: str, verifier: str
) -> str:
    """The service's sign-in page for one sign-in (ADR-0100, point 5)."""
    query = {
        "response_type": "code",
        "client_id": sign_in_client_id(settings, public_origin, server_id),
        "redirect_uri": redirect_uri(public_origin, server_id),
        "state": state,
        "code_challenge": challenge_of(verifier),
        "code_challenge_method": "S256",
        "resource": settings.resource or url,
    }
    if settings.scope:
        query["scope"] = settings.scope
    separator = "&" if urlsplit(settings.authorization_endpoint).query else "?"
    return f"{settings.authorization_endpoint}{separator}{urlencode(query)}"


async def _token_request(
    settings: OAuthSettings, secret: str | None, private_network: bool, form: dict[str, str], step: str
) -> Tokens:
    headers: dict[str, str] = {"Accept": "application/json"}
    form = {**form}
    if settings.token_endpoint_auth_method == BASIC and secret is not None:
        pair = f"{settings.client_id}:{secret}".encode()
        headers["Authorization"] = f"Basic {base64.b64encode(pair).decode()}"
    else:
        form["client_id"] = settings.client_id
        if settings.token_endpoint_auth_method == POST and secret is not None:
            form["client_secret"] = secret
    async with mcp_http_client(private_network=private_network, timeout=SECONDS) as client:
        try:
            response = await client.post(settings.token_endpoint, data=form, headers=headers)
        except httpx2.HTTPError as error:
            raise OAuthError(step, str(error)[:DETAIL_CHARS]) from None
    try:
        answer: Any = response.json()
    except ValueError:
        answer = None
    if response.status_code != 200 or not isinstance(answer, dict):
        error = cast(dict[str, Any], answer).get("error") if isinstance(answer, dict) else None
        raise OAuthError(step, f"the token endpoint answered {response.status_code} {error or ''}".strip())
    tokens = cast(dict[str, Any], answer)
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access or str(tokens.get("token_type", "")).lower() != "bearer":
        raise OAuthError(step, "the token endpoint gave no bearer token")
    refresh = tokens.get("refresh_token")
    expires = tokens.get("expires_in")
    return Tokens(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_in=int(expires) if isinstance(expires, int | float) and expires > 0 else None,
    )


async def exchange(
    settings: OAuthSettings,
    secret: str | None,
    url: str,
    private_network: bool,
    public_origin: str,
    server_id: uuid.UUID,
    code: str,
    verifier: str,
) -> Tokens:
    """Exchange an authorization code for the server's tokens, as the client the sign-in named (ADR-0122)."""
    return await _token_request(
        replace(settings, client_id=sign_in_client_id(settings, public_origin, server_id)),
        secret,
        private_network,
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri(public_origin, server_id),
            "resource": settings.resource or url,
        },
        "exchange",
    )


async def renew(settings: OAuthSettings, secret: str | None, url: str, private_network: bool, refresh: str) -> Tokens:
    """Renew the tokens; the answer may carry a new refresh token, which replaces the old (ADR-0100, point 7)."""
    return await _token_request(
        settings,
        secret,
        private_network,
        {"grant_type": "refresh_token", "refresh_token": refresh, "resource": settings.resource or url},
        "renew",
    )
