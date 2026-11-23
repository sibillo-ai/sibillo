"""Approvals: how they are answered, denied and audited, and requests that expire (AGT-007, AGT-008, AGT-012,
ADR-0033, ADR-0090).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py). Searches reach the search
service the tests serve, and ask for internet access (AGT-034), whose request
the tests answer here; tests/integration/test_internet_access.py tests what it
covers.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    activity,
    approve,
    asked,
    completed,
    deny,
    fresh_query,
    resume,
    resumed,
    search,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run
from tests.support.search import SearchServer
from tests.support.server import Server

ALL_SCOPES = ["once", "turn", "conversation"]


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


@pytest.mark.spec("AGT-007")
@pytest.mark.parametrize("how", ["denied", "cancelled"])
def test_a_denied_call_does_not_run_and_the_model_is_told(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer, how: str
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    query = fresh_query("denied")
    text = search(query)
    _, interrupt = asked(server, token, conversation_id, text)
    entry = deny(interrupt["id"]) if how == "denied" else {"interruptId": interrupt["id"], "status": "cancelled"}
    events = resumed(server, token, conversation_id, [entry])
    assert get_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert search_service.queries().count(query) == 0
    results = [
        str(message.get("content", ""))
        for request in default_model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    assert any("denied" in result.lower() for result in results), results


@pytest.mark.spec("AGT-012")
def test_answers_must_fit_the_stored_request(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation_id = create_conversation(server, token)["id"]
    _, interrupt = asked(server, token, conversation_id, search(fresh_query()))
    wrong: list[list[dict[str, Any]]] = [
        [approve("apr-unknown", "turn")],
        [approve(interrupt["id"], "forever")],
        [approve(interrupt["id"], "once")],
        [{"interruptId": interrupt["id"], "status": "resolved", "payload": {"approved": True}}],
        [{"interruptId": interrupt["id"], "status": "resolved", "payload": {}}],
        [approve(interrupt["id"], "turn"), approve("apr-unknown", "turn")],
        [],
    ]
    for entries in wrong:
        assert_problem(resume(server, token, conversation_id, entries), 422, "approval.invalid")
    resumed(server, token, conversation_id, [approve(interrupt["id"], "turn")])
    # Once resolved, the same answer is refused.
    assert_problem(resume(server, token, conversation_id, [approve(interrupt["id"], "turn")]), 422, "approval.invalid")


@pytest.mark.spec("AGT-012", "AGT-007")
def test_an_expired_request_cannot_be_approved(
    database: Database, server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    query = fresh_query("expired")
    _, interrupt = asked(server, token, conversation_id, search(query))
    with database.superuser() as conn:
        conn.execute(
            "UPDATE conversations SET approvals_expire_at = now() - interval '1 second' WHERE id = %s",
            (conversation_id,),
        )
    # Whether the sweep has denied it yet or not, it is no longer pending.
    assert_problem(resume(server, token, conversation_id, [approve(interrupt["id"], "turn")]), 422, "approval.invalid")
    assert search_service.queries().count(query) == 0


@pytest.mark.spec("AGT-008")
def test_every_tool_call_leaves_an_audit_event_without_its_content(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token, title="Audited")["id"]
    first, second, third = fresh_query("free"), fresh_query("approved"), fresh_query("denied")
    completed(server, token, conversation_id, f"run:echo {first}")
    _, approved = asked(server, token, conversation_id, search(second))
    resumed(server, token, conversation_id, [approve(approved["id"], "turn")])
    _, denied = asked(server, token, conversation_id, search(third))
    resumed(server, token, conversation_id, [deny(denied["id"])])
    with server.client(token) as client:
        response = client.get("/me/activity", params={"conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    # Content-free: neither the queries nor the results.
    for query in (first, second, third):
        assert query not in response.text
    events = body(response)["items"]
    # Newest first.
    assert [(e["tool"], e["outcome"], e["scope"], e["reason"]) for e in events] == [
        ("web_search", "denied", None, "internet_access"),
        ("web_search", "approved", "turn", "internet_access"),
        ("run_command", "not_needed", None, None),
    ]
    assert all(e["conversation_id"] == conversation_id for e in events)
    assert all(e["conversation_title"] == "Audited" for e in events)
    assert not any(e["repeated"] for e in events)
    # The history says, on each call, how it was decided (UX-023).
    with server.client(token) as client:
        page = body(client.get(f"/conversations/{conversation_id}/messages"))
    decided = {
        item["tool_call_id"]: (item["outcome"], item["scope"], item["reason"])
        for run in page["runs"]
        for item in run["approvals"]
    }
    assert decided[events[1]["tool_call_id"]] == ("approved", "turn", "internet_access")
    assert decided[events[0]["tool_call_id"]] == ("denied", None, "internet_access")
    # Filtered by tool, and kept once the conversation is deleted.
    assert activity(server, token, tool="read_page", conversation_id=conversation_id) == []
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    kept = activity(server, token, conversation_id=conversation_id)
    assert [e["id"] for e in kept] == [e["id"] for e in events]
    assert all(e["conversation_title"] is None for e in kept)


@pytest.mark.spec("AGT-008", "TEN-006")
def test_audit_events_are_visible_only_to_the_user_they_acted_for(
    database: Database, server: Server, token: str, account: Account, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    completed(server, token, conversation_id, f"run:echo {fresh_query()}")
    assert activity(server, token, conversation_id=conversation_id)
    # Not to another member of the household, nor to its admin.
    for role in ("member", "tenant_admin"):
        other = login(server, create_account(database, account.tenant_id, role))
        assert activity(server, other, conversation_id=conversation_id) == []
