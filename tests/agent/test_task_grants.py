"""Task grants: what a task may do unattended, and never the lethal trifecta (TSK-004 to TSK-006).

ADR-0106, ADR-0113. A task's instructions script the model the tests serve,
as a user's message does (tests/support/model.py): `chain:` calls tools one
after another, each once the result of the one before has arrived. A search
needs internet access (AGT-034); in a task's run it runs only when the task
has the grant of internet access, and is otherwise denied at once, without
asking.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from tests.support.accounts import assert_problem, body
from tests.support.approvals import approve, asked, deny, fresh_query, resumed, search, with_untrusted_content
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.mcp import McpServer, McpService
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.search import SearchServer
from tests.support.server import Server
from tests.support.tasks import (
    chain,
    create_task,
    fire_schedule,
    fixed_grant,
    get_task,
    open_grant,
    outcomes,
    schedule,
    task_request,
    trigger_of,
    try_create,
    wait_for_conversations,
    webhook,
)


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


def _searches(*queries: str) -> str:
    return chain(*[("web_search", {"query": query}) for query in queries])


def _fired(database: Database, server: Server, member: Member, task: dict[str, Any]) -> dict[str, Any]:
    """Fire the task's schedule and wait for its conversation: the task's entry for it."""
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    (item,) = wait_for_conversations(server, member.token, task["id"])
    return item


def _set_permissions(
    server: Server, member: Member, tools: dict[str, str], classes: dict[str, str] | None = None
) -> None:
    with server.client(member.model.admin_token) as client:
        response = client.put(
            f"/tenant/users/{member.account.id}/tool-permissions", json={"tools": tools, "classes": classes or {}}
        )
    assert response.status_code == 200, response.text


def _add_server(server: Server, member: Member, mcp_service: McpService) -> tuple[McpServer, str]:
    """A remote MCP server of the member's household, its tool `turn_on` accepted: the server and its prefix."""
    mcp = mcp_service.new()
    prefix = f"t{secrets.token_hex(4)}"
    with server.client(member.model.admin_token) as client:
        added = client.post(
            "/tenant/mcp-servers", json={"name": f"Lights {mcp.id}", "prefix": prefix, "url": mcp.url, "auth": "none"}
        )
        assert added.status_code == 201, added.text
        listed = {tool["name"]: tool for tool in body(added)["tools"]}
        accepted = client.put(
            f"/tenant/mcp-servers/{body(added)['id']}/accepted-tools",
            json={"tools": [{"name": "turn_on", "digest": listed["turn_on"]["digest"]}]},
        )
    assert accepted.status_code == 200, accepted.text
    return mcp, prefix


# --- TSK-004: task grants ---


@pytest.mark.spec("TSK-004", "AGT-004", "AGT-034")
def test_the_grant_of_internet_access_lets_a_task_use_the_web(
    database: Database, server: Server, member: Member, search_service: SearchServer
) -> None:
    first, second = fresh_query("first"), fresh_query("second")
    task = create_task(server, member.token, _searches(first, second), internet_access=True)
    assert task["internet_access"] is True
    item = _fired(database, server, member, task)
    assert item["outcome"] == "completed"
    assert search_service.requests_for(first)
    assert search_service.requests_for(second)
    # Both searches ran with the turn's internet access, after untrusted content too.
    assert outcomes(server, member.token, item["conversation_id"]) == ["allowed", "allowed"]


@pytest.mark.spec("TSK-004")
def test_a_call_no_grant_covers_is_denied_at_once_without_asking(
    database: Database, server: Server, member: Member, search_service: SearchServer
) -> None:
    first, second = fresh_query("first"), fresh_query("second")
    task = create_task(server, member.token, _searches(first, second))
    assert task["internet_access"] is False
    item = _fired(database, server, member, task)
    # The run did not stop to ask: it went on, and ended.
    assert item["outcome"] == "completed"
    assert not search_service.requests_for(first)
    assert not search_service.requests_for(second)
    assert outcomes(server, member.token, item["conversation_id"]) == ["not_granted", "not_granted"]
    with server.client(member.token) as client:
        conversation = body(client.get(f"/conversations/{item['conversation_id']}"))
        events = body(client.get("/me/activity", params={"conversation_id": item["conversation_id"]}))["items"]
    assert conversation["interrupts"] == []
    assert [(event["tool"], event["outcome"], event["reason"]) for event in events] == [
        ("web_search", "not_granted", "internet_access"),
        ("web_search", "not_granted", "internet_access"),
    ]


@pytest.mark.spec("TSK-004", "AGT-018")
def test_a_fixed_grant_covers_only_the_call_with_its_exact_arguments(
    database: Database, server: Server, member: Member, mcp_service: McpService
) -> None:
    mcp, prefix = _add_server(server, member, mcp_service)
    turn_on = f"{prefix}__turn_on"
    task = create_task(
        server,
        member.token,
        chain((turn_on, {"entity": "light.porch"}), (turn_on, {"entity": "light.garage"})),
        grants=[fixed_grant(turn_on, {"entity": "light.porch"})],
    )
    item = _fired(database, server, member, task)
    assert item["outcome"] == "completed"
    # Only the granted call reached the server.
    assert [call.params["arguments"] for call in mcp.calls() if call.params] == [{"entity": "light.porch"}]
    assert outcomes(server, member.token, item["conversation_id"]) == ["granted", "not_granted"]


@pytest.mark.spec("TSK-004")
def test_open_grants_never_cover_a_server_s_tool(server: Server, member: Member, mcp_service: McpService) -> None:
    _, prefix = _add_server(server, member, mcp_service)
    response = try_create(server, member.token, task_request(grants=[open_grant(f"{prefix}__turn_on")]))
    assert_problem(response, 422, "task.grant_not_allowed")


@pytest.mark.spec("TSK-004", "TSK-006")
def test_propose_task_cannot_be_granted(server: Server, member: Member) -> None:
    for grant in (open_grant("propose_task"), fixed_grant("propose_task", {"name": "x"})):
        response = try_create(server, member.token, task_request(grants=[grant]))
        assert_problem(response, 422, "task.grant_not_allowed")


@pytest.mark.spec("TSK-004", "AGT-002")
@pytest.mark.parametrize("setting", ["ask", "deny"])
def test_a_tool_a_permission_asks_or_denies_cannot_be_granted(server: Server, member: Member, setting: str) -> None:
    _set_permissions(server, member, {"read_file": setting})
    for grant in (open_grant("read_file"), fixed_grant("read_file", {"path": "/workspace/notes.md"})):
        response = try_create(server, member.token, task_request(grants=[grant]))
        assert_problem(response, 422, "task.grant_not_allowed")


@pytest.mark.spec("TSK-004", "AGT-034")
@pytest.mark.parametrize("tool", ["web_search", "read_page", "request_internet_access"])
def test_the_web_tools_take_no_grants(server: Server, member: Member, tool: str) -> None:
    response = try_create(server, member.token, task_request(grants=[open_grant(tool)]))
    assert_problem(response, 422, "task.grant_not_allowed")


@pytest.mark.spec("TSK-004", "AGT-002", "AGT-034")
def test_internet_access_cannot_be_granted_to_a_user_denied_external_communication(
    server: Server, member: Member
) -> None:
    _set_permissions(server, member, {}, {"external_communication": "deny"})
    response = try_create(server, member.token, task_request(internet_access=True))
    assert_problem(response, 422, "task.grant_not_allowed")


@pytest.mark.spec("TSK-004", "AGT-002")
def test_a_grant_is_checked_again_at_every_call(database: Database, server: Server, member: Member) -> None:
    task = create_task(
        server, member.token, chain(("read_file", {"path": "/workspace/notes.md"})), grants=[open_grant("read_file")]
    )
    # After the task was saved, the household's admin asks every reading of a file by the user.
    _set_permissions(server, member, {"read_file": "ask"})
    item = _fired(database, server, member, task)
    assert item["outcome"] == "completed"
    assert outcomes(server, member.token, item["conversation_id"]) == ["not_granted"]


@pytest.mark.spec("TSK-004", "AGT-034")
def test_grants_cover_only_the_task_s_first_turn(
    database: Database, server: Server, member: Member, search_service: SearchServer
) -> None:
    task = create_task(server, member.token, _searches(fresh_query(), fresh_query()), internet_access=True)
    item = _fired(database, server, member, task)
    # The user continues the conversation: the ordinary rules apply, so a search asks for internet access.
    later = fresh_query("later")
    _, request = asked(server, member.token, item["conversation_id"], search(later))
    assert request["metadata"]["internet_access"]["untrusted_content"] is True
    assert not search_service.requests_for(later)


# --- TSK-005: grants never complete the lethal trifecta ---


TRIFECTAS: dict[str, dict[str, Any]] = {
    # An open way out, untrusted content from the web, and the workspace's files.
    "web and files": {"internet_access": True, "grants": [open_grant("read_file")]},
    # An open way out and untrusted content, with memory.
    "web and memory": {"internet_access": True, "uses_memory": True},
    # An open way out, and an event, which carries private data and untrusted content.
    "web and an event": {"internet_access": True, "triggers": [webhook()]},
    # Commands with network read the workspace and reach the internet (ADR-0113).
    "commands online": {"internet_access": True, "grants": [open_grant("run_command")]},
}


@pytest.mark.spec("TSK-005")
@pytest.mark.parametrize("fields", TRIFECTAS.values(), ids=TRIFECTAS.keys())
def test_grants_that_complete_the_lethal_trifecta_are_refused(
    server: Server, member: Member, fields: dict[str, Any]
) -> None:
    problem = assert_problem(try_create(server, member.token, task_request(**fields)), 422, "task.lethal_trifecta")
    check = problem["grant_check"]
    assert check["passes"] is False
    assert check["private_data"]
    assert check["untrusted_content"]
    assert check["external_communication"]
    with server.client(member.token) as client:
        assert body(client.get("/tasks"))["items"] == []


PASSING: dict[str, dict[str, Any]] = {
    # A press review: the web, and nothing private.
    "press review": {"internet_access": True},
    # Commands without network are no way out (ADR-0113).
    "commands offline": {"grants": [open_grant("run_command"), open_grant("read_file")]},
    # Files and an event, but no way out.
    "files and an event": {"grants": [open_grant("read_file")], "triggers": [webhook()]},
    # A fixed call carries nothing the model chose, so it is no way out.
    "fixed command": {"grants": [fixed_grant("run_command", {"command": "df -h"}), open_grant("read_file")]},
}


@pytest.mark.spec("TSK-005")
@pytest.mark.parametrize("fields", PASSING.values(), ids=PASSING.keys())
def test_grants_without_the_whole_trifecta_are_accepted(server: Server, member: Member, fields: dict[str, Any]) -> None:
    response = try_create(server, member.token, task_request(**fields))
    assert response.status_code == 201, response.text
    assert body(response)["grant_check"]["passes"] is True


@pytest.mark.spec("TSK-005")
def test_the_check_names_the_sources_of_each_element(server: Server, member: Member) -> None:
    problem = assert_problem(
        try_create(
            server,
            member.token,
            task_request(internet_access=True, grants=[open_grant("read_file")], triggers=[webhook()]),
        ),
        422,
        "task.lethal_trifecta",
    )
    check = problem["grant_check"]
    assert set(check["private_data"]) == {"read_file", "event_trigger"}
    assert set(check["untrusted_content"]) == {"read_file", "internet_access", "event_trigger"}
    assert set(check["external_communication"]) == {"internet_access"}


@pytest.mark.spec("TSK-005")
def test_a_trigger_or_a_change_that_would_complete_the_trifecta_is_refused(server: Server, member: Member) -> None:
    task = create_task(server, member.token, internet_access=True)
    with server.client(member.token) as client:
        added = client.post(f"/tasks/{task['id']}/triggers", json=webhook())
        assert_problem(added, 422, "task.lethal_trifecta")
        changed = client.patch(f"/tasks/{task['id']}", json={"grants": [open_grant("read_file")]})
        assert_problem(changed, 422, "task.lethal_trifecta")
        with_memory = client.patch(f"/tasks/{task['id']}", json={"uses_memory": True})
        assert_problem(with_memory, 422, "task.lethal_trifecta")
    unchanged = get_task(server, member.token, task["id"])
    assert unchanged["grants"] == []
    assert unchanged["internet_access"] is True
    # Nor the grant of internet access, given to a task that reads files.
    reading = create_task(server, member.token, grants=[open_grant("read_file")])
    with server.client(member.token) as client:
        online = client.patch(f"/tasks/{reading['id']}", json={"internet_access": True})
        assert_problem(online, 422, "task.lethal_trifecta")
    assert [trigger["kind"] for trigger in unchanged["triggers"]] == ["schedule"]
    assert unchanged["uses_memory"] is False


@pytest.mark.spec("TSK-005", "MEM-006")
def test_a_task_that_no_longer_passes_fires_without_grants(
    database: Database, server: Server, member: Member, search_service: SearchServer
) -> None:
    with server.client(member.token) as client:
        assert client.put("/me/memory", json={"enabled": False}).status_code == 200
    first, second = fresh_query("first"), fresh_query("second")
    # It uses memory, which is off for its user: memory is no source of private data yet.
    task = create_task(server, member.token, _searches(first, second), internet_access=True, uses_memory=True)
    assert task["grant_check"]["passes"] is True
    with server.client(member.token) as client:
        assert client.put("/me/memory", json={"enabled": True}).status_code == 200
    check = get_task(server, member.token, task["id"])["grant_check"]
    assert check["passes"] is False
    assert "memory" in check["private_data"]

    item = _fired(database, server, member, task)
    assert item["without_grants"] is True
    assert not search_service.requests_for(first)
    assert not search_service.requests_for(second)
    assert outcomes(server, member.token, item["conversation_id"]) == ["not_granted", "not_granted"]


# --- TSK-006: the assistant proposes a task ---


def _proposal(**fields: Any) -> str:
    return f"tool:propose_task {json.dumps(task_request('Summarize the news.', **fields))}"


@pytest.mark.spec("TSK-006", "AGT-006")
def test_a_proposed_task_is_saved_only_when_its_user_approves_it(server: Server, member: Member) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    proposal = _proposal(name="Press review", internet_access=True)
    _, interrupt = asked(server, member.token, conversation_id, proposal)
    request = interrupt["metadata"]["approval"]
    assert request["tool"] == "propose_task"
    assert request["reason"] == "task_proposal"
    assert request["scopes"] == ["once"]
    assert request["untrusted_content"] is False
    # The whole task is shown, grants included.
    assert request["arguments"]["internet_access"] is True
    with server.client(member.token) as client:
        assert body(client.get("/tasks"))["items"] == []

    resumed(server, member.token, conversation_id, [approve(interrupt["id"])])
    with server.client(member.token) as client:
        (saved,) = body(client.get("/tasks"))["items"]
    assert saved["name"] == "Press review"
    assert saved["internet_access"] is True

    # Denied, nothing is saved; and the next proposal is asked again.
    _, again = asked(server, member.token, conversation_id, _proposal(name="Second review"))
    resumed(server, member.token, conversation_id, [deny(again["id"])])
    with server.client(member.token) as client:
        assert [item["name"] for item in body(client.get("/tasks"))["items"]] == ["Press review"]


@pytest.mark.spec("TSK-006", "AGT-003")
def test_a_proposal_from_a_run_with_untrusted_content_says_so(server: Server, member: Member) -> None:
    conversation_id = with_untrusted_content(server, member.token)
    _, interrupt = asked(server, member.token, conversation_id, _proposal())
    assert interrupt["metadata"]["approval"]["untrusted_content"] is True


@pytest.mark.spec("TSK-006", "TSK-005")
def test_an_approved_proposal_that_completes_the_trifecta_is_not_saved(server: Server, member: Member) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    proposal = _proposal(internet_access=True, grants=[open_grant("read_file")])
    _, interrupt = asked(server, member.token, conversation_id, proposal)
    resumed(server, member.token, conversation_id, [approve(interrupt["id"])])
    with server.client(member.token) as client:
        assert body(client.get("/tasks"))["items"] == []


@pytest.mark.spec("TSK-006")
def test_a_task_s_run_cannot_propose_a_task(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token, _proposal(name="Nested"), triggers=[schedule()])
    item = _fired(database, server, member, task)
    assert item["outcome"] == "completed"
    assert outcomes(server, member.token, item["conversation_id"]) == ["not_granted"]
    with server.client(member.token) as client:
        assert [saved["id"] for saved in body(client.get("/tasks"))["items"]] == [task["id"]]
    # An ordinary run's proposal is still asked.
    conversation_id = create_conversation(server, member.token)["id"]
    run_id, _ = start_run(server, member.token, conversation_id, _proposal(name="Asked"))
    assert wait_for_run(server, member.token, run_id)["status"] == "interrupted"
