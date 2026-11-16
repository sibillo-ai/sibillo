"""Remote MCP servers are reached only at checked addresses (AGT-019, AGT-031, ADR-0099, ADR-0100, T-27, T-38).

No test can serve an MCP server on a public address, so these tests use the
MCP client's HTTP client directly, with an injected resolver and, where a
connection must succeed, a policy that allows the loopback address; and the
database's guard of `private_network`, as for connections.
"""

from __future__ import annotations

import asyncio
import ipaddress
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx2
import psycopg
import pytest

from sibillo_server.endpoints import Address
from sibillo_server.mcp_http import mcp_http_client
from tests.support.database import Context, Database, app_transaction, uuid7
from tests.support.world import World


class _Server:
    """A local HTTP server that records requests and redirects `/redirect` to `/secret`."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.hosts: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                server.paths.append(self.path)
                server.hosts.append(self.headers.get("Host", ""))
                if "redirect" in self.path:
                    self.send_response(307)
                    self.send_header("Location", f"http://127.0.0.1:{server.port}/secret")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = b'{"jsonrpc": "2.0", "id": 1, "result": {}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def local_server() -> Iterator[_Server]:
    server = _Server()
    yield server
    server.http.shutdown()


def _resolver(addresses: dict[str, list[str]]) -> Callable[[str, int], Awaitable[list[Address]]]:
    async def resolve(host: str, port: int) -> list[Address]:
        return [ipaddress.ip_address(address) for address in addresses.get(host, [])]

    return resolve


def _loopback_allowed(address: Address) -> bool:
    return address.is_loopback


def _post(client: httpx2.AsyncClient, url: str) -> httpx2.Response:
    async def request() -> httpx2.Response:
        async with client:
            return await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    return asyncio.run(request())


@pytest.mark.spec("AGT-019")
@pytest.mark.parametrize("addresses", [["10.0.0.5"], ["93.184.216.34", "192.168.1.1"], ["127.0.0.1"], []])
def test_names_with_a_private_or_no_address_are_refused_at_connection_time(addresses: list[str]) -> None:
    client = mcp_http_client(private_network=False, resolve=_resolver({"mcp.example": addresses}))
    with pytest.raises(httpx2.ConnectError):
        _post(client, "https://mcp.example/mcp")


@pytest.mark.spec("AGT-019")
def test_the_connection_goes_to_the_checked_address_with_the_servers_name(local_server: _Server) -> None:
    # `mcp.invalid` resolves nowhere: only the client's own resolution can reach the server.
    client = mcp_http_client(
        private_network=False, resolve=_resolver({"mcp.invalid": ["127.0.0.1"]}), allowed=_loopback_allowed
    )
    response = _post(client, f"http://mcp.invalid:{local_server.port}/mcp")
    assert response.status_code == 200
    assert local_server.hosts == [f"mcp.invalid:{local_server.port}"]


@pytest.mark.spec("AGT-019", "AGT-031")
@pytest.mark.parametrize("private_network", [False, True])
def test_redirects_are_not_followed(local_server: _Server, private_network: bool) -> None:
    client = mcp_http_client(
        private_network=private_network, resolve=_resolver({"mcp.invalid": ["127.0.0.1"]}), allowed=_loopback_allowed
    )
    url = f"http://{'127.0.0.1' if private_network else 'mcp.invalid'}:{local_server.port}/redirect"
    response = _post(client, url)
    assert response.status_code == 307
    assert local_server.paths == ["/redirect"]


def _new_server(conn: psycopg.Connection, tenant_id: uuid.UUID, *, private_network: bool) -> uuid.UUID | None:
    """Add a server; return its ID if the row was stored with the given `private_network`."""
    server_id = uuid7()
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO mcp_servers (id, tenant_id, name, prefix, url, auth, generation, private_network,"
                " enabled, created_at, updated_at) VALUES (%s, %s, %s, %s, 'http://192.168.1.10:8123/api/mcp',"
                " 'none', gen_random_uuid(), %s, true, now(), now())",
                (server_id, tenant_id, f"Server {server_id}", f"s{server_id.hex[:8]}", private_network),
            )
    except psycopg.DatabaseError:
        return None
    row = conn.execute("SELECT private_network FROM mcp_servers WHERE id = %s", (server_id,)).fetchone()
    return server_id if row == (private_network,) else None


def _admin(world: World, *, instance_admin: bool = False) -> Context:
    return Context(world.tenant_a, world.anna.id, "tenant_admin", instance_admin)


@pytest.mark.spec("AGT-019")
def test_only_instance_admins_mark_a_server_private(database: Database, world: World) -> None:
    with app_transaction(database, _admin(world)) as conn:
        assert _new_server(conn, world.tenant_a, private_network=False)
        assert not _new_server(conn, world.tenant_a, private_network=True)
    with app_transaction(database, _admin(world, instance_admin=True)) as conn:
        assert _new_server(conn, world.tenant_a, private_network=True)


@pytest.mark.spec("AGT-019")
def test_a_new_address_from_another_admin_clears_private_network(database: Database, world: World) -> None:
    with app_transaction(database, _admin(world, instance_admin=True)) as conn:
        server_id = _new_server(conn, world.tenant_a, private_network=True)
        assert server_id
        conn.execute(
            "SELECT set_config('app.instance_admin', 'false', true)",
        )
        conn.execute("UPDATE mcp_servers SET name = 'Renamed' WHERE id = %s", (server_id,))
        row: Any = conn.execute("SELECT private_network FROM mcp_servers WHERE id = %s", (server_id,)).fetchone()
        assert row == (True,)
        try:
            with conn.transaction():
                conn.execute(
                    "UPDATE mcp_servers SET url = 'http://192.168.1.11:8123/api/mcp', private_network = true"
                    " WHERE id = %s",
                    (server_id,),
                )
        except psycopg.DatabaseError:
            pass
        row = conn.execute("SELECT url, private_network FROM mcp_servers WHERE id = %s", (server_id,)).fetchone()
        assert row != ("http://192.168.1.11:8123/api/mcp", True)


@pytest.mark.spec("AGT-019", "TEN-006")
def test_members_cannot_change_a_households_servers(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.alice.id)) as conn:
        assert not _new_server(conn, world.tenant_a, private_network=False)
        changed = conn.execute(
            "UPDATE mcp_servers SET name = 'Changed' WHERE tenant_id = %s", (world.tenant_a,)
        ).rowcount
        assert changed == 0
        assert conn.execute("SELECT 1 FROM mcp_servers").fetchall()
    with app_transaction(database, Context(world.tenant_b, world.bob.id, "tenant_admin")) as conn:
        assert conn.execute("SELECT 1 FROM mcp_servers WHERE tenant_id = %s", (world.tenant_a,)).fetchall() == []
        assert not _new_server(conn, world.tenant_a, private_network=False)
