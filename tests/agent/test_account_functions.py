"""The administration functions of the database contract, called as `sibillo_app` (AUTH-013, AUTH-014, MOD-021,
ADR-0144, ADR-0145).

Each function checks the request context itself: these tests call it with the
contexts it must refuse, and with the one it serves as a control.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql

from tests.support.database import CONTRACT_TABLES, Context, Database, app_transaction, uuid7
from tests.support.world import User, World, disable_user

INSUFFICIENT_PRIVILEGE = "42501"
NO_DATA_FOUND = "P0002"
OBJECT_IN_USE = "55006"
# Another Argon2id hash than the one every user of the world has, so that setting it is a change.
OTHER_ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$b3RoZXI$aGFzaA"


def _anna(world: World, *, instance_admin: bool = False) -> Context:
    return Context(world.tenant_a, world.anna.id, "tenant_admin", instance_admin)


def _alice(world: World) -> Context:
    return Context(world.tenant_a, world.alice.id)


def _sqlstate(conn: psycopg.Connection, query: str, params: tuple[Any, ...]) -> str | None:
    """The SQLSTATE a statement fails with, in a savepoint; `None` when it succeeds."""
    try:
        with conn.transaction():
            conn.execute(cast("Any", query), params)
    except psycopg.Error as error:
        return error.sqlstate
    return None


def _rows_of(database: Database, user_id: uuid.UUID) -> dict[str, int]:
    """How many rows of each contract table belong to the user, by its owner, user or own identifier."""
    counts: dict[str, int] = {}
    with database.superuser() as conn:
        for table in CONTRACT_TABLES:
            columns = {
                name
                for (name,) in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public'"
                    " AND table_name = %s",
                    (table,),
                ).fetchall()
            }
            column = "id" if table == "users" else next((c for c in ("owner_id", "user_id") if c in columns), None)
            if column is None:
                continue
            row = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(column)),
                (user_id,),
            ).fetchone()
            assert row is not None
            if row[0]:
                counts[table] = row[0]
    return counts


def _arrange_budget(database: Database, user: User) -> None:
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO budgets (tenant_id, user_id, kind, amount, currency, period, time_zone, updated_at)"
            " VALUES (%s, %s, 'cost', 5, 'USD', 'week', 'Europe/Rome', now())",
            (user.tenant_id, user.id),
        )


@pytest.mark.spec("AUTH-013", "TEN-007")
@pytest.mark.parametrize("instance_admin", [False, True], ids=["tenant-admin", "instance-admin"])
def test_an_admin_gives_another_user_only_a_new_initial_password(
    database: Database, world: World, instance_admin: bool
) -> None:
    with app_transaction(database, _anna(world, instance_admin=instance_admin)) as conn:
        # A new hash without the mark is a password the admin would know: refused.
        assert _sqlstate(conn, "UPDATE users SET password_hash = %s WHERE id = %s", (OTHER_ARGON2_HASH, world.alice.id))
        # The mark without a new hash: refused too.
        assert _sqlstate(conn, "UPDATE users SET password_change_required = true WHERE id = %s", (world.alice.id,))
        # Control: both together.
        assert (
            _sqlstate(
                conn,
                "UPDATE users SET password_hash = %s, password_change_required = true WHERE id = %s",
                (OTHER_ARGON2_HASH, world.alice.id),
            )
            is None
        )


@pytest.mark.spec("AUTH-013")
def test_a_member_gives_nobody_a_new_initial_password(database: Database, world: World) -> None:
    with app_transaction(database, _alice(world)) as conn:
        # Their own: the user never marks their password as initial.
        assert _sqlstate(
            conn,
            "UPDATE users SET password_hash = %s, password_change_required = true WHERE id = %s",
            (OTHER_ARGON2_HASH, world.alice.id),
        )
        result = conn.execute(
            "UPDATE users SET password_hash = %s, password_change_required = true WHERE id = %s",
            (OTHER_ARGON2_HASH, world.anna.id),
        )
        # Row-level security leaves the member no other row to change.
        assert result.rowcount == 0


@pytest.mark.spec("AUTH-013", "AUTH-008")
def test_only_an_instance_admin_resets_an_instance_admins_password(database: Database, world: World) -> None:
    with database.superuser() as conn:
        conn.execute("UPDATE users SET instance_admin = true WHERE id = %s", (world.alice.id,))
    reset = "UPDATE users SET password_hash = %s, password_change_required = true WHERE id = %s"
    with app_transaction(database, _anna(world)) as conn:
        assert _sqlstate(conn, reset, (OTHER_ARGON2_HASH, world.alice.id)) == INSUFFICIENT_PRIVILEGE
    with app_transaction(database, _anna(world, instance_admin=True)) as conn:
        assert _sqlstate(conn, reset, (OTHER_ARGON2_HASH, world.alice.id)) is None


@pytest.mark.spec("AUTH-013", "AUTH-009")
def test_a_new_initial_password_revokes_sessions_and_forgets_subscriptions(database: Database, world: World) -> None:
    session_id = world.alice.rows["device_sessions"][0]
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO notification_subscriptions (tenant_id, owner_id, device_session_id, endpoint, p256dh, auth,"
            " created_at) VALUES (%s, %s, %s, %s, 'p256dh', 'auth', now()) ON CONFLICT DO NOTHING",
            (world.tenant_a, world.alice.id, session_id, f"https://push.example/{session_id}"),
        )
    with database.app() as conn:
        conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
            " set_config('app.role', 'tenant_admin', true), set_config('app.instance_admin', 'false', true)",
            (str(world.tenant_a), str(world.anna.id)),
        )
        conn.execute(
            "UPDATE users SET password_hash = %s, password_change_required = true WHERE id = %s",
            (OTHER_ARGON2_HASH, world.alice.id),
        )
        conn.commit()
    with database.superuser() as conn:
        sessions = conn.execute(
            "SELECT count(*) FROM device_sessions WHERE user_id = %s AND revoked_at IS NULL", (world.alice.id,)
        ).fetchone()
        subscriptions = conn.execute(
            "SELECT count(*) FROM notification_subscriptions WHERE owner_id = %s", (world.alice.id,)
        ).fetchone()
        passkeys = conn.execute("SELECT count(*) FROM passkeys WHERE user_id = %s", (world.alice.id,)).fetchone()
        others = conn.execute(
            "SELECT count(*) FROM device_sessions WHERE user_id = %s AND revoked_at IS NULL", (world.anna.id,)
        ).fetchone()
    assert sessions == (0,)
    assert subscriptions == (0,)
    # Passkeys stay: a user who has one still needs it (ADR-0144).
    assert passkeys == (1,)
    assert others == (1,)


@pytest.mark.spec("AUTH-014", "TEN-009", "TEN-008")
def test_account_storage_names_what_lives_outside_the_tables(database: Database, world: World) -> None:
    disable_user(database, world.alice)
    with app_transaction(database, _anna(world)) as conn:
        rows = conn.execute("SELECT kind, id FROM account_storage(%s)", (world.alice.id,)).fetchall()
    assert sorted(rows) == sorted(
        [
            ("conversation", world.alice.conversation_id),
            ("run", world.alice.run_id),
            ("firing", world.alice.rows["task_firings"][0]),
        ]
    )


@pytest.mark.spec("AUTH-014", "TEN-006", "TEN-007")
@pytest.mark.parametrize("function", ["account_storage", "delete_account"])
def test_account_functions_refuse_what_the_contract_does_not_allow(
    database: Database, world: World, function: str
) -> None:
    call = f"SELECT * FROM {function}(%s)"  # noqa: S608 - one of two names
    with app_transaction(database, _anna(world)) as conn:
        # An account that is not disabled.
        assert _sqlstate(conn, call, (world.alice.id,)) == INSUFFICIENT_PRIVILEGE
    disable_user(database, world.alice)
    with app_transaction(database, _alice(world)) as conn:
        # A member, of anyone.
        assert _sqlstate(conn, call, (world.alice.id,)) == INSUFFICIENT_PRIVILEGE
    with app_transaction(database, Context(world.tenant_b, world.bob.id, "tenant_admin")) as conn:
        # A tenant admin of another tenant does not reach the account at all.
        assert _sqlstate(conn, call, (world.alice.id,)) == NO_DATA_FOUND
    with database.superuser() as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (world.anna.id,))
    with app_transaction(database, _anna(world)) as conn:
        # Their own account, disabled or not.
        assert _sqlstate(conn, call, (world.anna.id,)) == INSUFFICIENT_PRIVILEGE
    with database.superuser() as conn:
        conn.execute("UPDATE users SET instance_admin = true WHERE id = %s", (world.alice.id,))
    with app_transaction(database, _anna(world, instance_admin=True)) as conn:
        # An instance admin's, whoever asks.
        assert _sqlstate(conn, call, (world.alice.id,)) == INSUFFICIENT_PRIVILEGE
    assert _rows_of(database, world.alice.id)


@pytest.mark.spec("AUTH-014")
@pytest.mark.parametrize("function", ["account_storage", "delete_account"])
@pytest.mark.parametrize("status", ["queued", "running"])
def test_an_account_with_a_run_in_progress_is_not_deleted(
    database: Database, world: World, function: str, status: str
) -> None:
    disable_user(database, world.alice)
    with database.superuser() as conn:
        conn.execute("UPDATE runs SET status = %s WHERE id = %s", (status, world.alice.run_id))
    with app_transaction(database, _anna(world)) as conn:
        assert _sqlstate(conn, f"SELECT * FROM {function}(%s)", (world.alice.id,)) == OBJECT_IN_USE  # noqa: S608
    assert _rows_of(database, world.alice.id)


@pytest.mark.spec("AUTH-014", "TEN-006")
def test_deleting_an_account_deletes_every_row_of_its_user_and_nothing_else(database: Database, world: World) -> None:
    _arrange_budget(database, world.alice)
    before = _rows_of(database, world.alice.id)
    # Every private table, and the tenant's tables that name the user.
    assert {"users", "budgets", "tool_permissions", "egress_policies", "passkeys", "usage_ledger"} <= set(before)
    others = {user.id: _rows_of(database, user.id) for user in (world.anna, world.bob)}
    disable_user(database, world.alice)
    with database.app() as conn:
        conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
            " set_config('app.role', 'tenant_admin', true), set_config('app.instance_admin', 'false', true)",
            (str(world.tenant_a), str(world.anna.id)),
        )
        conn.execute("SELECT delete_account(%s)", (world.alice.id,))
        conn.commit()
    assert _rows_of(database, world.alice.id) == {}
    assert {user_id: _rows_of(database, user_id) for user_id in others} == others


@pytest.mark.spec("MOD-021", "TEN-006", "TEN-007")
def test_usage_of_a_user_is_for_them_and_their_tenant_admins(database: Database, world: World) -> None:
    call = "SELECT * FROM usage_of_user(%s, 'Europe/Rome')"
    with app_transaction(database, _alice(world)) as conn:
        own = conn.execute(call, (world.alice.id,)).fetchall()
        # Another member's usage: refused.
        assert _sqlstate(conn, call, (world.anna.id,)) == INSUFFICIENT_PRIVILEGE
    with app_transaction(database, _anna(world)) as conn:
        admin = conn.execute(call, (world.alice.id,)).fetchall()
    with app_transaction(database, Context(world.tenant_b, world.bob.id, "tenant_admin")) as conn:
        assert _sqlstate(conn, call, (world.alice.id,)) == NO_DATA_FOUND
    assert own
    assert admin == own


@pytest.mark.spec("MOD-021", "TEN-007")
def test_usage_of_a_user_holds_only_sums_per_day(database: Database, world: World) -> None:
    with database.superuser() as conn:
        for hours, cost in ((1, "0.25"), (2, "0.5")):
            conn.execute(
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, run_id, purpose, provider, model,"
                " input_tokens, output_tokens, cost, currency, price_source, created_at)"
                " VALUES (%s, %s, %s, %s, %s, 'run', 'openrouter.ai', 'test/summed', 10, 5, %s, 'USD', 'provider',"
                " date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' + make_interval(hours => %s))",
                (uuid7(), world.tenant_a, world.alice.id, world.alice.conversation_id, world.alice.run_id, cost, hours),
            )
    with app_transaction(database, _anna(world)) as conn:
        cursor = conn.execute("SELECT * FROM usage_of_user(%s, 'UTC') WHERE model = 'test/summed'", (world.alice.id,))
        names = [column.name for column in cursor.description or []]
        rows = cursor.fetchall()
    assert names == [
        "day",
        "provider",
        "model",
        "price_source",
        "currency",
        "cost",
        "input_tokens",
        "output_tokens",
        "requests",
    ]
    assert len(rows) == 1
    _, provider, _, source, currency, cost, input_tokens, output_tokens, requests = rows[0]
    assert (provider, source, currency, cost, input_tokens, output_tokens, requests) == (
        "openrouter.ai",
        "provider",
        "USD",
        Decimal("0.75"),
        20,
        10,
        2,
    )
