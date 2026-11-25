"""The functions that find the work of tasks before any request context (TSK-003, TSK-007 to TSK-010).

ADR-0106 and the pre-authentication functions of specs/contracts/database.md.
Each returns only identifiers, and nothing of a paused task or of a disabled
account but what the contract lists. Calls are made as `sibillo_app` with no
request context, as the worker and the API make them. Rows are arranged as
superuser.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
import pytest

from tests.support.database import Database, uuid7
from tests.support.world import User, World, disable_user


def _task(conn: psycopg.Connection, user: User, *, paused: bool = False) -> uuid.UUID:
    task_id = uuid7()
    conn.execute(
        "INSERT INTO tasks (id, tenant_id, owner_id, name, instructions, time_zone, paused_at, created_at,"
        " updated_at) VALUES (%s, %s, %s, %s, 'Say hello.', 'UTC', CASE WHEN %s THEN now() END, now(), now())",
        (task_id, user.tenant_id, user.id, f"Task {task_id}", paused),
    )
    return task_id


def _schedule(conn: psycopg.Connection, user: User, task_id: uuid.UUID, *, due: bool) -> uuid.UUID:
    trigger_id = uuid7()
    conn.execute(
        "INSERT INTO task_triggers (id, tenant_id, owner_id, task_id, kind, schedule_start, recurrence, next_fire_at,"
        " created_at)"
        " VALUES (%s, %s, %s, %s, 'schedule', '2026-01-01 07:00', '{RRULE:FREQ=DAILY}',"
        " now() + CASE WHEN %s THEN interval '-1 minute'"
        " ELSE interval '1 day' END, now())",
        (trigger_id, user.tenant_id, user.id, task_id, due),
    )
    return trigger_id


def _webhook(conn: psycopg.Connection, user: User, task_id: uuid.UUID) -> tuple[uuid.UUID, bytes]:
    trigger_id, token_hash = uuid7(), hashlib.sha256(secrets.token_urlsafe(32).encode()).digest()
    conn.execute(
        "INSERT INTO task_triggers (id, tenant_id, owner_id, task_id, kind, token_hash, created_at)"
        " VALUES (%s, %s, %s, %s, 'webhook', %s, now())",
        (trigger_id, user.tenant_id, user.id, task_id, token_hash),
    )
    return trigger_id, token_hash


def _event_trigger(
    conn: psycopg.Connection, user: User, task_id: uuid.UUID, delivery: str, *, poll_due: bool = False
) -> uuid.UUID:
    trigger_id = uuid7()
    conn.execute(
        "INSERT INTO task_triggers (id, tenant_id, owner_id, task_id, kind, server_id, server_generation,"
        " event_name, event_arguments, delivery, next_poll_at, secret_ciphertext, refresh_before, created_at)"
        " VALUES (%s, %s, %s, %s, 'mcp_event', %s, %s, 'mail.received', '{}', %s,"
        " CASE WHEN %s = 'poll' THEN now() + CASE WHEN %s THEN interval '-1 second' ELSE interval '1 hour' END END,"
        " CASE WHEN %s = 'webhook' THEN 'ciphertext'::bytea END,"
        " CASE WHEN %s = 'webhook' THEN now() + interval '5 minutes' END, now())",
        (
            trigger_id,
            user.tenant_id,
            user.id,
            task_id,
            user.mcp_server_id,
            user.mcp_server_id,
            delivery,
            delivery,
            poll_due,
            delivery,
            delivery,
        ),
    )
    return trigger_id


def _due(conn: psycopg.Connection) -> set[tuple[uuid.UUID, str]]:
    rows = conn.execute("SELECT trigger_id, task_id, tenant_id, owner_id, work FROM due_task_triggers()").fetchall()
    return {(row[0], row[4]) for row in rows}


@contextmanager
def _unseen_by_the_worker(database: Database) -> Generator[psycopg.Connection]:
    """A transaction that arranges rows as superuser, then reads as `sibillo_app`, before anyone else sees them.

    The session's worker sweeps for due triggers and waiting firings every second, and would do their work
    while the test reads them; rows not yet committed are the test's alone.
    """
    with database.superuser() as conn, conn.transaction(force_rollback=True):
        yield conn


def _as_app(conn: psycopg.Connection) -> None:
    conn.execute("SET LOCAL ROLE sibillo_app")


@pytest.mark.spec("TSK-003", "TSK-008")
def test_due_triggers_are_found_with_their_work(database: Database, world: World) -> None:
    alice = world.alice
    with _unseen_by_the_worker(database) as conn:
        task_id = _task(conn, alice)
        due = _schedule(conn, alice, task_id, due=True)
        later = _schedule(conn, alice, task_id, due=False)
        polled = _event_trigger(conn, alice, task_id, "poll", poll_due=True)
        not_yet = _event_trigger(conn, alice, task_id, "poll", poll_due=False)
        renewed = _event_trigger(conn, alice, task_id, "webhook")
        _as_app(conn)
        found = _due(conn)
        assert {(due, "fire"), (polled, "poll"), (renewed, "renew")} <= found
        assert not {trigger for trigger, _ in found} & {later, not_yet}
        (row,) = conn.execute(
            "SELECT trigger_id, task_id, tenant_id, owner_id FROM due_task_triggers() WHERE trigger_id = %s", (due,)
        ).fetchall()
    assert row == (due, task_id, alice.tenant_id, alice.id)


@pytest.mark.spec("TSK-001", "TSK-010")
def test_triggers_of_paused_tasks_and_disabled_accounts_are_not_due(database: Database, world: World) -> None:
    disable_user(database, world.bob)
    with _unseen_by_the_worker(database) as conn:
        paused = _schedule(conn, world.alice, _task(conn, world.alice, paused=True), due=True)
        disabled = _schedule(conn, world.bob, _task(conn, world.bob), due=True)
        _as_app(conn)
        assert not {trigger for trigger, _ in _due(conn)} & {paused, disabled}


@pytest.mark.spec("TSK-009")
def test_the_oldest_waiting_firing_of_a_task_with_none_running_is_found(database: Database, world: World) -> None:
    alice = world.alice
    with _unseen_by_the_worker(database) as conn:
        idle, busy = _task(conn, alice), _task(conn, alice)
        firings: dict[str, uuid.UUID] = {}
        for name, task_id, status, age in (
            ("oldest", idle, "waiting", "3 minutes"),
            ("newer", idle, "waiting", "1 minute"),
            ("running", busy, "running", "2 minutes"),
            ("blocked", busy, "waiting", "1 minute"),
        ):
            firings[name] = uuid7()
            conn.execute(
                "INSERT INTO task_firings (id, tenant_id, owner_id, task_id, trigger_kind, fire_key, status,"
                " created_at) VALUES (%s, %s, %s, %s, 'webhook', %s, %s, now() - %s::interval)",
                (firings[name], alice.tenant_id, alice.id, task_id, f"key:{uuid7()}", status, age),
            )
        _as_app(conn)
        rows = conn.execute("SELECT firing_id, task_id, tenant_id, owner_id FROM waiting_task_firings()").fetchall()
    found = {row[0] for row in rows}
    assert firings["oldest"] in found
    assert not found & {firings["newer"], firings["running"], firings["blocked"]}
    assert (firings["oldest"], idle, alice.tenant_id, alice.id) in rows


@pytest.mark.spec("TSK-007")
def test_a_webhook_trigger_is_found_by_its_token_hash(database: Database, world: World) -> None:
    with database.superuser() as conn:
        task_id = _task(conn, world.alice, paused=True)
        trigger_id, token_hash = _webhook(conn, world.alice, task_id)
        bobs_trigger, bobs_hash = _webhook(conn, world.bob, _task(conn, world.bob))
    query = "SELECT trigger_id, task_id, tenant_id, owner_id, paused FROM find_webhook_trigger(%s)"
    with database.app() as conn:
        assert conn.execute(query, (token_hash,)).fetchall() == [
            (trigger_id, task_id, world.alice.tenant_id, world.alice.id, True)
        ]
        assert conn.execute(query, (hashlib.sha256(b"unknown").digest(),)).fetchall() == []
        assert [row[0] for row in conn.execute(query, (bobs_hash,)).fetchall()] == [bobs_trigger]
    disable_user(database, world.bob)
    with database.app() as conn:
        assert conn.execute(query, (bobs_hash,)).fetchall() == []


@pytest.mark.spec("TSK-008")
def test_an_event_subscription_is_found_by_its_trigger(database: Database, world: World) -> None:
    alice = world.alice
    with database.superuser() as conn:
        task_id = _task(conn, alice)
        delivered = _event_trigger(conn, alice, task_id, "webhook")
        polled = _event_trigger(conn, alice, task_id, "poll")
        schedule = _schedule(conn, alice, task_id, due=False)
    query = "SELECT task_id, tenant_id, owner_id, paused, secret_ciphertext FROM find_event_subscription(%s)"
    with database.app() as conn:
        assert conn.execute(query, (delivered,)).fetchall() == [
            (task_id, alice.tenant_id, alice.id, False, b"ciphertext")
        ]
        for other in (polled, schedule, uuid7()):
            assert conn.execute(query, (other,)).fetchall() == []
    disable_user(database, alice)
    with database.app() as conn:
        assert conn.execute(query, (delivered,)).fetchall() == []
