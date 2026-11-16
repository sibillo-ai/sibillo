"""The HTTP client of remote MCP servers and their authorization servers (AGT-019, AGT-031, ADR-0099, ADR-0100).

The MCP SDK speaks `httpx2`, so this is the transport of ADR-0061 for that
library: an address set by a user who is not the instance admin is reached
only at public addresses that the transport resolved itself, and no request
follows a redirect, whoever set the address.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2

from sibillo_server.endpoints import Address, Resolver, is_public, resolve

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


def mcp_http_client(
    *,
    private_network: bool,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    resolve: Resolver = resolve,
    allowed: Callable[[Address], bool] = is_public,
) -> httpx2.AsyncClient:
    """The client that reaches a server's address, and its authorization server's, by the server's rules."""
    limit = httpx2.Timeout(timeout or READ_SECONDS, connect=CONNECT_SECONDS)
    if private_network:
        # Set by the instance admin: any address (ADR-0064, point 4).
        return httpx2.AsyncClient(headers=headers, follow_redirects=False, timeout=limit)
    return httpx2.AsyncClient(
        transport=PublicEndpointTransport(resolve=resolve, allowed=allowed),
        headers=headers,
        follow_redirects=False,
        timeout=limit,
    )
