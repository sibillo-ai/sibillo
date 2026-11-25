"""Memory: items the user sees and the assistant is given, kept through tools, with their provenance
(MEM-001 to MEM-008, ADR-0095).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>`, and several tools in turn with `chain:`
(tests/support/model.py). Searches reach the search service the tests serve,
whose results are untrusted content.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    approval_of,
    approve,
    approving,
    asked,
    completed,
    deny,
    fresh_query,
    holds_untrusted_content,
    resumed,
    search,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.model import ModelRequest
from tests.support.runs import create_conversation, messages, start_run, text_of, wait_for_run
from tests.support.search import SearchServer
from tests.support.server import Server

MEMORY_TOOLS = {"remember", "update_memory", "forget"}


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _memory(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/me/memory")
    assert response.status_code == 200, response.text
    return body(response)


def _items(server: Server, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _memory(server, token)["items"]
    return items


def _add(server: Server, token: str, text: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.post("/me/memory/items", json={"text": text})
    assert response.status_code == 201, response.text
    return body(response)


def _edit(server: Server, token: str, item_id: str, text: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.patch(f"/me/memory/items/{item_id}", json={"text": text})
    assert response.status_code == 200, response.text
    return body(response)


def _switch(server: Server, token: str, enabled: bool) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.put("/me/memory", json={"enabled": enabled})
    assert response.status_code == 200, response.text
    return body(response)


def _request(server: Server, token: str, model: HarnessModel, conversation_id: str, text: str) -> ModelRequest:
    """Run `text` in the conversation, and the first request it made to the model."""
    completed(server, token, conversation_id, text)
    return model.endpoint.requests_with(text)[0]


def _new_request(server: Server, token: str, model: HarnessModel) -> ModelRequest:
    conversation_id = create_conversation(server, token)["id"]
    return _request(server, token, model, conversation_id, f"hello {secrets.token_hex(4)}")


def _tool(name: str, **arguments: Any) -> str:
    return f"tool:{name} {json.dumps(arguments)}"


def _fact(label: str = "fact") -> str:
    return f"The user's {label} is {secrets.token_hex(6)}."


@pytest.mark.spec("MEM-001", "MEM-006", "MEM-007")
def test_memory_starts_on_and_empty(server: Server, token: str) -> None:
    assert _memory(server, token) == {"enabled": True, "items": [], "used_characters": 0, "limit_characters": 10_000}


@pytest.mark.spec("MEM-001", "MEM-002", "MEM-003", "MEM-005", "MEM-008")
def test_the_user_adds_edits_and_deletes_items(server: Server, token: str) -> None:
    first = _add(server, token, "  Lives in Bologna.  ")
    # Surrounding whitespace is removed; the user's items are trusted and come from no conversation.
    assert first["text"] == "Lives in Bologna."
    assert (first["origin"], first["untrusted"], first["conversation"]) == ("user", False, None)
    second = _add(server, token, "Has a cat named Miso.")
    # Newest first, every character counted.
    memory = _memory(server, token)
    assert [item["id"] for item in memory["items"]] == [second["id"], first["id"]]
    assert memory["used_characters"] == len("Lives in Bologna.") + len("Has a cat named Miso.")
    # Editing the older one makes it the most recently written.
    edited = _edit(server, token, first["id"], "Lives in Modena.")
    assert edited["text"] == "Lives in Modena."
    assert edited["updated_at"] >= edited["created_at"]
    assert [item["text"] for item in _items(server, token)] == ["Lives in Modena.", "Has a cat named Miso."]
    with server.client(token) as client:
        assert client.delete(f"/me/memory/items/{second['id']}").status_code == 204
        assert_problem(client.delete(f"/me/memory/items/{second['id']}"), 404, "resource.not_found")
        assert_problem(client.patch(f"/me/memory/items/{second['id']}", json={"text": "x"}), 404, "resource.not_found")
    assert [item["text"] for item in _items(server, token)] == ["Lives in Modena."]
    # Everything at once.
    _add(server, token, "Prefers short answers.")
    with server.client(token) as client:
        assert client.delete("/me/memory/items").status_code == 204
    assert _memory(server, token)["items"] == []


@pytest.mark.spec("MEM-007")
def test_an_item_or_the_memory_over_its_limit_is_refused(server: Server, token: str) -> None:
    with server.client(token) as client:
        assert_problem(client.post("/me/memory/items", json={"text": "x" * 501}), 422, "request.validation_failed")
        assert_problem(client.post("/me/memory/items", json={"text": "   "}), 422, "request.validation_failed")
    for _ in range(20):
        _add(server, token, "y" * 500)
    assert _memory(server, token)["used_characters"] == 10_000
    item_id = _items(server, token)[0]["id"]
    with server.client(token) as client:
        assert_problem(client.post("/me/memory/items", json={"text": "z"}), 422, "memory.full")
        # An item can shrink, and then grow back to the limit but not past it; nothing else is written.
        assert client.patch(f"/me/memory/items/{item_id}", json={"text": "y" * 400}).status_code == 200
        assert client.patch(f"/me/memory/items/{item_id}", json={"text": "y" * 450}).status_code == 200
        assert_problem(client.post("/me/memory/items", json={"text": "z" * 51}), 422, "memory.full")
    assert _memory(server, token)["used_characters"] == 9_950


@pytest.mark.spec("MEM-002", "MEM-003", "MEM-007")
def test_every_run_is_given_the_items_as_they_are_when_it_starts(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    before = _request(server, token, default_model, conversation_id, f"before {secrets.token_hex(4)}")
    fact = _fact()
    item = _add(server, token, fact)
    # Also in a conversation that started before the item existed.
    assert (
        fact in _request(server, token, default_model, conversation_id, f"after {secrets.token_hex(4)}").system_text()
    )
    assert fact not in before.system_text()
    # With its ID, for the tools that change it, and in a new conversation too.
    system = _new_request(server, token, default_model).system_text()
    assert fact in system
    assert item["id"] in system
    edited = _fact("edited")
    _edit(server, token, item["id"], edited)
    system = _request(server, token, default_model, conversation_id, f"edited {secrets.token_hex(4)}").system_text()
    assert edited in system
    assert fact not in system
    with server.client(token) as client:
        assert client.delete(f"/me/memory/items/{item['id']}").status_code == 204
    system = _request(server, token, default_model, conversation_id, f"deleted {secrets.token_hex(4)}").system_text()
    assert edited not in system


@pytest.mark.spec("MEM-003")
def test_deletion_is_physical_and_runs_keep_no_copy(
    database: Database, server: Server, token: str, default_model: HarnessModel
) -> None:
    fact = _fact()
    item = _add(server, token, fact)
    conversation_id = create_conversation(server, token)["id"]
    assert fact in _request(server, token, default_model, conversation_id, f"run {secrets.token_hex(4)}").system_text()
    with database.superuser() as conn:
        # Stored messages hold no instructions, and so no memory; nor do the inputs of durable workflows.
        stored = conn.execute(
            "SELECT count(*) FROM conversation_messages WHERE conversation_id = %s AND message::text LIKE %s",
            (conversation_id, f"%{fact}%"),
        ).fetchone()
        assert stored == (0,)
        inputs = conn.execute(
            "SELECT count(*) FROM dbos.workflow_status WHERE inputs LIKE %s", (f"%{fact}%",)
        ).fetchone()
        assert inputs == (0,)
    with server.client(token) as client:
        assert client.delete(f"/me/memory/items/{item['id']}").status_code == 204
    with database.superuser() as conn:
        assert conn.execute("SELECT count(*) FROM memory_items WHERE id = %s", (item["id"],)).fetchone() == (0,)


@pytest.mark.spec("MEM-005", "MEM-007")
def test_the_assistant_remembers_through_a_tool_that_shows_in_the_conversation(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token, title="Planning the garden")
    fact = _fact("garden")
    request = _request(server, token, default_model, conversation["id"], _tool("remember", text=fact))
    assert request.tool_names() >= MEMORY_TOOLS
    (item,) = _items(server, token)
    assert (item["text"], item["origin"], item["untrusted"]) == (fact, "assistant", False)
    assert item["conversation"] == {"id": conversation["id"], "title": "Planning the garden", "deleted": False}
    # The call is part of the conversation, like any tool call.
    shown = json.dumps(messages(server, token, conversation["id"])["items"])
    assert "remember" in shown
    assert fact in shown
    # The item outlives its conversation, which it names as deleted.
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation['id']}").status_code == 204
    (item,) = _items(server, token)
    assert item["conversation"] == {"id": conversation["id"], "title": None, "deleted": True}


@pytest.mark.spec("MEM-007")
def test_the_assistant_updates_and_forgets_items_by_their_id(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    kept, dropped = _add(server, token, _fact("kept")), _add(server, token, _fact("dropped"))
    conversation_id = create_conversation(server, token)["id"]
    updated = _fact("updated")
    completed(server, token, conversation_id, _tool("update_memory", id=kept["id"], text=updated))
    completed(server, token, conversation_id, _tool("forget", id=dropped["id"]))
    (item,) = _items(server, token)
    assert (item["id"], item["text"], item["origin"]) == (kept["id"], updated, "assistant")
    assert item["conversation"]["id"] == conversation_id
    # An item that is not there is an error the assistant is told about.
    events = completed(server, token, conversation_id, _tool("forget", id=dropped["id"]))
    assert "Tool said:" in text_of(events)
    assert [i["id"] for i in _items(server, token)] == [kept["id"]]


@pytest.mark.spec("MEM-007")
def test_the_assistant_is_told_when_memory_is_full(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation_id = create_conversation(server, token)["id"]
    events = completed(server, token, conversation_id, _tool("remember", text="x" * 501))
    assert "500" in text_of(events)
    for _ in range(20):
        _add(server, token, "y" * 500)
    events = completed(server, token, conversation_id, _tool("remember", text="One more thing."))
    assert "10,000" in text_of(events) or "10000" in text_of(events)
    # Nothing was cut to fit.
    assert {item["text"] for item in _items(server, token)} == {"y" * 500}


@pytest.mark.spec("MEM-008", "AGT-003", "AGT-004")
def test_items_written_after_untrusted_content_are_untrusted_until_the_user_saves_them(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    planted = _fact("planted")
    query = fresh_query("garden")
    # What the search returns is untrusted, and so is what follows.
    approving(
        server,
        token,
        conversation_id,
        f"chain:web_search {json.dumps({'query': query})} >>> remember {json.dumps({'text': planted})}",
    )
    (item,) = _items(server, token)
    assert (item["text"], item["origin"], item["untrusted"]) == (planted, "assistant", True)
    # A new conversation is given it labeled as untrusted, and is untrusted from its start: its first request
    # for internet access says so.
    fresh = create_conversation(server, token)["id"]
    text = search(fresh_query("first"))
    _, request = asked(server, token, fresh, text)
    assert request["metadata"]["internet_access"]["untrusted_content"] is True
    system = default_model.endpoint.requests_with(text)[0].system_text()
    assert planted in system
    assert "untrusted" in system[system.index(item["id"]) - 200 : system.index(planted) + 200].lower()
    # Saved by the user, unchanged: confirmed, trusted, and runs are trusted again.
    saved = _edit(server, token, item["id"], planted)
    assert (saved["origin"], saved["untrusted"], saved["conversation"]) == ("user", False, None)
    assert holds_untrusted_content(server, token, create_conversation(server, token)["id"]) is False


@pytest.mark.spec("MEM-008")
def test_an_item_updated_after_untrusted_content_becomes_untrusted(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    item = _add(server, token, _fact())
    conversation_id = create_conversation(server, token)["id"]
    changed = _fact("changed")
    approving(
        server,
        token,
        conversation_id,
        f"chain:web_search {json.dumps({'query': fresh_query()})}"
        f" >>> update_memory {json.dumps({'id': item['id'], 'text': changed})}",
    )
    (updated,) = _items(server, token)
    assert (updated["text"], updated["origin"], updated["untrusted"]) == (changed, "assistant", True)


@pytest.mark.spec("MEM-008")
def test_items_written_without_untrusted_content_do_not_make_runs_untrusted(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    completed(server, token, create_conversation(server, token)["id"], _tool("remember", text=_fact()))
    assert _items(server, token)[0]["untrusted"] is False
    assert holds_untrusted_content(server, token, create_conversation(server, token)["id"]) is False


@pytest.mark.spec("MEM-006", "MEM-007")
def test_while_memory_is_off_runs_get_no_items_and_no_tools(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    fact = _fact()
    _add(server, token, fact)
    off = _switch(server, token, False)
    assert off["enabled"] is False
    # The items stay, and the user still manages them.
    assert [item["text"] for item in off["items"]] == [fact]
    request = _new_request(server, token, default_model)
    assert fact not in request.system_text()
    assert not MEMORY_TOOLS & request.tool_names()
    edited = _fact("edited")
    _edit(server, token, _items(server, token)[0]["id"], edited)
    assert _switch(server, token, True)["enabled"] is True
    request = _new_request(server, token, default_model)
    assert edited in request.system_text()
    assert request.tool_names() >= MEMORY_TOOLS


@pytest.mark.spec("MEM-007", "CNV-011")
def test_temporary_conversations_neither_read_nor_write_memory(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    fact = _fact()
    _add(server, token, fact)
    with server.client(token) as client:
        response = client.post("/conversations", json={"temporary": True})
    assert response.status_code == 201, response.text
    text = f"temporary {secrets.token_hex(4)}"
    request = _request(server, token, default_model, body(response)["id"], text)
    assert fact not in request.system_text()
    assert not MEMORY_TOOLS & request.tool_names()


@pytest.mark.spec("MEM-007", "CNV-013")
def test_memory_tools_switched_off_in_a_conversation_are_not_offered(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    fact = _fact()
    _add(server, token, fact)
    conversation_id = create_conversation(server, token)["id"]
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": ["remember", "forget"]})
    assert response.status_code == 200, response.text
    request = _request(server, token, default_model, conversation_id, f"some {secrets.token_hex(4)}")
    assert request.tool_names() & MEMORY_TOOLS == {"update_memory"}
    # Items are still given: the switches are about writing.
    assert fact in request.system_text()


@pytest.mark.spec("MEM-004", "TEN-006")
def test_items_of_others_cannot_be_read_changed_or_deleted(
    database: Database, server: Server, token: str, account: Account
) -> None:
    mine = _add(server, token, _fact())
    for other in (create_account(database, account.tenant_id), create_account(database, create_tenant(database))):
        other_token = login(server, other)
        assert _items(server, other_token) == []
        with server.client(other_token) as client:
            assert_problem(
                client.patch(f"/me/memory/items/{mine['id']}", json={"text": "x"}), 404, "resource.not_found"
            )
            assert_problem(client.delete(f"/me/memory/items/{mine['id']}"), 404, "resource.not_found")
            assert client.delete("/me/memory/items").status_code == 204
    assert [item["id"] for item in _items(server, token)] == [mine["id"]]


@pytest.mark.spec("MEM-008", "AGT-004")
def test_an_untrusted_run_asks_before_it_changes_or_forgets_what_the_user_wrote(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    mine = _add(server, token, _fact("own"))
    for tool, arguments in (
        ("forget", {"id": mine["id"]}),
        ("update_memory", {"id": mine["id"], "text": _fact("planted")}),
    ):
        conversation_id = create_conversation(server, token)["id"]
        chain = f"chain:web_search {json.dumps({'query': fresh_query('page')})} >>> {tool} {json.dumps(arguments)}"
        _, internet = asked(server, token, conversation_id, chain)
        # After the page, the change of an item the user wrote asks, and says what it says now (ADR-0127).
        events = resumed(server, token, conversation_id, [approve(internet["id"], "turn")])
        request = approval_of(events)
        approval = request["metadata"]["approval"]
        assert (approval["tool"], approval["reason"]) == (tool, "untrusted_content")
        assert mine["text"] in json.dumps(approval)
        resumed(server, token, conversation_id, [deny(request["id"])])
        assert [item["text"] for item in _items(server, token)] == [mine["text"]]
    # An item the assistant wrote from untrusted content is changed without asking.
    conversation_id = create_conversation(server, token)["id"]
    planted = _fact("planted")
    approving(
        server,
        token,
        conversation_id,
        f"chain:web_search {json.dumps({'query': fresh_query('again')})} >>> remember {json.dumps({'text': planted})}",
    )
    (own,) = [item for item in _items(server, token) if item["text"] == planted]
    run_id, _ = start_run(server, token, conversation_id, f"tool:forget {json.dumps({'id': own['id']})}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert [item["text"] for item in _items(server, token)] == [mine["text"]]
