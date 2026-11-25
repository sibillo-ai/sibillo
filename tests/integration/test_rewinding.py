"""Rewinding, editing a message and continuity across devices (CNV-004, CNV-016, CNV-015, ADR-0068).

A conversation has one chain of runs. Rewinding names the run that becomes
the last and deletes the runs after it; editing a message is rewinding to
the turn before it, then sending the edited text.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
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
    # Whether its workflow is still ending when this asks depends on the worker's pace, which the agent tier's
    # test of a run that has not ended checks; what holds either way is that the rewind goes through once it did.
    deadline = time.monotonic() + 30
    while (response := _rewind(server, token, conversation_id, first)).status_code == 409:
        assert time.monotonic() < deadline, "the cancelled run never stopped"
        time.sleep(0.5)
    assert response.status_code == 200, response.text
