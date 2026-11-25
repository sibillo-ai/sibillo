"""A persistent workspace in an ephemeral sandbox, one per conversation (SBX-010, SBX-018, SBX-019, SBX-020,
SBX-021, AGT-022, ADR-0076, ADR-0077, ADR-0078).

The driver's tests use its API directly; the agent's, runs with the model the
tests serve (tests/support/model.py).
"""

from __future__ import annotations

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database, uuid7
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


def _tool_result(model: HarnessModel, text: str) -> str:
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


@pytest.mark.spec("SBX-019")
def test_a_small_workspace_says_nothing_about_its_quota(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    text = "run:echo small > /workspace/small.txt"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "quota" not in _tool_result(default_model, text).lower()


@pytest.mark.spec("AGT-022")
def test_the_agent_is_told_what_the_workspace_keeps(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    text = f"instructions {uuid7()}"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(text)[:1]
    messages = request.body.get("messages", [])
    system = " ".join(str(message.get("content", "")) for message in messages if message.get("role") == "system")
    for phrase in ("/scratch", "/workspace", "README.md"):
        assert phrase in system, f"the instructions do not mention {phrase}"


@pytest.mark.spec("SBX-021")
def test_the_agent_is_told_which_tools_the_sandbox_has(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    text = f"instructions {uuid7()}"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(text)[:1]
    messages = request.body.get("messages", [])
    system = " ".join(str(message.get("content", "")) for message in messages if message.get("role") == "system")
    for tool in ("pdftotext", "markitdown", "pandoc", "typst", "ffmpeg", "ImageMagick", "pandas", "openpyxl", "node"):
        assert tool in system, f"the instructions do not mention {tool}"
