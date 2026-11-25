"""Internet access: one permission of a conversation for the web, asked once for every call of a run, or turned on
and off by its user (AGT-034, ADR-0113, ADR-0115).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>`, several tools in turn with `chain:`, and several at
once, in one answer, with `calls:` (tests/support/model.py). Searches reach the
search service the tests serve, whose results are untrusted content.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    activity,
    approve,
    completed,
    conversation_of,
    deny,
    fresh_query,
    internet_request,
    interrupts,
    resume,
    resumed,
    search,
    with_untrusted_content,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run, start_run, text_of, wait_for_run
from tests.support.search import SearchServer
from tests.support.server import Server

PAGE = "ftp://example.org/file"
NO_ACCESS: dict[str, object] = {"internet_access": False, "turn_internet_access": False, "tools": []}
# What a client sends to turn internet access off.
WITHDRAW: dict[str, object] = {"internet_access": False, "tools": []}
WAIT = f"run_command {json.dumps({'command': 'sleep 4', 'description': 'Wait a little'})}"


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def asked_for_access(server: Server, token: str, conversation_id: str, text: str) -> tuple[str, dict[str, Any]]:
    """Run `text`, which ends asking for internet access: the run and its request."""
    run_id, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    return run_id, internet_request(events)


def tool_results(model: HarnessModel, text: str) -> list[str]:
    """What the model was told of its calls, in the requests that answer `text`."""
    return [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]


@pytest.mark.spec("AGT-034")
def test_the_web_asks_for_internet_access_without_untrusted_content(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    assert conversation_of(server, token, conversation_id)["allowances"] == NO_ACCESS
    query = fresh_query("first")
    before = datetime.datetime.now(datetime.UTC)
    run_id, interrupt = asked_for_access(server, token, conversation_id, search(query))
    # One request of the run, about internet access, not about the call.
    assert interrupt["id"] == f"apr-internet-{run_id}"
    assert "toolCallId" not in interrupt
    assert "approval" not in interrupt["metadata"]
    expires = datetime.datetime.fromisoformat(interrupt["expiresAt"])
    assert datetime.timedelta(hours=23, minutes=59) < expires - before < datetime.timedelta(hours=24, minutes=1)
    request = interrupt["metadata"]["internet_access"]
    assert request["untrusted_content"] is False
    assert request["scopes"] == ["turn", "conversation"]
    (call,) = request["calls"]
    assert call["tool"] == "web_search"
    assert call["arguments"] == {"query": query}
    assert query in call["data"]
    assert call["destination"].strip()
    # Nothing ran: the query has not left.
    assert search_service.queries().count(query) == 0
    assert conversation_of(server, token, conversation_id)["interrupts"] == [interrupt]
    # Allowed for the turn: the search runs, and the run goes on.
    events = resumed(server, token, conversation_id, [approve(interrupt["id"], "turn")])
    run = get_run(server, token, events[0].data["runId"])
    assert (run["kind"], run["parent_run_id"], run["status"]) == ("resume", run_id, "completed")
    assert search_service.queries().count(query) == 1
    assert text_of(events).startswith("Tool said:")
    # The turn is over: the conversation has no internet access, and the next turn asks again, now saying
    # that the run holds untrusted content.
    assert conversation_of(server, token, conversation_id)["allowances"] == NO_ACCESS
    _, again = asked_for_access(server, token, conversation_id, search(fresh_query("second")))
    assert again["metadata"]["internet_access"]["untrusted_content"] is True


@pytest.mark.spec("AGT-034", "AGT-012")
def test_the_calls_of_one_run_make_one_request(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    first, second = fresh_query("one"), fresh_query("two")
    text = (
        f"calls:web_search {json.dumps({'query': first})}"
        f" ||| web_search {json.dumps({'query': second})}"
        f" ||| read_page {json.dumps({'url': PAGE})}"
    )
    _, interrupt = asked_for_access(server, token, conversation_id, text)
    calls = interrupt["metadata"]["internet_access"]["calls"]
    assert [(call["tool"], call["arguments"]) for call in calls] == [
        ("web_search", {"query": first}),
        ("web_search", {"query": second}),
        ("read_page", {"url": PAGE}),
    ]
    assert calls[2]["data"] == PAGE
    assert "example.org" in calls[2]["destination"]
    # Never `once`, and one answer for all of them.
    for entries in ([approve(interrupt["id"], "once")], [approve(interrupt["id"]), approve(interrupt["id"])]):
        assert_problem(resume(server, token, conversation_id, entries), 422, "approval.invalid")
    events = resumed(server, token, conversation_id, [approve(interrupt["id"], "turn")])
    assert get_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert interrupts(events) == []
    assert (search_service.queries().count(first), search_service.queries().count(second)) == (1, 1)


@pytest.mark.spec("AGT-034", "AGT-006")
def test_internet_access_in_a_conversation_until_withdrawn(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    run_id, interrupt = asked_for_access(server, token, conversation_id, search(fresh_query()))
    resumed(server, token, conversation_id, [approve(interrupt["id"], "conversation")])
    assert conversation_of(server, token, conversation_id)["allowances"] == {
        "internet_access": True,
        "turn_internet_access": False,
        "tools": [],
    }
    # Later turns ask nothing: neither a search, nor a page, after untrusted content.
    later = fresh_query("later")
    completed(server, token, conversation_id, search(later))
    assert search_service.queries().count(later) == 1
    completed(server, token, conversation_id, f"tool:read_page {json.dumps({'url': PAGE})}")
    with server.client(token) as client:
        # A fork does not copy it, and no tool is allowed but by answering a request.
        response = client.post(f"/conversations/{conversation_id}/fork", json={"run_id": run_id})
        assert response.status_code == 201, response.text
        fork = body(response)
        assert fork["allowances"] == NO_ACCESS
        added = client.patch(
            f"/conversations/{fork['id']}", json={"allowances": {"internet_access": False, "tools": ["web_search"]}}
        )
        assert_problem(added, 422, "request.validation_failed")
        # Its user withdraws it, and the web asks again.
        withdrawn = client.patch(f"/conversations/{conversation_id}", json={"allowances": WITHDRAW})
        assert withdrawn.status_code == 200, withdrawn.text
        assert body(withdrawn)["allowances"] == NO_ACCESS
    asked_for_access(server, token, conversation_id, search(fresh_query("again")))


@pytest.mark.spec("AGT-034")
def test_commands_need_no_approval(server: Server, token: str, default_model: HarnessModel) -> None:
    # Even with untrusted content in the conversation, and no internet access.
    conversation_id = with_untrusted_content(server, token)
    events = completed(server, token, conversation_id, "run:echo offline")
    assert interrupts(events) == []
    assert "offline" in text_of(events)


@pytest.mark.spec("AGT-034")
def test_the_assistant_asks_for_internet_access_with_its_tool(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    text = "tool:request_internet_access {}"
    _, interrupt = asked_for_access(server, token, conversation_id, text)
    request = interrupt["metadata"]["internet_access"]
    assert (request["calls"], request["untrusted_content"]) == ([], False)
    events = resumed(server, token, conversation_id, [approve(interrupt["id"], "conversation")])
    assert "internet access" in text_of(events).lower()
    # With internet access, it is answered at once.
    events = completed(server, token, conversation_id, f"{text} ")
    assert interrupts(events) == []
    assert "internet access" in text_of(events).lower()


@pytest.mark.spec("AGT-034", "AGT-007")
def test_a_denial_holds_for_the_rest_of_the_turn(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    first, second, third = fresh_query("one"), fresh_query("two"), fresh_query("three")
    text = (
        f"chain:web_search {json.dumps({'query': first})}"
        f" >>> web_search {json.dumps({'query': second})}"
        " >>> request_internet_access {}"
    )
    _, interrupt = asked_for_access(server, token, conversation_id, text)
    events = resumed(server, token, conversation_id, [deny(interrupt["id"])])
    # The later calls were denied without asking: the run completed.
    assert get_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert interrupts(events) == []
    assert (search_service.queries().count(first), search_service.queries().count(second)) == (0, 0)
    # What the model last saw: the result of each of its three calls.
    *_, last = default_model.endpoint.requests_with(text)
    results = [str(m.get("content", "")) for m in last.body.get("messages", []) if m.get("role") == "tool"]
    assert len(results) == 3, results
    assert all("denied" in result.lower() for result in results), results
    # The next turn asks again.
    asked_for_access(server, token, conversation_id, search(third))


@pytest.mark.spec("AGT-034", "AGT-007", "AGT-008")
def test_an_unanswered_request_denies_every_waiting_call_when_it_expires(
    database: Database, server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    first, second = fresh_query("one"), fresh_query("two")
    text = f"calls:web_search {json.dumps({'query': first})} ||| web_search {json.dumps({'query': second})}"
    run_id, _ = asked_for_access(server, token, conversation_id, text)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE conversations SET approvals_expire_at = now() - interval '1 second' WHERE id = %s",
            (conversation_id,),
        )
    deadline = time.monotonic() + 20
    conversation = conversation_of(server, token, conversation_id)
    while conversation["active_run_id"] == run_id and time.monotonic() < deadline:
        time.sleep(0.2)
        conversation = conversation_of(server, token, conversation_id)
    run = wait_for_run(server, token, conversation["active_run_id"])
    assert (run["kind"], run["parent_run_id"], run["status"]) == ("resume", run_id, "completed")
    assert (search_service.queries().count(first), search_service.queries().count(second)) == (0, 0)
    events = [e for e in activity(server, token, conversation_id=conversation_id) if e["run_id"] == run_id]
    assert sorted((e["tool"], e["outcome"], e["reason"], e["scope"]) for e in events) == [
        ("web_search", "expired", "internet_access", None),
        ("web_search", "expired", "internet_access", None),
    ]


@pytest.mark.spec("AGT-034", "AGT-008")
def test_calls_that_need_internet_access_are_audited_with_its_reason(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    _, interrupt = asked_for_access(server, token, conversation_id, search(fresh_query("approved")))
    resumed(server, token, conversation_id, [approve(interrupt["id"], "conversation")])
    completed(server, token, conversation_id, search(fresh_query("allowed")))
    with server.client(token) as client:
        page = body(client.get(f"/conversations/{conversation_id}/messages"))
    decided = [(item["outcome"], item["scope"], item["reason"]) for run in page["runs"] for item in run["approvals"]]
    assert ("approved", "conversation", "internet_access") in decided
    events = activity(server, token, conversation_id=conversation_id)
    assert [(e["tool"], e["outcome"], e["scope"], e["reason"]) for e in events] == [
        ("web_search", "allowed", "conversation", None),
        ("web_search", "approved", "conversation", "internet_access"),
    ]


@pytest.mark.spec("AGT-034")
def test_the_instructions_say_that_the_sandbox_has_no_network(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    text = f"hello {fresh_query()}"
    completed(server, token, conversation_id, text)
    (request, *_) = default_model.endpoint.requests_with(text)
    instructions = " ".join(
        str(message.get("content", ""))
        for message in request.body.get("messages", [])
        if message.get("role") in ("system", "developer")
    )
    assert "request_internet_access" in instructions
    assert "no network" in instructions.lower()


# --- The switch of internet access (UX-042, ADR-0115) ---


def switch(server: Server, token: str, conversation_id: str, on: bool) -> Any:
    with server.client(token) as client:
        return client.patch(
            f"/conversations/{conversation_id}", json={"allowances": {"internet_access": on, "tools": []}}
        )


def turn_access(server: Server, token: str, conversation_id: str) -> bool:
    allowed: bool = conversation_of(server, token, conversation_id)["allowances"]["turn_internet_access"]
    return allowed


def in_background(work: Callable[[], object]) -> threading.Thread:
    """Start a run whose events stream until it ends, without waiting for it."""
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


def while_running(server: Server, token: str, conversation_id: str) -> None:
    """Wait until the conversation's active run is running its command."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        active = conversation_of(server, token, conversation_id)["active_run_id"]
        if active and get_run(server, token, active)["status"] == "running":
            time.sleep(1)
            return
        time.sleep(0.2)
    raise AssertionError("the run did not start")


@pytest.mark.spec("AGT-034")
def test_its_user_turns_internet_access_on_and_off(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    on = switch(server, token, conversation_id, True)
    assert on.status_code == 200, on.text
    assert body(on)["allowances"] == {"internet_access": True, "turn_internet_access": False, "tools": []}
    # The web runs without asking.
    query = fresh_query("switched")
    completed(server, token, conversation_id, search(query))
    assert search_service.queries().count(query) == 1
    # Turned off, it asks again.
    off = switch(server, token, conversation_id, False)
    assert off.status_code == 200, off.text
    assert body(off)["allowances"] == NO_ACCESS
    asked_for_access(server, token, conversation_id, search(fresh_query("off")))


@pytest.mark.spec("AGT-034")
def test_a_conversation_starts_with_internet_access_its_user_gave(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    with server.client(token) as client:
        response = client.post("/conversations", json={"internet_access": True})
    assert response.status_code == 201, response.text
    conversation = body(response)
    assert conversation["allowances"]["internet_access"] is True
    query = fresh_query("from the start")
    completed(server, token, conversation["id"], search(query))
    assert search_service.queries().count(query) == 1
    # Without it, as by default, it has none.
    assert create_conversation(server, token)["allowances"] == NO_ACCESS


@pytest.mark.spec("AGT-034", "AGT-002")
def test_a_user_denied_external_communication_cannot_turn_it_on(
    database: Database, server: Server, account: Account, token: str, default_model: HarnessModel
) -> None:
    admin = login(server, create_account(database, account.tenant_id, "tenant_admin"))
    with server.client(admin) as client:
        response = client.put(
            f"/tenant/users/{account.id}/tool-permissions",
            json={"tools": {}, "classes": {"external_communication": "deny"}},
        )
    assert response.status_code == 200, response.text
    conversation_id = create_conversation(server, token)["id"]
    assert_problem(switch(server, token, conversation_id, True), 422, "request.validation_failed")
    with server.client(token) as client:
        created = client.post("/conversations", json={"internet_access": True})
    assert_problem(created, 422, "request.validation_failed")


@pytest.mark.spec("AGT-034")
def test_the_turn_s_internet_access_lasts_until_the_turn_ends(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    text = f"chain:web_search {json.dumps({'query': fresh_query('turn')})} >>> {WAIT}"
    _, interrupt = asked_for_access(server, token, conversation_id, text)
    in_background(lambda: resume(server, token, conversation_id, [approve(interrupt["id"], "turn")]))
    while_running(server, token, conversation_id)
    assert turn_access(server, token, conversation_id) is True
    active = conversation_of(server, token, conversation_id)["active_run_id"]
    assert wait_for_run(server, token, active)["status"] == "completed"
    assert conversation_of(server, token, conversation_id)["allowances"] == NO_ACCESS


@pytest.mark.spec("AGT-034")
def test_turned_off_during_a_turn_the_turn_asks_again(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    later = fresh_query("after the switch")
    text = (
        f"chain:web_search {json.dumps({'query': fresh_query('before')})} >>> {WAIT}"
        f" >>> web_search {json.dumps({'query': later})}"
    )
    _, interrupt = asked_for_access(server, token, conversation_id, text)
    in_background(lambda: resume(server, token, conversation_id, [approve(interrupt["id"], "turn")]))
    while_running(server, token, conversation_id)
    assert switch(server, token, conversation_id, False).status_code == 200
    assert turn_access(server, token, conversation_id) is False
    active = conversation_of(server, token, conversation_id)["active_run_id"]
    assert wait_for_run(server, token, active)["status"] == "interrupted"
    assert "internet_access" in conversation_of(server, token, conversation_id)["interrupts"][0]["metadata"]
    assert search_service.queries().count(later) == 0


@pytest.mark.spec("AGT-034")
def test_turned_on_during_a_turn_the_turn_has_it(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    later = fresh_query("switched on")
    text = f"chain:{WAIT} >>> web_search {json.dumps({'query': later})}"
    in_background(lambda: start_run(server, token, conversation_id, text))
    while_running(server, token, conversation_id)
    assert switch(server, token, conversation_id, True).status_code == 200
    run_id = conversation_of(server, token, conversation_id)["active_run_id"]
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert search_service.queries().count(later) == 1
