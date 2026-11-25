"""Web search and page reading, through runs (AGT-020, AGT-021, ADR-0074, ADR-0075).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py). Searches reach the search
service the tests serve (tests/support/search.py); pages are served from
inside the user's sandbox, on its own loopback address.
"""

from __future__ import annotations

import json
import secrets
import shlex

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.approvals import approving
from tests.support.browser import LIBRARY, LOAD, SEED_SWAP, call, chain, serve_pages
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run, text_of
from tests.support.sandbox import Driver
from tests.support.server import Server

PAGE_PORT = 8765
PAGE = """<!doctype html>
<html><head><title>Garden notes</title></head>
<body>
<nav><a href="/">Home</a> <a href="/shop">Shop for seedlings</a> <a href="/contact">Contact</a></nav>
<article>
<h1>Watering tomatoes</h1>
<p>Tomatoes want deep watering twice a week rather than a little every day,
so that their roots grow down into the cooler soil, where they find water
even in the hottest weeks of the summer.</p>
<p>Water early in the morning, at the foot of the plant, and keep the leaves
dry, which keeps blight away from them.</p>
</article>
<footer>Copyright the garden club</footer>
</body></html>
"""


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _call(tool: str, **arguments: str) -> str:
    return f"tool:{tool} {json.dumps(arguments)}"


def _tool_result(model: HarnessModel, text: str) -> str:
    """What the model received as the tool's result, for the run of `text`."""
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


def _tool_result_last(model: HarnessModel, text: str) -> str:
    """What the model was told of the last of its calls, for the run of `text`."""
    contents = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return contents[-1]


def _completed(server: Server, token: str, text: str, conversation_id: str | None = None) -> str:
    """Run `text` in the conversation, or a new one; the run's answer, once completed."""
    conversation = conversation_id or create_conversation(server, token)["id"]
    # With internet access for the turn (AGT-034).
    _, events, last = approving(server, token, conversation, text)
    assert get_run(server, token, last)["status"] == "completed"
    return text_of(events)


def _serve_page(sandboxes: Driver, account: Account, conversation_id: str, name: str, html: str) -> str:
    """Serve `html` at `name` from inside the conversation's sandbox, until its next answer ends; its address there."""
    tenant, user = str(account.tenant_id), str(account.id)
    written = sandboxes.sh(
        tenant, user, conversation_id, f"mkdir -p /tmp/site && printf %s {shlex.quote(html)} > /tmp/site/{name}"
    )
    assert written.exit_code == 0, written
    started = sandboxes.sh(
        tenant,
        user,
        conversation_id,
        f"cd /tmp/site && (setsid python3 -m http.server {PAGE_PORT} --bind 127.0.0.1 >/dev/null 2>&1 &)"
        f" ; for _ in $(seq 50); do curl -fso /dev/null http://127.0.0.1:{PAGE_PORT}/{name} && exit 0; sleep 0.1;"
        " done; exit 1",
    )
    assert started.exit_code == 0, started
    return f"http://127.0.0.1:{PAGE_PORT}/{name}"


@pytest.mark.spec("AGT-021")
def test_read_page_returns_the_main_text_of_a_page(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    address = _serve_page(sandboxes, account, conversation_id, "notes.html", PAGE)
    text = _call("read_page", url=address)
    assert _completed(server, token, text, conversation_id).startswith("Tool said:")
    content = _tool_result(default_model, text)
    assert "Garden notes" in content
    assert address in content
    assert "Watering tomatoes" in content
    assert "deep watering twice a week" in content
    assert "keep the leaves" in content
    # Only the main text: not the page's navigation.
    assert "Shop for seedlings" not in content
    assert "untrusted" in content.lower()


@pytest.mark.spec("AGT-021")
def test_read_page_output_is_bounded(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    words = " ".join(f"word{index}" for index in range(3_000))
    html = f"<html><body><article><p>{words}</p></article></body></html>"
    conversation_id = create_conversation(server, token)["id"]
    address = _serve_page(sandboxes, account, conversation_id, "long.html", html)
    text = _call("read_page", url=address)
    _completed(server, token, text, conversation_id)
    content = _tool_result(default_model, text)
    assert "word0 " in content
    assert len(content) < len(words)


@pytest.mark.spec("AGT-040")
def test_read_page_renders_a_page_built_by_its_script(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    opening = f"3:{secrets.randbelow(60):02d}"
    address = _serve_page(sandboxes, account, conversation_id, "swap.html", SEED_SWAP.replace("{opening}", opening))
    text = _call("read_page", url=address)
    assert _completed(server, token, text, conversation_id).startswith("Tool said:")
    content = _tool_result(default_model, text)
    # What only the page's script wrote.
    assert "Spring seed swap" in content
    assert f"The swap opens at {opening}" in content
    assert "rendered" in content.lower()
    assert "untrusted" in content.lower()


@pytest.mark.spec("AGT-040")
def test_read_page_does_not_render_a_page_it_can_read(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    paragraph = (
        "Tomatoes want deep watering twice a week rather than a little every day, so that their roots grow down "
        "into the cooler soil, where they find water even in the hottest weeks of the summer."
    )
    # Paragraphs that differ, since the reader keeps one of each repeated paragraph.
    article = "".join(f"<p>Week {week}: {paragraph}</p>" for week in range(1, 10))
    html = f"<html><head><title>Long notes</title></head><body><article>{article}</article></body></html>"
    conversation_id = create_conversation(server, token)["id"]
    address = _serve_page(sandboxes, account, conversation_id, "long-notes.html", html)
    text = _call("read_page", url=address)
    _completed(server, token, text, conversation_id)
    content = _tool_result(default_model, text)
    assert "deep watering twice a week" in content
    assert "rendered" not in content.lower()


@pytest.mark.spec("AGT-040", "AGT-039")
def test_rendering_leaves_the_browser_tools_alone(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    base = serve_pages(
        sandboxes,
        account,
        conversation_id,
        {"library.html": LIBRARY.replace("{opening}", "9:00"), "swap.html": SEED_SWAP.replace("{opening}", "3:00")},
    )
    text = chain(
        LOAD,
        call("browser_goto", url=f"{base}library.html"),
        call("read_page", url=f"{base}swap.html"),
        call("browser_get_url"),
    )
    _completed(server, token, text, conversation_id)
    content = _tool_result_last(default_model, text)
    assert f"{base}library.html" in content
    assert "afresh" not in content.lower()
