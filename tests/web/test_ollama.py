"""An Ollama server's own context window, in the household's settings (MOD-019, ADR-0093)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, body, login
from tests.support.fixtures import HarnessModel
from tests.support.model import OLLAMA_CONTEXT_LENGTH
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in

CONNECTION_WINDOW = 32768


@pytest.mark.spec("MOD-019", "UX-014")
def test_admins_are_told_when_ollama_serves_a_smaller_window(
    page: Page, server: Server, admin: Account, default_model: HarnessModel
) -> None:
    token = login(server, admin)
    with server.client(token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "Ollama box",
                "kind": "openai",
                "base_url": default_model.endpoint.ollama_url,
                "location": "local",
                "context_window": CONNECTION_WINDOW,
            },
        )
        assert response.status_code == 201, response.text
        connection_id = body(response)["id"]
        conversation = create_conversation(server, token)["id"]
        chosen = client.patch(
            f"/conversations/{conversation}", json={"model": {"connection_id": connection_id, "model": "test-model"}}
        )
        assert chosen.status_code == 200, chosen.text
    run_id, _ = start_run(server, token, conversation, "hello")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    warning = page.get_by_role("main").get_by_text("OLLAMA_CONTEXT_LENGTH")
    expect(warning).to_be_visible(timeout=30_000)
    note = page.get_by_role("main").get_by_role("note").filter(has_text="OLLAMA_CONTEXT_LENGTH")
    expect(note).to_contain_text("test-model")
    expect(note).to_contain_text(f"{OLLAMA_CONTEXT_LENGTH:,}")
    expect(note).to_contain_text(f"{CONNECTION_WINDOW:,}")
    assert accessibility_violations(page) == []
