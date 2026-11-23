"""Accounts and the HTTP surface hold against a stolen session (AUTH-005, AUTH-006, AUTH-008, AUTH-010, ADR-0131).

A stolen admin session must not weaken its own account, nor the instance
admin's; a household must keep an admin; the source of a sign-in is the one
the trusted proxy saw; and every answer carries the headers that keep it out
of caches, frames and other origins.
"""

from __future__ import annotations

import ipaddress
import secrets
import uuid

import httpx
import pytest
from argon2 import PasswordHasher

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.server import Server


@pytest.fixture
def tenant(database: Database) -> uuid.UUID:
    return create_tenant(database)


def _patch(server: Server, token: str, user: Account, **changes: object) -> httpx.Response:
    with server.client(token) as client:
        return client.patch(f"/tenant/users/{user.id}", json=changes)


@pytest.mark.spec("AUTH-008", "AUTH-009")
def test_a_tenant_admin_disables_and_reenables_an_account_and_changes_its_role(
    database: Database, server: Server, tenant: uuid.UUID
) -> None:
    admin = create_account(database, tenant, "tenant_admin")
    member = create_account(database, tenant)
    admin_token, member_token = login(server, admin), login(server, member)
    disabled = _patch(server, admin_token, member, disabled=True)
    assert disabled.status_code == 200, disabled.text
    assert body(disabled)["disabled"] is True
    # Its sessions end at once (AUTH-009).
    with server.client(member_token) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")
    enabled = _patch(server, admin_token, member, disabled=False, role="tenant_admin")
    assert enabled.status_code == 200, enabled.text
    assert (body(enabled)["disabled"], body(enabled)["role"]) == (False, "tenant_admin")


@pytest.mark.spec("AUTH-008")
def test_an_admin_changes_neither_their_own_account_nor_the_last_admin(
    database: Database, server: Server, tenant: uuid.UUID
) -> None:
    admin = create_account(database, tenant, "tenant_admin")
    token = login(server, admin)
    for change in ({"disabled": True}, {"role": "member"}):
        assert_problem(_patch(server, token, admin, **change), 403, "permission.denied")
    # Another admin may not leave the household without one: there would be none left once this one goes.
    other = create_account(database, tenant, "tenant_admin")
    assert _patch(server, token, other, role="member").status_code == 200
    assert_problem(_patch(server, login(server, other), admin, role="member"), 403, "permission.denied")


@pytest.mark.spec("AUTH-008")
def test_a_tenant_admin_cannot_change_the_instance_admin(database: Database, server: Server) -> None:
    tenant = create_tenant(database)
    instance_admin = create_account(database, tenant, "tenant_admin", instance_admin=True)
    admin = create_account(database, tenant, "tenant_admin")
    assert_problem(_patch(server, login(server, admin), instance_admin, disabled=True), 403, "permission.denied")


@pytest.mark.spec("AUTH-010")
def test_an_admin_removes_neither_their_own_passkeys_nor_the_instance_admins(
    database: Database, server: Server
) -> None:
    tenant = create_tenant(database)
    instance_admin = create_account(database, tenant, "tenant_admin", instance_admin=True)
    admin = create_account(database, tenant, "tenant_admin")
    member = create_account(database, tenant)
    with server.client(login(server, admin)) as client:
        for target in (admin, instance_admin):
            assert_problem(client.delete(f"/tenant/users/{target.id}/passkeys"), 403, "permission.denied")
        assert client.delete(f"/tenant/users/{member.id}/passkeys").status_code == 204


def _failure(server: Server, headers: list[tuple[str, str]], username: str) -> httpx.Response:
    with httpx.Client(base_url=server.base_url, timeout=30) as client:
        return client.post(
            "/auth/login",
            json={"username": username, "password": "wrong", "device_name": "x"},
            headers=headers,
        )


@pytest.mark.spec("AUTH-006")
def test_every_forwarding_line_is_read(server: Server) -> None:
    # A proxy that adds its own line leaves the first to the client; the last address is what it saw (ADR-0131).
    seen = str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("100.64.0.0")) + secrets.randbelow(1 << 22)))
    for _ in range(20):
        chosen = str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("100.64.0.0")) + secrets.randbelow(1 << 22)))
        lines = [("X-Forwarded-For", chosen), ("X-Forwarded-For", seen)]
        assert_problem(_failure(server, lines, f"user-{uuid.uuid4()}"), 401, "auth.invalid_credentials")
    lines = [("X-Forwarded-For", "203.0.113.7"), ("X-Forwarded-For", seen)]
    assert_problem(_failure(server, lines, f"user-{uuid.uuid4()}"), 429, "auth.rate_limited")


@pytest.mark.spec("AUTH-006")
def test_an_ipv6_source_counts_as_its_64(server: Server) -> None:
    network = ipaddress.IPv6Network(f"2001:db8:{secrets.randbelow(1 << 16):x}:{secrets.randbelow(1 << 16):x}::/64")
    for index in range(20):
        address = str(network[index * 7919 + 1])
        failure = _failure(server, [("X-Forwarded-For", address)], f"user-{uuid.uuid4()}")
        assert_problem(failure, 401, "auth.invalid_credentials")
    last = _failure(server, [("X-Forwarded-For", str(network[999_999]))], f"user-{uuid.uuid4()}")
    assert_problem(last, 429, "auth.rate_limited")


@pytest.mark.spec("AUTH-005")
def test_answers_carry_their_security_headers(server: Server, database: Database) -> None:
    with server.client() as client:
        answer = client.get("/health")
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["cross-origin-opener-policy"] == "same-origin"
    assert answer.headers["cross-origin-resource-policy"] == "same-origin"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert "camera" in answer.headers["permissions-policy"]
    # The session cookie can only be set by this host (ADR-0131).
    account = create_account(database, create_tenant(database))
    with server.client() as client:
        signed_in = client.post(
            "/auth/login",
            json={
                "username": account.username,
                "password": account.password,
                "device_name": "x",
                "session_delivery": "cookie",
            },
        )
    assert signed_in.status_code == 201, signed_in.text
    assert signed_in.headers["set-cookie"].startswith("__Host-sibillo_session=")
    assert "; Path=/" in signed_in.headers["set-cookie"]
    assert "Domain=" not in signed_in.headers["set-cookie"]


@pytest.mark.spec("AUTH-004")
def test_a_user_has_at_most_fifty_sessions(database: Database, server: Server) -> None:
    account = create_account(database, create_tenant(database))
    first = login(server, account)
    for _ in range(50):
        login(server, account)
    # The least recently used gave way (ADR-0131).
    with server.client(first) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-004")
def test_a_session_ends_a_year_after_it_was_made(database: Database, server: Server) -> None:
    account = create_account(database, create_tenant(database))
    token = login(server, account)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE device_sessions SET created_at = now() - interval '366 days' WHERE user_id = %s", (account.id,)
        )
    with server.client(token) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-001")
def test_a_password_with_older_parameters_is_hashed_again_at_sign_in(database: Database, server: Server) -> None:
    account = create_account(database, create_tenant(database))
    old = PasswordHasher(time_cost=1, memory_cost=8192).hash(account.password)
    with database.superuser() as conn, conn.transaction():
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(account.id),))
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (old, account.id))
    login(server, account)
    with database.superuser() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (account.id,)).fetchone()
    assert row is not None
    assert row[0] != old
    assert not PasswordHasher().check_needs_rehash(row[0])
