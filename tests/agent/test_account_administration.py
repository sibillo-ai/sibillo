"""A tenant admin gives a member a new initial password, and deletes a disabled account (AUTH-013, AUTH-014,
ADR-0144)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from psycopg import sql

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, disable_account, login
from tests.support.database import Database, uuid7
from tests.support.fake_sandboxes import FakeDriver
from tests.support.fixtures import HarnessModel
from tests.support.passkeys import arrange_passkey
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def admin(database: Database, harness_model: HarnessModel) -> Account:
    account = create_account(database, create_tenant(database), "tenant_admin")
    harness_model.connect(account.tenant_id)
    return account


@pytest.fixture
def member(database: Database, admin: Account) -> Account:
    return create_account(database, admin.tenant_id)


def _password() -> str:
    return f"a new password {uuid7()}"


def _sign_in(server: Server, username: str, password: str) -> int:
    with server.client() as client:
        return client.post(
            "/auth/login", json={"username": username, "password": password, "device_name": "check"}
        ).status_code


def _reset(server: Server, token: str, user_id: uuid.UUID, password: str) -> Any:
    with server.client(token) as client:
        return client.post(f"/tenant/users/{user_id}/password", json={"password": password})


@pytest.mark.spec("AUTH-013", "AUTH-012")
def test_a_member_signs_in_with_the_new_initial_password_and_must_replace_it(
    server: Server, admin: Account, member: Account
) -> None:
    password = _password()
    response = _reset(server, login(server, admin), member.id, password)
    assert response.status_code == 200, response.text
    assert body(response)["password_change_required"] is True
    assert _sign_in(server, member.username, member.password) == 401
    with server.client() as client:
        signed_in = client.post(
            "/auth/login", json={"username": member.username, "password": password, "device_name": "after"}
        )
    assert signed_in.status_code == 201, signed_in.text
    with server.client(body(signed_in)["token"]) as client:
        assert_problem(client.get("/conversations"), 403, "auth.password_change_required")
        own = f"my own password {uuid7()}"
        changed = client.post("/me/password", json={"current_password": password, "new_password": own})
        assert changed.status_code == 204, changed.text
        assert client.get("/conversations").status_code == 200


@pytest.mark.spec("AUTH-013")
def test_a_reset_ends_every_session_of_the_member_and_keeps_their_passkeys(
    database: Database, server: Server, admin: Account, member: Account
) -> None:
    # Signed in before the passkey, which a sign-in would then ask for.
    session = login(server, member)
    arrange_passkey(database, member, "Phone")
    admin_token = login(server, admin)
    assert _reset(server, admin_token, member.id, _password()).status_code == 200
    with server.client(session) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")
    with server.client(admin_token) as client:
        # The admin's own session stays.
        assert body(client.get(f"/tenant/users/{member.id}/passkeys"))["count"] == 1


@pytest.mark.spec("AUTH-013", "AUTH-008", "TEN-006")
def test_a_reset_is_refused_where_the_api_does_not_allow_it(
    database: Database, server: Server, admin: Account, member: Account
) -> None:
    admin_token = login(server, admin)
    # Their own: changed with the current password, never reset.
    assert_problem(_reset(server, admin_token, admin.id, _password()), 403, "permission.denied")
    # A member resets nobody's.
    other = create_account(database, admin.tenant_id)
    assert_problem(_reset(server, login(server, member), other.id, _password()), 403, "permission.denied")
    # An instance admin's, by a tenant admin who is not one.
    operator = create_account(database, admin.tenant_id, "tenant_admin", instance_admin=True)
    assert_problem(_reset(server, admin_token, operator.id, _password()), 403, "permission.denied")
    # Another household's member is not found.
    elsewhere = create_account(database, create_tenant(database))
    assert_problem(_reset(server, admin_token, elsewhere.id, _password()), 404, "resource.not_found")
    # A password shorter than an account's.
    assert_problem(_reset(server, admin_token, member.id, "short"), 422, "request.validation_failed")
    for account in (admin, other, operator, elsewhere, member):
        assert _sign_in(server, account.username, account.password) == 201


@pytest.mark.spec("AUTH-013", "AUTH-008")
def test_an_instance_admin_resets_another_instance_admins_password(
    database: Database, server: Server, admin: Account
) -> None:
    first = create_account(database, admin.tenant_id, "tenant_admin", instance_admin=True)
    second = create_account(database, admin.tenant_id, "tenant_admin", instance_admin=True)
    password = _password()
    assert _reset(server, login(server, first), second.id, password).status_code == 200
    assert _sign_in(server, second.username, password) == 201


def _delete(server: Server, token: str, user_id: uuid.UUID) -> Any:
    with server.client(token) as client:
        return client.delete(f"/tenant/users/{user_id}")


@pytest.mark.spec("AUTH-014", "TEN-008", "TEN-009")
def test_deleting_a_disabled_account_deletes_everything_of_its_user(
    database: Database, server: Server, sandboxes: FakeDriver, admin: Account, member: Account
) -> None:
    token = login(server, member)
    conversation = create_conversation(server, token, "Notes")
    run_id, _ = start_run(server, token, conversation["id"], "run:echo kept")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    with server.client(token) as client:
        assert client.post("/me/memory/items", json={"text": "Likes tea"}).status_code == 201
    assert any(box.user_id == member.id for box in sandboxes.sandboxes.boxes)
    admin_token = login(server, admin)
    with server.client(admin_token) as client:
        assert client.patch(f"/tenant/users/{member.id}", json={"disabled": True}).status_code == 200
        assert client.put(
            f"/tenant/users/{member.id}/budget",
            json={"cost": None, "tokens": {"tokens": 1000, "period": "day", "time_zone": "UTC"}},
        ).is_success
    response = _delete(server, admin_token, member.id)
    assert response.status_code == 204, response.text
    with database.superuser() as conn:
        workflows = conn.execute("SELECT 1 FROM dbos.workflow_status WHERE workflow_uuid = %s", (run_id,)).fetchall()
        left = {
            table: conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(column)),
                (member.id,),
            ).fetchone()
            for table, column in (
                ("users", "id"),
                ("conversations", "owner_id"),
                ("runs", "owner_id"),
                ("memory_items", "owner_id"),
                ("usage_ledger", "owner_id"),
                ("device_sessions", "user_id"),
                ("budgets", "user_id"),
            )
        }
    assert workflows == []
    assert set(left.values()) == {(0,)}, left
    assert not any(box.user_id == member.id for box in sandboxes.sandboxes.boxes)
    with server.client(admin_token) as client:
        listed = [user["id"] for user in body(client.get("/tenant/users"))["items"]]
        assert str(member.id) not in listed
        # The username is free again.
        again = client.post(
            "/tenant/users",
            json={"username": member.username, "display_name": "Again", "password": _password(), "role": "member"},
        )
    assert again.status_code == 201, again.text


@pytest.mark.spec("AUTH-014")
def test_an_enabled_account_is_not_deleted(server: Server, admin: Account, member: Account) -> None:
    assert_problem(_delete(server, login(server, admin), member.id), 409, "resource.conflict")
    assert _sign_in(server, member.username, member.password) == 201


@pytest.mark.spec("AUTH-014")
def test_an_account_with_a_run_in_progress_is_not_deleted(
    database: Database, server: Server, admin: Account, member: Account
) -> None:
    conversation = create_conversation(server, login(server, member), "Busy")
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, kind, status, last_event_seq, created_at)"
            " VALUES (%s, %s, %s, %s, 'message', 'running', 0, now())",
            (uuid7(), member.tenant_id, member.id, conversation["id"]),
        )
    disable_account(database, member)
    assert_problem(_delete(server, login(server, admin), member.id), 409, "run.in_progress")
    with database.superuser() as conn:
        assert conn.execute("SELECT count(*) FROM users WHERE id = %s", (member.id,)).fetchone() == (1,)


@pytest.mark.spec("AUTH-014", "AUTH-008", "TEN-006")
def test_a_deletion_is_refused_where_the_api_does_not_allow_it(
    database: Database, server: Server, admin: Account, member: Account
) -> None:
    disable_account(database, member)
    # A member deletes nobody.
    other = create_account(database, admin.tenant_id)
    assert_problem(_delete(server, login(server, other), member.id), 403, "permission.denied")
    admin_token = login(server, admin)
    # Their own account.
    assert_problem(_delete(server, admin_token, admin.id), 403, "permission.denied")
    # An instance admin's, by anyone.
    operator = create_account(database, admin.tenant_id, "tenant_admin", instance_admin=True)
    operator_token = login(server, operator)
    disabled_operator = create_account(database, admin.tenant_id, "tenant_admin", instance_admin=True)
    with database.superuser() as conn:
        # Arranged data, without the triggers that guard changes.
        conn.execute("SET session_replication_role = replica")
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (disabled_operator.id,))
    assert_problem(_delete(server, admin_token, disabled_operator.id), 403, "permission.denied")
    assert_problem(_delete(server, operator_token, disabled_operator.id), 403, "permission.denied")
    # Another household's account is not found.
    elsewhere = create_account(database, create_tenant(database))
    disable_account(database, elsewhere)
    assert_problem(_delete(server, admin_token, elsewhere.id), 404, "resource.not_found")
    assert_problem(_delete(server, admin_token, uuid7()), 404, "resource.not_found")
    with database.superuser() as conn:
        kept = conn.execute(
            "SELECT count(*) FROM users WHERE id = ANY(%s)", ([member.id, disabled_operator.id, elsewhere.id],)
        ).fetchone()
    assert kept == (3,)
