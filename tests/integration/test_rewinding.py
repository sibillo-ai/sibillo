"""Rewinding, editing a message and continuity across devices (CNV-004, CNV-016, CNV-015, ADR-0068).

A conversation has one chain of runs. Rewinding names the run that becomes
the last and deletes the runs after it; editing a message is rewinding to
the turn before it, then sending the edited text.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.support.accounts import Account, assert_problem, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _rewind(server: Server, token: str, conversation_id: str, run_id: str | None) -> httpx.Response:
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/rewind", json={"run_id": run_id})


@pytest.mark.spec("CNV-004", "CNV-003")
def test_a_rewind_waits_for_a_cancelled_run_to_stop(server: Server, token: str) -> None:
    conversation_id = create_conversation(server, token)["id"]
    first, _ = start_run(server, token, conversation_id, "kept")
    assert wait_for_run(server, token, first)["status"] == "completed"
    slow, _ = start_run(server, token, conversation_id, "slow:6", stop_after=1)
    with server.client(token) as client:
        assert client.post(f"/runs/{slow}/cancel").status_code == 200
    # Cancelled, but its workflow is still ending: what it does now must not outlive the rewind (ADR-0132).
    assert_problem(_rewind(server, token, conversation_id, first), 409, "run.in_progress")
    deadline = time.monotonic() + 30
    while _rewind(server, token, conversation_id, first).status_code == 409:
        assert time.monotonic() < deadline, "the cancelled run never stopped"
        time.sleep(0.5)
