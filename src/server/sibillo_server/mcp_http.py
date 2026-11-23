"""The HTTP client of remote MCP servers and their authorization servers (AGT-019, AGT-031, ADR-0099, ADR-0100).

The MCP SDK speaks `httpx2`, so this is the transport of ADR-0061 for that
library: an address set by a user who is not the instance admin is reached
only at public addresses that the transport resolved itself, over `https`.
The instance admin's exemption covers the origin of the address they set,
not the other addresses an OAuth flow finds; every response is bounded in
bytes and time. Requests follow no redirect, but the MCP library itself
follows redirects within the server's origin (ADR-0128).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit

import httpx2

from sibillo_server.endpoints import RESPONSE_BYTES, RESPONSE_SECONDS, Address, Resolver, is_public, resolve

# Connecting, and each read; a call to a tool has its own limit (SIBILLO_MCP_CALL_SECONDS).
CONNECT_SECONDS = 10
READ_SECONDS = 60


class PublicEndpointTransport(httpx2.AsyncBaseTransport):
    """Connects only to addresses that `allowed` accepts, among those the transport resolved itself."""

    def __init__(self, *, resolve: Resolver = resolve, allowed: Callable[[Address], bool] = is_public) -> None:
        self._resolve = resolve
        self._allowed = allowed
        self._transport = httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.scheme != "https":
            raise httpx2.ConnectError(f"{request.url.host} is not reached over https", request=request)
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = await self._resolve(host, port)
        if not addresses or not all(self._allowed(address) for address in addresses):
            raise httpx2.ConnectError(f"{host} does not resolve only to public addresses", request=request)
        # The connection goes to a checked address; the Host header and TLS keep the server's name.
        request.url = request.url.copy_with(host=str(addresses[0]))
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


class _BoundedStream(httpx2.AsyncByteStream):
    """A response body that fails once it passes its bytes or its time (ADR-0128)."""

    def __init__(self, inner: httpx2.AsyncByteStream, request: httpx2.Request, deadline: float) -> None:
        self._inner, self._request, self._deadline = inner, request, deadline

    async def __aiter__(self) -> AsyncIterator[bytes]:
        received = 0
        async for chunk in self._inner:
            received += len(chunk)
            if received > RESPONSE_BYTES:
                raise httpx2.ReadError(f"the response is larger than {RESPONSE_BYTES} bytes", request=self._request)
            if time.monotonic() > self._deadline:
                raise httpx2.ReadTimeout("the response took too long", request=self._request)
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class _ServerTransport(httpx2.AsyncBaseTransport):
    """Any address for the origin the instance admin set, checked addresses for every other; bounded."""

    def __init__(self, *, origin: str | None, resolve: Resolver, allowed: Callable[[Address], bool]) -> None:
        self._origin = origin
        self._open = httpx2.AsyncHTTPTransport()
        self._checked = PublicEndpointTransport(resolve=resolve, allowed=allowed)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        exempt = self._origin is not None and _origin(str(request.url)) == self._origin
        transport = self._open if exempt else self._checked
        deadline = time.monotonic() + RESPONSE_SECONDS
        try:
            async with asyncio.timeout(RESPONSE_SECONDS):
                response = await transport.handle_async_request(request)
        except TimeoutError:
            raise httpx2.ReadTimeout("the response took too long", request=request) from None
        if isinstance(response.stream, httpx2.AsyncByteStream):
            response.stream = _BoundedStream(response.stream, request, deadline)
        return response

    async def aclose(self) -> None:
        await self._open.aclose()
        await self._checked.aclose()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}:{port}"


def mcp_http_client(
    *,
    private_network: bool,
    server_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    resolve: Resolver = resolve,
    allowed: Callable[[Address], bool] = is_public,
) -> httpx2.AsyncClient:
    """The client that reaches a server's address, and its authorization server's, by the server's rules.

    When the instance admin set the server's address, `server_url`'s origin may be any address (ADR-0064,
    point 4); every other origin, such as an authorization server elsewhere, is checked (ADR-0128).
    """
    limit = httpx2.Timeout(timeout or READ_SECONDS, connect=CONNECT_SECONDS)
    origin = _origin(server_url) if private_network and server_url is not None else None
    return httpx2.AsyncClient(
        transport=_ServerTransport(origin=origin, resolve=resolve, allowed=allowed),
        headers=headers,
        follow_redirects=False,
        timeout=limit,
    )
