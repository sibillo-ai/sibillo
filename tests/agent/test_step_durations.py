"""How long each tool call took, measured by the worker and given by the history (UX-043, API-003, ADR-0140).

The model the tests serve calls the command tool when the user's message is
`run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import secrets

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, messages, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


@pytest.mark.spec("UX-043")
def test_each_tool_result_says_how_long_its_call_took(server: Server, token: str) -> None:
    conversation_id = create_conversation(server, token)["id"]
    run_id, _ = start_run(server, token, conversation_id, f"run:sleep 1; echo slept-{secrets.token_hex(3)}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    items = messages(server, token, conversation_id)["items"]
    (result,) = [item for item in items if item["role"] == "tool"]
    duration = result["duration_ms"]
    assert isinstance(duration, int)
    # The command slept a second; the call took at least that, and not much more.
    assert 1_000 <= duration < 20_000
    # Only tool results carry it.
    assert all("duration_ms" not in item for item in items if item["role"] != "tool")
