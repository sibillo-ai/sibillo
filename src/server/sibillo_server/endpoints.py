"""Connections to tenant model endpoints: public addresses only, checked at connection time (MOD-009, ADR-0061).

A tenant admin chooses the endpoint and the request leaves from the control
plane, so the address it reaches is checked when the connection is made,
against the addresses this module resolved itself, and redirects are never
followed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type Resolver = Callable[[str, int], Awaitable[list[Address]]]

# A NAT64 gateway can map these to any IPv4 address, private ones included.
NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Ranges that some Python releases judge global, and are not: IPv4-compatible IPv6, site-local IPv6, and the
# deprecated 6to4 relay anycast (ADR-0128).
NOT_GLOBAL = (
    ipaddress.ip_network("::/96"),
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("192.88.99.0/24"),
)
MODEL_TIMEOUT = httpx.Timeout(600, connect=10)
# What a response may hold, and for how long it may last: a model's answer, and anything else (ADR-0128).
MODEL_RESPONSE_BYTES = 64 * 1024 * 1024
MODEL_RESPONSE_SECONDS = 30 * 60
RESPONSE_BYTES = 16 * 1024 * 1024
RESPONSE_SECONDS = 2 * 60


def is_public(address: Address) -> bool:
    """A global unicast address; an IPv4-mapped IPv6 address is judged as its IPv4 address."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public(address.ipv4_mapped)
        if address in NAT64:
            return False
    if any(address.version == network.version and address in network for network in NOT_GLOBAL):
        return False
    return address.is_global and not address.is_multicast


class _BoundedStream(httpx.AsyncByteStream):
    """A response body that fails once it passes its bytes or its time (ADR-0128)."""

    def __init__(self, inner: httpx.AsyncByteStream, request: httpx.Request, limit: int, deadline: float) -> None:
        self._inner, self._request, self._limit, self._deadline = inner, request, limit, deadline

    async def __aiter__(self) -> AsyncIterator[bytes]:
        received = 0
        async for chunk in self._inner:
            received += len(chunk)
            if received > self._limit:
                raise httpx.ReadError(f"the response is larger than {self._limit} bytes", request=self._request)
            if time.monotonic() > self._deadline:
                raise httpx.ReadTimeout("the response took too long", request=self._request)
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class BoundedTransport(httpx.AsyncBaseTransport):
    """Bounds every response of `inner` in bytes and in total time (ADR-0128)."""

    def __init__(self, inner: httpx.AsyncBaseTransport, *, limit: int, seconds: float) -> None:
        self._inner, self._limit, self._seconds = inner, limit, seconds

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        deadline = time.monotonic() + self._seconds
        try:
            async with asyncio.timeout(self._seconds):
                response = await self._inner.handle_async_request(request)
        except TimeoutError:
            raise httpx.ReadTimeout("the response took too long", request=request) from None
        stream = response.stream
        if not isinstance(stream, httpx.AsyncByteStream):
            return response
        response.stream = _BoundedStream(stream, request, self._limit, deadline)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def bounded_client(
    *, private_network: bool, model: bool = False, timeout: httpx.Timeout | None = None
) -> httpx.AsyncClient:
    """The client of a connection: any address when the instance admin set it, else checked ones; bounded, and
    never following a redirect (ADR-0061, ADR-0128)."""
    inner: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport() if private_network else PublicEndpointTransport()
    limit, seconds = (MODEL_RESPONSE_BYTES, MODEL_RESPONSE_SECONDS) if model else (RESPONSE_BYTES, RESPONSE_SECONDS)
    return httpx.AsyncClient(
        transport=BoundedTransport(inner, limit=limit, seconds=seconds),
        follow_redirects=False,
        timeout=timeout or MODEL_TIMEOUT,
    )


async def resolve(host: str, port: int) -> list[Address]:
    """Every address `host` resolves to; a literal address resolves to itself."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    return [ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in found]


class PublicEndpointTransport(httpx.AsyncBaseTransport):
    """Connects only to addresses that `allowed` accepts, among those the transport resolved itself."""

    def __init__(
        self,
        *,
        resolve: Resolver = resolve,
        allowed: Callable[[Address], bool] = is_public,
        schemes: tuple[str, ...] = ("https",),
    ) -> None:
        self._resolve = resolve
        self._allowed = allowed
        # Only `https` but in tests of the transport against a server of their own (ADR-0128).
        self._schemes = schemes
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # A tenant admin's addresses are `https` only, whatever the caller checked (ADR-0128).
        if request.url.scheme not in self._schemes:
            raise httpx.ConnectError(f"{request.url.host} is not reached over https", request=request)
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = await self._resolve(host, port)
        if not addresses or not all(self._allowed(address) for address in addresses):
            raise httpx.ConnectError(f"{host} does not resolve only to public addresses", request=request)
        # The connection goes to a checked address; the Host header and TLS keep the endpoint's name.
        request.url = request.url.copy_with(host=str(addresses[0]))
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


def tenant_http_client(
    *,
    resolve: Resolver = resolve,
    allowed: Callable[[Address], bool] = is_public,
    schemes: tuple[str, ...] = ("https",),
) -> httpx.AsyncClient:
    """The HTTP client of a tenant model: checked addresses only, no redirects, bounded (ADR-0061, ADR-0128)."""
    return httpx.AsyncClient(
        transport=BoundedTransport(
            PublicEndpointTransport(resolve=resolve, allowed=allowed, schemes=schemes),
            limit=MODEL_RESPONSE_BYTES,
            seconds=MODEL_RESPONSE_SECONDS,
        ),
        follow_redirects=False,
        timeout=MODEL_TIMEOUT,
    )
