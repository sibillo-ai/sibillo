"""Approval requests, and how tests answer them (AGT-004, AGT-006, AGT-007, AGT-012, AGT-034, ADR-0090, ADR-0113).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py). Searches reach the search
service the tests serve, whose results are untrusted content. The web tools
need internet access, which a conversation has only once its user gives it.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx

from tests.support.accounts import body
from tests.support.database import uuid7
from tests.support.runs import Event, create_conversation, parse_events, start_run, wait_for_run
from tests.support.server import Server

# The classes and approval defaults of ADR-0090, as ADR-0113 amends them.
DECLARED: dict[str, tuple[set[str], str]] = {
    "web_search": ({"ingests_untrusted", "external_communication"}, "allow"),
    "read_page": ({"ingests_untrusted", "external_communication"}, "allow"),
    # Asks for internet access, and does nothing else (AGT-034).
    "request_internet_access": (set[str](), "allow"),
    # A command's only way out is the sandbox's network, which internet access governs (ADR-0113).
    "run_command": ({"reads_private_data", "ingests_untrusted"}, "allow"),
    "start_command": ({"reads_private_data", "ingests_untrusted"}, "allow"),
    **{
        name: ({"reads_private_data", "ingests_untrusted"}, "allow")
        for name in (
            "check_command",
            "read_file",
            # It returns the command's output, as `check_command` does (ADR-0127).
            "stop_command",
            "list_directory",
            "find_files",
            "search_files",
            "file_info",
            "view_image",
            "read_tool_result",
        )
    },
    **{
        name: ({"reads_private_data"}, "allow")
        for name in ("write_file", "edit_file", "create_directory", "offer_download")
    },
    **{
        name: (set[str](), "allow")
        for name in (
            "ask_user_question",
            "write_plan",
            "read_plan",
            "add_task",
            "update_task_status",
            "update_task_statuses",
            "remove_task",
            # They change only the user's own memory, guarded by its provenance (ADR-0095).
            "remember",
            "update_memory",
            "forget",
            # Loads a skill: its body is untrusted when the skill is, by provenance (AGT-025, ADR-0096).
            "load_capability",
        )
    },
    # Saves a skill that reaches later conversations: the user sees it first (AGT-026, ADR-0096).
    "save_skill": (set[str](), "ask"),
    # Saves a task that runs later with standing grants: the user sees all of it first (TSK-006, ADR-0106).
    "propose_task": (set[str](), "ask"),
    # Changes a task: the user sees the whole change first (TSK-012, ADR-0107).
    "update_task": (set[str](), "ask"),
    # Read the user's tasks and conversations: private data, untrusted by what they read (ADR-0107).
    "list_tasks": ({"reads_private_data"}, "allow"),
    "search_conversations": ({"reads_private_data"}, "allow"),
    "read_conversation": ({"reads_private_data"}, "allow"),
    # Hands a brief to a delegated run: private data, untrusted by what the delegated run read (ADR-0136).
    "delegate": ({"reads_private_data"}, "allow"),
}


def search(query: str) -> str:
    return f"tool:web_search {json.dumps({'query': query})}"


def fresh_query(label: str = "query") -> str:
    return f"{label} {secrets.token_hex(4)}"


def interrupts(events: list[Event]) -> list[dict[str, Any]]:
    """The interrupts the run finished with; none when it finished otherwise."""
    (finished,) = [event for event in events if event.type == "RUN_FINISHED"]
    outcome: dict[str, Any] = finished.data.get("outcome") or {}
    found: list[dict[str, Any]] = outcome.get("interrupts", [])
    return found if outcome.get("type") == "interrupt" else []


def approval_of(events: list[Event]) -> dict[str, Any]:
    """The one approval request the run ended with."""
    (interrupt,) = interrupts(events)
    assert interrupt["reason"] == "approval", interrupt
    return interrupt


def internet_request(events: list[Event]) -> dict[str, Any]:
    """The one request for internet access the run ended with (AGT-034)."""
    interrupt = approval_of(events)
    assert interrupt["id"].startswith("apr-internet-"), interrupt
    return interrupt


def approve(interrupt_id: str, scope: str = "once") -> dict[str, Any]:
    return {"interruptId": interrupt_id, "status": "resolved", "payload": {"approved": True, "scope": scope}}


def deny(interrupt_id: str) -> dict[str, Any]:
    return {"interruptId": interrupt_id, "status": "resolved", "payload": {"approved": False}}


def resume(server: Server, token: str, conversation_id: str, entries: list[dict[str, Any]]) -> httpx.Response:
    """Answer the pending interrupts: the response, streamed in full."""
    payload = {"threadId": conversation_id, "runId": str(uuid7()), "messages": [], "resume": entries}
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/runs", json=payload, timeout=60)


def resumed(server: Server, token: str, conversation_id: str, entries: list[dict[str, Any]]) -> list[Event]:
    """Answer the pending interrupts, and wait for the run that continues: its events."""
    response = resume(server, token, conversation_id, entries)
    assert response.status_code == 200, response.text
    events = parse_events(response.text.splitlines())
    wait_for_run(server, token, events[0].data["runId"])
    return events


def conversation_of(server: Server, token: str, conversation_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        return body(client.get(f"/conversations/{conversation_id}"))


def completed(server: Server, token: str, conversation_id: str, text: str) -> list[Event]:
    """Run `text`, which needs no approval, to completion: its events."""
    run_id, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed", interrupts(events)
    return events


def with_untrusted_content(server: Server, token: str) -> str:
    """A new conversation whose first turn searched the web, with internet access for that turn only: it has
    untrusted content from then on, and no internet access."""
    conversation_id = create_conversation(server, token)["id"]
    approving(server, token, conversation_id, search(fresh_query("first")))
    return conversation_id


def holds_untrusted_content(server: Server, token: str, conversation_id: str) -> bool:
    """Whether a run in the conversation, which has no internet access, now holds untrusted content: what the
    request for internet access of a search says (AGT-003, AGT-034). The request is left pending."""
    run_id, events = start_run(server, token, conversation_id, search(fresh_query("probe")))
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    untrusted: bool = internet_request(events)["metadata"]["internet_access"]["untrusted_content"]
    return untrusted


def asked(server: Server, token: str, conversation_id: str, text: str) -> tuple[str, dict[str, Any]]:
    """Run `text`, which ends asking for approval: the run and its request."""
    run_id, events = start_run(server, token, conversation_id, text)
    # Its status follows its last event.
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    return run_id, approval_of(events)


def activity(server: Server, token: str, **params: str) -> list[dict[str, Any]]:
    with server.client(token) as client:
        response = client.get("/me/activity", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = body(response)["items"]
    return items


def _broadest(interrupt: dict[str, Any]) -> str:
    """For the turn when the request offers it; otherwise the one scope it offers, such as `once` (ADR-0127)."""
    metadata: dict[str, Any] = interrupt["metadata"]
    request: dict[str, Any] = metadata.get("approval") or metadata.get("internet_access") or {}
    scopes = [str(scope) for scope in request.get("scopes", ["turn"])]
    return "turn" if "turn" in scopes else scopes[0]


def approving(server: Server, token: str, conversation_id: str, text: str) -> tuple[str, list[Event], str]:
    """Run `text`, approving every request it makes, for the turn where it may be (ADR-0090): its first run, every
    event, its last run.

    For tests of other things that search the web or read pages, which ask for internet access (AGT-034).
    """
    run_id, events = start_run(server, token, conversation_id, text)
    seen = list(events)
    last = run_id
    while wait_for_run(server, token, last)["status"] == "interrupted":
        pending = [interrupt for interrupt in interrupts(events) if interrupt["reason"] == "approval"]
        assert pending, "the run asks a question, not for approval"
        events = resumed(server, token, conversation_id, [approve(i["id"], _broadest(i)) for i in pending])
        seen += events
        last = events[0].data["runId"]
    return run_id, seen, last
