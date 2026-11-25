"""Runs through the API: AG-UI events over SSE, durable execution, history and the cost ledger.

API-004, AGT-009, AGT-010, CNV-002, CNV-003, MOD-001, MOD-002, MOD-005,
MOD-006 and TEN-009, as in ADR-0032, ADR-0034, ADR-0037 and ADR-0052. The
model is the one the tests serve (specs/contracts/test-harness.md).
"""

from __future__ import annotations

import time

import pytest

from tests.support.accounts import Account, assert_problem, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.runs import (
    create_conversation,
    get_run,
    messages,
    replay,
    start_run,
    wait_for_run,
)
from tests.support.server import Server

LIFECYCLE = {"RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"}


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def household(account: Account, default_model: HarnessModel) -> HouseholdModel:
    return default_model.connect(account.tenant_id)


@pytest.fixture
def token(server: Server, account: Account, household: HouseholdModel) -> str:
    return login(server, account)


@pytest.mark.spec("TEN-009")
def test_workflows_of_old_runs_are_deleted(database: Database, server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    with database.superuser() as conn:
        conn.execute("UPDATE runs SET finished_at = now() - interval '31 days' WHERE id = %s", (run_id,))
    # Retention runs when the worker starts (ADR-0052).
    server.crash_and_restart_worker()
    deadline = time.monotonic() + 60
    with database.superuser() as conn:
        while conn.execute("SELECT 1 FROM dbos.workflow_status WHERE workflow_uuid = %s", (run_id,)).fetchall():
            assert time.monotonic() < deadline, "the workflow of an old run was not deleted"
            time.sleep(0.5)
    # The run and its history stay; its events do not.
    assert get_run(server, token, run_id)["status"] == "completed"
    assert len(messages(server, token, conversation["id"])["items"]) == 2
    with server.client(token) as client:
        assert_problem(client.get(f"/runs/{run_id}/events"), 404, "resource.not_found")


@pytest.mark.spec("AGT-010")
def test_a_run_survives_a_crash_of_the_worker(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "slow:8", stop_after=3)
    server.crash_and_restart_worker()
    run = wait_for_run(server, token, run_id, timeout=120)
    events = replay(server, token, run_id)
    # Resumed, retried or failed, but never silently lost.
    assert run["status"] in {"completed", "failed"}
    assert events[-1].type == ("RUN_FINISHED" if run["status"] == "completed" else "RUN_ERROR")
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
