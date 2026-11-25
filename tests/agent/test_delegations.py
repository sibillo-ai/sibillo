"""Delegating work to delegated runs (AGT-035 to AGT-038, AGT-003, ADR-0136).

The model the tests serve answers by the last user message
(tests/support/model.py): `tool:delegate {"brief": ...}` hands the brief to
a delegated run, whose only message is the brief, so the delegated run
follows the script the brief holds, and the delegating run then answers
`Tool said: <report>`.
"""

from __future__ import annotations

import datetime
import json
import time
import uuid
from typing import Any

import pytest

from tests.support.accounts import body
from tests.support.approvals import (
    activity,
    completed,
    fresh_query,
    holds_untrusted_content,
    interrupts,
    search,
    with_untrusted_content,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.search import SearchServer, result
from tests.support.server import RUN_REQUEST_LIMIT, Server

DELEGATION_SECONDS = 20


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


def _delegate(brief: str) -> str:
    return f"tool:delegate {json.dumps({'brief': brief})}"


def _delegates(*briefs: str) -> str:
    """Every brief delegated at once, in one answer."""
    return "calls:" + " ||| ".join(f"delegate {json.dumps({'brief': brief})}" for brief in briefs)


def _said(server: Server, token: str, conversation_id: str, text: str) -> str:
    return text_of(completed(server, token, conversation_id, text))


def _delegations(database: Database, run_id: str) -> list[dict[str, Any]]:
    """The delegations of a run, as stored, in the order they were made."""
    with database.superuser() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, tool_call_id, brief, status, error_code, untrusted, report, created_at, started_at,"
            " finished_at FROM delegations WHERE run_id = %s ORDER BY created_at, id",
            (uuid.UUID(run_id),),
        )
        columns = [column.name for column in cursor.description or ()]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _wait_for_delegation(database: Database, run_id: str, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + DELEGATION_SECONDS
    while time.monotonic() < deadline:
        found = [item for item in _delegations(database, run_id) if item["status"] == status]
        if found:
            return found[0]
        time.sleep(0.2)
    raise AssertionError(f"no delegation of the run became {status}")


def _most_at_once(delegations: list[dict[str, Any]]) -> int:
    """The most delegated runs that ran at the same moment."""
    edges = sorted(
        [(item["started_at"], 1) for item in delegations] + [(item["finished_at"], -1) for item in delegations],
        key=lambda edge: (edge[0], edge[1]),
    )
    running = most = 0
    for _, step in edges:
        running += step
        most = max(most, running)
    return most


# --- AGT-035: delegating work ---


@pytest.mark.spec("AGT-035")
def test_the_assistant_gets_the_report_of_the_work_it_delegated(
    server: Server, member: Member, database: Database
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, events = start_run(server, member.token, conversation_id, _delegate("Count the plums"))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed", interrupts(events)
    assert "Tool said: Echo: Count the plums" in text_of(events)
    (delegation,) = _delegations(database, run_id)
    assert (delegation["brief"], delegation["status"]) == ("Count the plums", "completed")
    assert delegation["report"] == "Echo: Count the plums"


@pytest.mark.spec("AGT-035")
def test_a_delegated_run_sees_only_its_brief(server: Server, member: Member, default_model: HarnessModel) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    with server.client(member.token) as client:
        response = client.patch(
            f"/conversations/{conversation_id}", json={"additional_instructions": "Mention the platypus."}
        )
    assert response.status_code == 200, response.text
    completed(server, member.token, conversation_id, "Remember the walrus plan")
    completed(server, member.token, conversation_id, _delegate("Weigh the apples"))
    (request,) = default_model.endpoint.requests_with("Weigh the apples")
    assert request.user_texts() == ["Weigh the apples"]
    sent = json.dumps(request.body)
    assert "walrus" not in sent
    assert "platypus" not in sent
    # The delegating run's own requests carry them.
    delegating = default_model.endpoint.requests_with(_delegate("Weigh the apples"))[0]
    assert "walrus" in json.dumps(delegating.body)
    assert "platypus" in json.dumps(delegating.body)
    # On the delegating run's model.
    assert request.body.get("model") == delegating.body.get("model")


@pytest.mark.spec("AGT-035")
def test_delegations_of_one_answer_run_together_four_at_once_and_ten_at_most(
    server: Server, member: Member, database: Database, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    text = _delegates(*["slow:2"] * 11)
    run_id, events = start_run(server, member.token, conversation_id, text)
    assert wait_for_run(server, member.token, run_id)["status"] == "completed", interrupts(events)
    delegations = _delegations(database, run_id)
    assert len(delegations) == 10
    assert all(item["status"] == "completed" for item in delegations)
    assert 2 <= _most_at_once(delegations) <= 4
    # Ten reports reached the model, and an eleventh result that is not one.
    results = [
        str(message.get("content", ""))
        for message in default_model.endpoint.requests_with(text)[-1].body.get("messages", [])
        if message.get("role") == "tool"
    ]
    assert len(results) == 11
    reports = [item["report"] for item in delegations]
    assert sum(1 for found in results if found in reports) == 10


@pytest.mark.spec("AGT-035")
def test_a_delegated_run_cannot_delegate(server: Server, member: Member, database: Database) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, events = start_run(server, member.token, conversation_id, _delegate(_delegate("Deeper")))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed", interrupts(events)
    assert "No tool delegate" in text_of(events)
    assert len(_delegations(database, run_id)) == 1


@pytest.mark.spec("AGT-035", "CNV-013")
def test_delegation_can_be_switched_off(server: Server, member: Member, database: Database) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    with server.client(member.token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": ["delegate"]})
    assert response.status_code == 200, response.text
    run_id, events = start_run(server, member.token, conversation_id, _delegate("Anything"))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed", interrupts(events)
    assert "No tool delegate" in text_of(events)
    assert _delegations(database, run_id) == []


# --- AGT-036: what a delegated run may do ---


@pytest.mark.spec("AGT-036")
def test_a_delegated_run_works_in_the_conversation_s_sandbox(server: Server, member: Member) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    completed(server, member.token, conversation_id, "run:echo shared > /workspace/note.txt")
    said = _said(server, member.token, conversation_id, _delegate("run:cat /workspace/note.txt"))
    assert "shared" in said


@pytest.mark.spec("AGT-036")
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("ask_user_question", {"questions": [{"question": "Which?", "options": [{"label": "A"}, {"label": "B"}]}]}),
        ("remember", {"text": "The user likes plums."}),
        ("write_plan", {"tasks": [{"content": "One"}]}),
        ("offer_download", {"path": "/workspace/note.txt"}),
        ("request_internet_access", {}),
        ("save_skill", {"path": "/workspace/skill"}),
        ("propose_task", {"name": "Daily"}),
    ],
)
def test_a_delegated_run_is_not_offered_what_speaks_to_the_user_or_outlasts_the_work(
    server: Server, member: Member, tool: str, arguments: dict[str, Any]
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _delegate(f"tool:{tool} {json.dumps(arguments)}"))
    assert f"No tool {tool}" in said


@pytest.mark.spec("AGT-036", "CNV-013")
def test_a_delegated_run_follows_the_conversation_s_switches(server: Server, member: Member) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    with server.client(member.token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": ["list_tasks"]})
    assert response.status_code == 200, response.text
    said = _said(server, member.token, conversation_id, _delegate("tool:list_tasks {}"))
    assert "No tool list_tasks" in said


@pytest.mark.spec("AGT-036", "AGT-034")
def test_a_delegated_run_never_asks_and_is_denied_what_needs_approval(
    server: Server, member: Member, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    query = fresh_query("unasked")
    run_id, events = start_run(server, member.token, conversation_id, _delegate(search(query)))
    # The delegating run does not end waiting for an approval: nobody was asked.
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    assert interrupts(events) == []
    assert search_service.requests_for(query) == []
    audited = activity(server, member.token, tool="web_search")
    assert [(item["outcome"], item["reason"]) for item in audited] == [("not_granted", "internet_access")]


@pytest.mark.spec("AGT-036", "AGT-034")
def test_a_delegated_run_has_the_conversation_s_internet_access(
    server: Server, member: Member, search_service: SearchServer
) -> None:
    with server.client(member.token) as client:
        response = client.post("/conversations", json={"internet_access": True})
    assert response.status_code == 201, response.text
    conversation_id = body(response)["id"]
    query = fresh_query("delegated")
    said = _said(server, member.token, conversation_id, _delegate(search(query)))
    assert len(search_service.requests_for(query)) == 1
    assert result(query, 0)["title"] in said


# --- AGT-037: provenance through delegation ---


@pytest.mark.spec("AGT-037", "AGT-003")
def test_the_report_of_a_delegated_run_that_read_untrusted_content_is_untrusted(
    server: Server, member: Member, database: Database
) -> None:
    clean = create_conversation(server, member.token)["id"]
    run_id = start_run(server, member.token, clean, _delegate("Say hello"))[0]
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    assert _delegations(database, run_id)[0]["untrusted"] is False
    assert not holds_untrusted_content(server, member.token, clean)

    # Command output is untrusted content (AGT-003).
    tainted = create_conversation(server, member.token)["id"]
    run_id = start_run(server, member.token, tainted, _delegate("run:echo from the sandbox"))[0]
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    assert _delegations(database, run_id)[0]["untrusted"] is True
    assert holds_untrusted_content(server, member.token, tainted)


@pytest.mark.spec("AGT-037", "AGT-003")
def test_a_delegated_run_of_a_run_with_untrusted_content_starts_untrusted(
    server: Server, member: Member, database: Database
) -> None:
    conversation_id = with_untrusted_content(server, member.token)
    run_id = start_run(server, member.token, conversation_id, _delegate("Say hello"))[0]
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    (delegation,) = _delegations(database, run_id)
    assert delegation["untrusted"] is True


# --- AGT-038: delegated runs end, fail and survive with their run ---


@pytest.mark.spec("AGT-038", "CNV-003")
def test_stopping_the_delegating_run_stops_its_delegated_runs(
    server: Server, member: Member, database: Database, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, _ = start_run(server, member.token, conversation_id, _delegate("slow:40"), stop_after=1)
    _wait_for_delegation(database, run_id, "running")
    deadline = time.monotonic() + DELEGATION_SECONDS
    while not default_model.endpoint.requests_with("slow:40") and time.monotonic() < deadline:
        time.sleep(0.2)
    with server.client(member.token) as client:
        response = client.post(f"/runs/{run_id}/cancel")
    assert response.status_code == 200, response.text
    assert wait_for_run(server, member.token, run_id)["status"] == "cancelled"
    stopped = _wait_for_delegation(database, run_id, "cancelled")
    # Well before the twenty seconds its answer would have taken.
    assert stopped["finished_at"] - stopped["started_at"] < datetime.timedelta(seconds=15)


@pytest.mark.spec("AGT-038")
def test_a_failed_delegated_run_reports_it_and_the_delegating_run_goes_on(
    server: Server, member: Member, database: Database
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, events = start_run(server, member.token, conversation_id, _delegate("fail"))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    (delegation,) = _delegations(database, run_id)
    assert delegation["status"] == "failed"
    assert delegation["error_code"] in {"model.request_failed", "model.unavailable"}
    assert delegation["error_code"] in text_of(events)


@pytest.mark.spec("AGT-038", "AGT-027")
def test_a_delegated_run_stops_at_the_limit_of_model_requests_of_a_run(
    server: Server, member: Member, database: Database
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    brief = "chain:" + " >>> ".join(["list_tasks {}"] * (RUN_REQUEST_LIMIT + 5))
    run_id, events = start_run(server, member.token, conversation_id, _delegate(brief))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    (delegation,) = _delegations(database, run_id)
    assert (delegation["status"], delegation["error_code"]) == ("failed", "run.step_limit")
    assert "run.step_limit" in text_of(events)


@pytest.mark.spec("AGT-038", "MOD-006", "AGT-008")
def test_a_delegated_run_s_requests_are_in_the_ledger_and_its_calls_are_audited(
    server: Server, member: Member, database: Database
) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id = start_run(server, member.token, conversation_id, _delegate("run:echo counted"))[0]
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    (delegation,) = _delegations(database, run_id)
    with database.superuser() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM usage_ledger WHERE run_id = %s AND purpose = 'delegation'", (uuid.UUID(run_id),)
        )
        (requests,) = cursor.fetchone() or (0,)
    # The command, then the report.
    assert requests == 2
    audited = activity(server, member.token, conversation_id=conversation_id)
    assert any(item["tool"] == "run_command" and item["run_id"] == str(delegation["id"]) for item in audited)
    assert any(item["tool"] == "delegate" and item["run_id"] == run_id for item in audited)


@pytest.mark.spec("AGT-038", "CNV-004")
def test_a_delegation_is_deleted_with_its_run(server: Server, member: Member, database: Database) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    run_id = start_run(server, member.token, conversation_id, _delegate("Say hello"))[0]
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    assert len(_delegations(database, run_id)) == 1
    with server.client(member.token) as client:
        response = client.post(f"/conversations/{conversation_id}/rewind", json={"run_id": None})
    assert response.status_code == 200, response.text
    assert _delegations(database, run_id) == []
