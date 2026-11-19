"""The assistant searches and reads the user's earlier conversations (AGT-032, AGT-033, AGT-003, ADR-0107).

What it reads is the user's private data; it is untrusted content only when
the conversation read holds untrusted content. A search after reading asks
for approval exactly then (AGT-004). The model the tests serve calls a tool
when the message is `tool:<name> <arguments>`, then answers
`Tool said: <result>` (tests/support/model.py).
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from tests.support.approvals import completed, fresh_query, search, with_untrusted_content
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.search import SearchServer, result
from tests.support.server import Server


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return f"tool:{name} {json.dumps(arguments)}"


def _said(server: Server, token: str, conversation_id: str, text: str) -> str:
    """Run `text` to completion: what the assistant said."""
    run_id, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    return text_of(events)


def _with_words(server: Server, token: str, *, temporary: bool = False) -> tuple[str, str]:
    """A conversation whose message holds fresh words: its ID and the words."""
    words = f"zebra{secrets.token_hex(4)}"
    with server.client(token) as client:
        response = client.post("/conversations", json={"temporary": temporary})
    assert response.status_code == 201, response.text
    conversation_id = response.json()["id"]
    completed(server, token, conversation_id, f"Remember the {words} plan")
    return conversation_id, words


def _asks_before_searching(server: Server, token: str, conversation_id: str) -> bool:
    """Whether a search in the conversation now asks for approval: whether it holds untrusted content."""
    run_id, _ = start_run(server, token, conversation_id, search(fresh_query()))
    return wait_for_run(server, token, run_id)["status"] == "interrupted"


# --- AGT-032: searching the user's conversations ---


@pytest.mark.spec("AGT-032")
def test_the_assistant_finds_the_user_s_conversations_by_their_words(server: Server, member: Member) -> None:
    found_id, words = _with_words(server, member.token)
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _tool("search_conversations", {"query": words}))
    assert found_id in said
    assert words in said


@pytest.mark.spec("AGT-032", "CNV-011", "TEN-007")
def test_search_never_finds_temporary_conversations_or_another_user_s(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    temporary_id, words = _with_words(server, member.token, temporary=True)
    other = new_member(database, server, default_model)
    theirs_id, their_words = _with_words(server, other.token)
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _tool("search_conversations", {"query": words}))
    assert temporary_id not in said
    said = _said(server, member.token, conversation_id, _tool("search_conversations", {"query": their_words}))
    assert theirs_id not in said


@pytest.mark.spec("AGT-032", "CNV-004")
def test_search_never_finds_what_a_rewind_removed(server: Server, member: Member) -> None:
    rewound_id, words = _with_words(server, member.token)
    with server.client(member.token) as client:
        response = client.post(f"/conversations/{rewound_id}/rewind", json={"run_id": None})
    assert response.status_code == 200, response.text
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _tool("search_conversations", {"query": words}))
    assert rewound_id not in said


@pytest.mark.spec("AGT-032", "AGT-003", "AGT-004")
def test_finding_a_conversation_with_untrusted_content_makes_the_run_untrusted(server: Server, member: Member) -> None:
    clean_id, clean_words = _with_words(server, member.token)
    tainted_id = with_untrusted_content(server, member.token)
    tainted_words = f"zebra{secrets.token_hex(4)}"
    completed(server, member.token, tainted_id, f"Remember the {tainted_words} plan")

    clean = create_conversation(server, member.token)["id"]
    assert clean_id in _said(server, member.token, clean, _tool("search_conversations", {"query": clean_words}))
    assert not _asks_before_searching(server, member.token, clean)

    tainted = create_conversation(server, member.token)["id"]
    assert tainted_id in _said(server, member.token, tainted, _tool("search_conversations", {"query": tainted_words}))
    assert _asks_before_searching(server, member.token, tainted)


# --- AGT-033: reading another conversation ---


@pytest.mark.spec("AGT-033")
def test_the_assistant_reads_another_conversation_without_its_tool_results(
    server: Server, member: Member, search_service: SearchServer
) -> None:
    read_id, words = _with_words(server, member.token)
    query = fresh_query("hidden")
    completed(server, member.token, read_id, search(query))
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _tool("read_conversation", {"conversation_id": read_id}))
    assert words in said
    assert "web_search" in said
    # The search's results, as the search service answered them, are not read.
    assert search_service.requests_for(query)
    assert result(query, 0)["title"] not in said
    assert result(query, 0)["content"] not in said


@pytest.mark.spec("AGT-033", "CNV-011", "TEN-007")
def test_reading_never_reaches_temporary_conversations_or_another_user_s(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    temporary_id, words = _with_words(server, member.token, temporary=True)
    other = new_member(database, server, default_model)
    theirs_id, their_words = _with_words(server, other.token)
    conversation_id = create_conversation(server, member.token)["id"]
    said = _said(server, member.token, conversation_id, _tool("read_conversation", {"conversation_id": temporary_id}))
    assert words not in said
    said = _said(server, member.token, conversation_id, _tool("read_conversation", {"conversation_id": theirs_id}))
    assert their_words not in said


@pytest.mark.spec("AGT-033", "AGT-003", "AGT-004")
@pytest.mark.parametrize("tainted", [False, True], ids=["clean", "tainted"])
def test_reading_makes_the_run_untrusted_only_when_the_conversation_read_is(
    server: Server, member: Member, tainted: bool
) -> None:
    read_id = with_untrusted_content(server, member.token) if tainted else _with_words(server, member.token)[0]
    conversation_id = create_conversation(server, member.token)["id"]
    _said(server, member.token, conversation_id, _tool("read_conversation", {"conversation_id": read_id}))
    assert _asks_before_searching(server, member.token, conversation_id) is tainted


@pytest.mark.spec("AGT-032", "AGT-033")
def test_the_tools_switch_off_with_their_group(server: Server, member: Member, default_model: HarnessModel) -> None:
    with server.client(member.token) as client:
        response = client.post("/conversations", json={"disabled_tools": ["search_conversations", "read_conversation"]})
    conversation_id = response.json()["id"]
    marker = f"offered {secrets.token_hex(4)}"
    _said(server, member.token, conversation_id, marker)
    (request,) = [r for r in default_model.endpoint.requests if r.user_texts()[-1:] == [marker]][:1]
    assert not {"search_conversations", "read_conversation"} & request.tool_names()
