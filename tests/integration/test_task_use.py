"""Tasks in use: firing one now, the assistant changing and listing them (TSK-011 to TSK-013, ADR-0107).

The model the tests serve calls a tool by name when the message is
`tool:<name> <arguments>`, then answers `Tool said: <result>`
(tests/support/model.py).
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from tests.support.accounts import assert_problem, body
from tests.support.approvals import approve, asked, deny, fresh_query, resumed, search, with_untrusted_content
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.search import SearchServer
from tests.support.server import Server
from tests.support.tasks import (
    arrange_done_firings,
    chain,
    conversations_of,
    create_task,
    fire_schedule,
    firings,
    get_task,
    open_grant,
    outcomes,
    trigger_of,
    update_task,
    wait_for_conversations,
)


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return f"tool:{name} {json.dumps(arguments)}"


def _fire(server: Server, token: str, task_id: str) -> Any:
    with server.client(token) as client:
        return client.post(f"/tasks/{task_id}/fire")


# --- TSK-011: running a task now ---


@pytest.mark.spec("TSK-011")
def test_a_task_fires_at_once_also_while_paused(server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    response = _fire(server, member.token, task["id"])
    assert response.status_code == 202, response.text
    (first,) = wait_for_conversations(server, member.token, task["id"])
    assert first["trigger_kind"] == "manual"
    assert first["outcome"] == "completed"

    update_task(server, member.token, task["id"], paused=True)
    assert _fire(server, member.token, task["id"]).status_code == 202
    second, _ = wait_for_conversations(server, member.token, task["id"], 2)
    assert second["trigger_kind"] == "manual"
    assert get_task(server, member.token, task["id"])["paused"] is True


@pytest.mark.spec("TSK-011", "TSK-009")
def test_firing_now_counts_toward_the_hourly_limit(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    arrange_done_firings(database, task["id"], 10)
    assert_problem(_fire(server, member.token, task["id"]), 409, "task.limit_reached")
    assert get_task(server, member.token, task["id"])["skipped"]["count"] == 1
    assert len(firings(database, task["id"])) == 10


@pytest.mark.spec("TSK-011", "TSK-004")
def test_a_task_fired_now_follows_its_grants(server: Server, member: Member, search_service: SearchServer) -> None:
    first, second = fresh_query("first"), fresh_query("second")
    task = create_task(
        server,
        member.token,
        chain(("web_search", {"query": first}), ("web_search", {"query": second})),
        grants=[open_grant("web_search")],
    )
    assert _fire(server, member.token, task["id"]).status_code == 202
    (item,) = wait_for_conversations(server, member.token, task["id"])
    assert search_service.requests_for(second)
    assert outcomes(server, member.token, item["conversation_id"]) == ["granted"]


@pytest.mark.spec("TSK-011", "TEN-007")
def test_only_its_user_fires_a_task(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    assert_problem(_fire(server, member.model.admin_token, task["id"]), 404, "resource.not_found")
    time.sleep(2)
    assert firings(database, task["id"]) == []


# --- TSK-012: the assistant changes a task ---


@pytest.mark.spec("TSK-012", "AGT-006")
def test_the_assistant_changes_a_task_only_once_its_user_approves(server: Server, member: Member) -> None:
    task = create_task(server, member.token, "Summarize the news.", name="News")
    conversation_id = create_conversation(server, member.token)["id"]
    change = {"task_id": task["id"], "instructions": "Summarize the sports news.", "paused": True}
    _, interrupt = asked(server, member.token, conversation_id, _tool("update_task", change))
    request = interrupt["metadata"]["approval"]
    assert request["tool"] == "update_task"
    assert request["reason"] == "task_proposal"
    assert request["scopes"] == ["once"]
    assert request["untrusted_content"] is False
    assert request["arguments"] == change
    # Nothing changed yet.
    assert get_task(server, member.token, task["id"])["instructions"] == "Summarize the news."

    resumed(server, member.token, conversation_id, [approve(interrupt["id"])])
    changed = get_task(server, member.token, task["id"])
    assert changed["instructions"] == "Summarize the sports news."
    assert changed["paused"] is True

    _, again = asked(
        server, member.token, conversation_id, _tool("update_task", {"task_id": task["id"], "paused": False})
    )
    resumed(server, member.token, conversation_id, [deny(again["id"])])
    assert get_task(server, member.token, task["id"])["paused"] is True


@pytest.mark.spec("TSK-012", "TSK-005")
def test_an_approved_change_that_completes_the_trifecta_is_not_applied(server: Server, member: Member) -> None:
    task = create_task(server, member.token, grants=[open_grant("web_search")])
    conversation_id = create_conversation(server, member.token)["id"]
    change = {"task_id": task["id"], "grants": [open_grant("web_search"), open_grant("read_file")]}
    _, interrupt = asked(server, member.token, conversation_id, _tool("update_task", change))
    resumed(server, member.token, conversation_id, [approve(interrupt["id"])])
    assert get_task(server, member.token, task["id"])["grants"] == [open_grant("web_search")]


@pytest.mark.spec("TSK-012", "AGT-003")
def test_a_change_from_a_run_with_untrusted_content_says_so(server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    conversation_id = with_untrusted_content(server, member.token)
    _, interrupt = asked(
        server, member.token, conversation_id, _tool("update_task", {"task_id": task["id"], "paused": True})
    )
    assert interrupt["metadata"]["approval"]["untrusted_content"] is True


@pytest.mark.spec("TSK-012", "TEN-007")
def test_the_assistant_cannot_change_another_user_s_task(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    other = new_member(database, server, default_model)
    theirs = create_task(server, other.token, name="Theirs")
    conversation_id = create_conversation(server, member.token)["id"]
    _, interrupt = asked(
        server, member.token, conversation_id, _tool("update_task", {"task_id": theirs["id"], "paused": True})
    )
    resumed(server, member.token, conversation_id, [approve(interrupt["id"])])
    assert get_task(server, other.token, theirs["id"])["paused"] is False


@pytest.mark.spec("TSK-012")
def test_a_task_s_run_cannot_change_a_task(database: Database, server: Server, member: Member) -> None:
    target = create_task(server, member.token, name="Target")
    task = create_task(server, member.token, _tool("update_task", {"task_id": target["id"], "paused": True}))
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    (item,) = wait_for_conversations(server, member.token, task["id"])
    assert outcomes(server, member.token, item["conversation_id"]) == ["not_granted"]
    assert get_task(server, member.token, target["id"])["paused"] is False


# --- TSK-013: the assistant reads the user's tasks ---


@pytest.mark.spec("TSK-013")
def test_the_assistant_lists_the_user_s_tasks_and_their_latest_firings(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    task = create_task(server, member.token, "Say good morning.", name="Morning")
    assert _fire(server, member.token, task["id"]).status_code == 202
    (fired,) = wait_for_conversations(server, member.token, task["id"])
    other = new_member(database, server, default_model)
    create_task(server, other.token, name="Someone else's task")

    conversation_id = create_conversation(server, member.token)["id"]
    run_id, events = start_run(server, member.token, conversation_id, _tool("list_tasks", {}))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    said = text_of(events)
    assert "Morning" in said
    assert "Say good morning." in said
    assert fired["conversation_id"] in said
    assert "completed" in said
    assert "Someone else's task" not in said


@pytest.mark.spec("TSK-013", "AGT-003")
def test_listing_tasks_brings_no_untrusted_content(
    server: Server, member: Member, search_service: SearchServer
) -> None:
    create_task(server, member.token, name="Plain")
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, _ = start_run(server, member.token, conversation_id, _tool("list_tasks", {}))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    # A search after it needs no approval: the run holds no untrusted content.
    query = fresh_query()
    run_id, _ = start_run(server, member.token, conversation_id, search(query))
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    assert search_service.requests_for(query)


@pytest.mark.spec("TSK-011", "TSK-013")
def test_list_of_conversations_after_firing_now(server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    assert _fire(server, member.token, task["id"]).status_code == 202
    wait_for_conversations(server, member.token, task["id"])
    with server.client(member.token) as client:
        listed = body(client.get("/tasks"))["items"]
    assert listed[0]["last_fired_at"] is not None
    assert conversations_of(server, member.token, task["id"])[0]["trigger_kind"] == "manual"
