"""Users change their own password, and replace an initial one first (AUTH-011, AUTH-012, ADR-0105)."""

from __future__ import annotations

import uuid
from dataclasses import replace

import httpx
import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.server import Server


@pytest.fixture
def member(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin")


def _new_password() -> str:
    return f"new password {uuid7()}"


def _change(client: httpx.Client, current: str, new: str) -> httpx.Response:
    return client.post("/me/password", json={"current_password": current, "new_password": new})


def _sign_in(server: Server, username: str, password: str) -> httpx.Response:
    with server.client() as client:
        return client.post("/auth/login", json={"username": username, "password": password, "device_name": "x"})


def _created_by(server: Server, admin: Account, role: str = "member") -> Account:
    """An account created by a tenant admin through the API, with an initial password."""
    username, password = f"new-{uuid7()}", f"initial password {uuid7()}"
    with server.client(login(server, admin)) as client:
        created = client.post(
            "/tenant/users",
            json={"username": username, "display_name": "New user", "password": password, "role": role},
        )
    assert created.status_code == 201, created.text
    user = body(created)
    assert user["password_change_required"] is True
    return Account(uuid.UUID(user["id"]), admin.tenant_id, username, password, role, False)


@pytest.mark.spec("AUTH-011")
def test_users_change_their_password_with_the_current_one(server: Server, member: Account) -> None:
    new = _new_password()
    with server.client(login(server, member)) as client:
        response = _change(client, member.password, new)
        assert response.status_code == 204, response.text
        # The session that made the change stays.
        assert client.get("/me").status_code == 200
    assert_problem(_sign_in(server, member.username, member.password), 401, "auth.invalid_credentials")
    assert _sign_in(server, member.username, new).status_code == 201


@pytest.mark.spec("AUTH-011")
def test_a_change_revokes_every_other_session(database: Database, server: Server, member: Account) -> None:
    other = login(server, member, "other device")
    with server.client(other) as client:
        other_session = next(s["id"] for s in body(client.get("/me/sessions"))["items"] if s["current"])
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO notification_subscriptions (tenant_id, owner_id, device_session_id, endpoint, p256dh, auth,"
            " created_at) VALUES (%s, %s, %s, %s, 'p256dh', 'auth', now())",
            (member.tenant_id, member.id, other_session, f"https://fcm.googleapis.com/fcm/send/{other_session}"),
        )
    with server.client(login(server, member, "this device")) as client:
        assert _change(client, member.password, _new_password()).status_code == 204
        assert [s["device_name"] for s in body(client.get("/me/sessions"))["items"]] == ["this device"]
    with server.client(other) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")
    # A revoked session is notified no more (ADR-0101).
    with database.superuser() as conn:
        left = conn.execute(
            "SELECT count(*) FROM notification_subscriptions WHERE device_session_id = %s", (other_session,)
        ).fetchone()
    assert left == (0,)


@pytest.mark.spec("AUTH-011")
def test_a_wrong_current_password_changes_nothing(server: Server, member: Account) -> None:
    with server.client(login(server, member)) as client:
        assert_problem(_change(client, "not the password", _new_password()), 403, "auth.invalid_credentials")
        # The session stays valid.
        assert client.get("/me").status_code == 200
    assert _sign_in(server, member.username, member.password).status_code == 201


@pytest.mark.spec("AUTH-011")
def test_wrong_current_passwords_are_rate_limited_like_sign_ins(server: Server, member: Account) -> None:
    with server.client(login(server, member)) as client:
        for _ in range(5):
            assert_problem(_change(client, "not the password", _new_password()), 403, "auth.invalid_credentials")
        # Over the limit, even the right password is refused (ADR-0047).
        refused = assert_problem(_change(client, member.password, _new_password()), 429, "auth.rate_limited")
    assert refused["status"] == 429
    assert_problem(_sign_in(server, member.username, member.password), 429, "auth.rate_limited")


@pytest.mark.spec("AUTH-011")
@pytest.mark.parametrize("new", ["too short", None], ids=["too-short", "same-as-current"])
def test_invalid_new_passwords_are_refused(server: Server, member: Account, new: str | None) -> None:
    with server.client(login(server, member)) as client:
        response = _change(client, member.password, member.password if new is None else new)
    assert_problem(response, 422, "request.validation_failed")
    assert _sign_in(server, member.username, member.password).status_code == 201


@pytest.mark.spec("AUTH-012")
def test_an_initial_password_must_be_replaced_first(server: Server, admin: Account) -> None:
    member = _created_by(server, admin)
    signed_in = _sign_in(server, member.username, member.password)
    assert signed_in.status_code == 201, signed_in.text
    assert body(signed_in)["user"]["password_change_required"] is True
    with server.client(body(signed_in)["token"]) as client:
        me = client.get("/me")
        assert me.status_code == 200
        assert body(me)["password_change_required"] is True
        for method, path in (("GET", "/conversations"), ("GET", "/me/sessions"), ("GET", "/me/settings")):
            assert_problem(client.request(method, path), 403, "auth.password_change_required")
        assert_problem(client.post("/conversations", json={}), 403, "auth.password_change_required")
        new = _new_password()
        assert _change(client, member.password, new).status_code == 204
        assert body(client.get("/me"))["password_change_required"] is False
        assert client.get("/conversations").status_code == 200
    assert _sign_in(server, member.username, new).status_code == 201


@pytest.mark.spec("AUTH-012")
def test_signing_out_works_before_the_change(server: Server, admin: Account) -> None:
    member = _created_by(server, admin)
    with server.client(login(server, member)) as client:
        assert client.post("/auth/logout").status_code == 204
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-012")
def test_the_first_admin_of_a_new_tenant_replaces_their_initial_password(database: Database, server: Server) -> None:
    instance_admin = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    first = Account(uuid7(), uuid7(), f"first-{uuid7()}", f"initial password {uuid7()}", "tenant_admin", False)
    with server.client(login(server, instance_admin)) as client:
        created = client.post(
            "/instance/tenants",
            json={
                "name": f"Family {uuid7()}",
                "admin": {
                    "username": first.username,
                    "display_name": "First admin",
                    "password": first.password,
                    "role": "tenant_admin",
                },
            },
        )
    assert created.status_code == 201, created.text
    first = replace(first, tenant_id=uuid.UUID(body(created)["id"]))
    with server.client(login(server, first)) as client:
        assert body(client.get("/me"))["password_change_required"] is True
        assert_problem(client.get("/tenant/users"), 403, "auth.password_change_required")


@pytest.mark.spec("AUTH-012")
def test_users_who_chose_their_password_are_not_asked_to_change_it(server: Server, member: Account) -> None:
    with server.client(login(server, member)) as client:
        assert body(client.get("/me"))["password_change_required"] is False
        assert client.get("/conversations").status_code == 200
