"""The browser tools, through runs (AGT-039, ADR-0138).

The model the tests serve calls tools in turn when the user's message is
`chain:<name> <arguments> >>> …`, and one tool with `tool:<name> <arguments>`,
answering `No tool <name>` when the request does not offer it
(tests/support/model.py). Pages are served from inside the conversation's
sandbox, on its own loopback address.
"""

from __future__ import annotations

import json
import secrets

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.approvals import approving, internet_request
from tests.support.browser import (
    BROWSER_TOOLS,
    CATALOG_ENTRY,
    LOAD,
    call,
    chain,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run, start_run, text_of, wait_for_run
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _tool_results(model: HarnessModel, text: str) -> list[str]:
    """What the model was told of its calls, in order, in the last request that answers `text`."""
    return [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]


def _completed(server: Server, token: str, conversation_id: str, text: str) -> str:
    """Run `text` with internet access for the turn (AGT-034); the run's answer, once completed."""
    _, events, last = approving(server, token, conversation_id, text)
    assert get_run(server, token, last)["status"] == "completed"
    return text_of(events)


@pytest.mark.spec("AGT-039")
def test_the_browser_is_not_offered_until_the_model_loads_it(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    text = f"tool:browser_goto {json.dumps({'url': 'https://example.org/'})}"
    _, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert text_of(events) == "No tool browser_goto"
    (request,) = default_model.endpoint.requests_with(text)
    # Only the catalog's line, and the tool that loads it.
    assert not request.tool_names() & BROWSER_TOOLS
    assert "load_capability" in request.tool_names()
    assert CATALOG_ENTRY in request.system_text()


@pytest.mark.spec("AGT-039")
def test_a_loaded_browser_stays_offered_for_the_rest_of_the_conversation(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    _, events = start_run(server, token, conversation_id, f"tool:{LOAD}")
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    text = f"later {secrets.token_hex(4)}"
    _, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(text)
    assert request.tool_names() >= BROWSER_TOOLS
    # Loading it again changes nothing.
    again = chain(LOAD)
    _, events = start_run(server, token, conversation_id, again)
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert default_model.endpoint.requests_with(again)[-1].tool_names() >= BROWSER_TOOLS


@pytest.mark.spec("AGT-039")
def test_the_browser_tools_wait_for_internet_access(server: Server, token: str) -> None:
    conversation_id = create_conversation(server, token)["id"]
    address = "https://library.example/hours"
    run_id, events = start_run(server, token, conversation_id, chain(LOAD, call("browser_goto", url=address)))
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    request = internet_request(events)["metadata"]["internet_access"]
    assert [(entry["tool"], entry["arguments"]) for entry in request["calls"]] == [("browser_goto", {"url": address})]


@pytest.mark.spec("AGT-039")
@pytest.mark.parametrize(
    "failing",
    [
        call("browser_goto", url="file:///etc/passwd"),
        call("browser_goto", url="http://127.0.0.1:8766/missing"),
        call("browser_click", selector="#no-such-element"),
    ],
    ids=["file", "unreachable", "missing-element"],
)
def test_a_failed_action_is_told_to_the_model(
    server: Server, token: str, default_model: HarnessModel, failing: str
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    text = chain(LOAD, failing)
    assert _completed(server, token, conversation_id, text).startswith("Tool said:")
    content = _tool_results(default_model, text)[-1]
    assert content.strip()
    assert "root:" not in content


@pytest.mark.spec("AGT-039")
def test_with_every_browser_tool_off_the_browser_is_not_offered(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": sorted(BROWSER_TOOLS)})
    assert response.status_code == 200, response.text
    # A text of its own: the requests of other tests that load the browser hold `chain(LOAD)` too.
    text = chain(LOAD, call("load_capability", id=f"browser-{secrets.token_hex(4)}"))
    _, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    requests = default_model.endpoint.requests_with(text)
    assert all(CATALOG_ENTRY not in request.system_text() for request in requests)
    assert all(not request.tool_names() & BROWSER_TOOLS for request in requests)


@pytest.mark.spec("AGT-039")
def test_with_some_browser_tools_off_only_the_others_are_offered(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    off = sorted(BROWSER_TOOLS - {"browser_goto", "browser_markdown"})
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": off})
    assert response.status_code == 200, response.text
    text = chain(LOAD)
    _, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert default_model.endpoint.requests_with(text)[-1].tool_names() & BROWSER_TOOLS == {
        "browser_goto",
        "browser_markdown",
    }
