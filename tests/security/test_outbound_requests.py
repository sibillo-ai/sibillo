"""Outbound requests are bounded, and checked by what they reach (MOD-009, MOD-010, AGT-019, ADR-0128).

The transports of connections and of remote MCP servers are exercised here
against servers this test starts, and the API against the household of the
test session.
"""

from __future__ import annotations

import asyncio
import ipaddress
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from sibillo_server import endpoints
from sibillo_server.connections import Target, connection_client
from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.server import Server

MIB = 1024 * 1024


class _Large(BaseHTTPRequestHandler):
    """Answers every request with 17 MiB, more than any response other than a model's may hold."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        chunk = b"a" * MIB
        try:
            for _ in range(17):
                self.wfile.write(chunk)
        except OSError:
            pass


@pytest.fixture
def large_server() -> Iterator[str]:
    http = ThreadingHTTPServer(("127.0.0.1", 0), _Large)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{http.server_address[1]}"
    http.shutdown()


@pytest.mark.spec("MOD-009")
@pytest.mark.parametrize(
    "address",
    [
        "::10.0.0.1",
        "::7f00:1",
        "fec0::1",
        "192.88.99.1",
        "10.0.0.1",
        "127.0.0.1",
        "::ffff:192.168.1.1",
        "64:ff9b::a00:1",
    ],
)
def test_non_global_addresses_are_never_public(address: str) -> None:
    # A fixed table, so that no Python release changes the judgement (ADR-0128).
    assert endpoints.is_public(ipaddress.ip_address(address)) is False


@pytest.mark.spec("MOD-009")
@pytest.mark.parametrize("address", ["1.1.1.1", "9.9.9.9", "2606:4700:4700::1111"])
def test_global_addresses_are_public(address: str) -> None:
    assert endpoints.is_public(ipaddress.ip_address(address)) is True


@pytest.mark.spec("MOD-009")
def test_a_response_over_its_bound_fails(large_server: str) -> None:
    async def fetch() -> None:
        # Even for an address the instance admin set, which may be private.
        async with connection_client(Target("openai", large_server, None, True)) as client:
            await client.get(f"{large_server}/models")

    with pytest.raises(httpx.HTTPError):
        asyncio.run(fetch())


@pytest.mark.spec("MOD-009")
def test_the_checking_transport_refuses_plain_http_itself(large_server: str) -> None:
    async def fetch() -> None:
        async with endpoints.tenant_http_client(allowed=lambda _address: True) as client:
            await client.get(f"{large_server}/models")

    with pytest.raises(httpx.HTTPError, match="https"):
        asyncio.run(fetch())


@pytest.fixture
def tenant_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin")


def _openai(base_url: str, **changes: Any) -> dict[str, Any]:
    return {"name": f"Server {uuid7()}", "kind": "openai", "base_url": base_url, "location": "remote"} | changes


@pytest.mark.spec("MOD-010")
def test_only_the_instance_admins_addresses_may_be_local(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        refused = client.post("/tenant/connections", json=_openai("https://example.invalid/v1", location="local"))
    problem = assert_problem(refused, 422, "request.validation_failed")
    assert problem["errors"] == [{"location": "/location", "code": "local_needs_instance_admin"}]


@pytest.mark.spec("MOD-009")
def test_an_address_with_a_user_or_password_is_refused(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        for path in ("/tenant/connections", "/tenant/connection-tests"):
            refused = client.post(path, json=_openai("https://user:secret@example.invalid/v1"))
            assert_problem(refused, 422, "request.validation_failed")


@pytest.mark.spec("MOD-013")
def test_a_tenant_admins_test_names_no_address_it_resolved(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        result = body(client.post("/tenant/connection-tests", json=_openai("https://localhost/v1")))
    assert result["reason"] == "address_not_allowed"
    shown = str(result)
    for address in ("127.0.0.1", "::1"):
        assert address not in shown
