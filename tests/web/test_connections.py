"""Changing a connection in the household's settings (UX-025, UX-016, MOD-008)."""

from __future__ import annotations

import re
import socket
from typing import Any
from uuid import uuid4

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.support.accounts import Account, body, login
from tests.support.fixtures import HarnessModel
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _connections(server: Server, admin: Account) -> dict[str, dict[str, Any]]:
    with server.client(login(server, admin)) as client:
        response = client.get("/tenant/connections")
    assert response.status_code == 200, response.text
    return {item["name"]: item for item in body(response)["items"]}


def _add(server: Server, admin: Account, json: dict[str, Any]) -> dict[str, Any]:
    with server.client(login(server, admin)) as client:
        response = client.post("/tenant/connections", json=json)
    assert response.status_code == 201, response.text
    return body(response)


def _settings(page: Page, admin: Account) -> None:
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()


def _edit(page: Page, name: str) -> Locator:
    page.get_by_role("button", name=f"Edit {name}").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    return dialog


@pytest.mark.spec("UX-025")
def test_adding_a_server_sets_its_context_window(
    page: Page, server: Server, admin: Account, default_model: HarnessModel
) -> None:
    _settings(page, admin)
    page.get_by_role("button", name="Add a connection").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Your own server").click()
    name = f"Workstation {uuid4().hex[:6]}"
    dialog.get_by_label("Name", exact=True).fill(name)
    dialog.get_by_label("Address").fill(default_model.endpoint.url)
    dialog.get_by_label("Context window").fill("16384")
    dialog.get_by_role("button", name="Connect", exact=True).click()
    expect(page.get_by_role("main")).to_contain_text(f"{name}Runs at home", timeout=30_000)
    assert _connections(server, admin)[name]["context_window"] == 16384


@pytest.mark.spec("UX-025")
def test_changing_a_server_keeps_what_is_not_changed(
    page: Page, server: Server, admin: Account, default_model: HarnessModel
) -> None:
    name = f"Gaming PC {uuid4().hex[:6]}"
    _add(
        server,
        admin,
        {
            "name": name,
            "kind": "openai",
            "base_url": default_model.endpoint.url,
            "location": "local",
            "api_key": f"key-{uuid4().hex}",
        },
    )
    _settings(page, admin)
    dialog = _edit(page, name)
    # The form starts from the connection as it is, and never shows its key.
    expect(dialog.get_by_label("Name", exact=True)).to_have_value(name)
    expect(dialog.get_by_label("Address")).to_have_value(default_model.endpoint.url)
    expect(dialog.get_by_label("Context window")).to_have_value("8192")
    expect(dialog.get_by_label(re.compile("^New API key"))).to_have_value("")
    assert accessibility_violations(page) == []
    renamed = f"Office PC {uuid4().hex[:6]}"
    dialog.get_by_label("Name", exact=True).fill(renamed)
    dialog.get_by_label("Context window").fill("32768")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden(timeout=30_000)
    expect(page.get_by_role("main")).to_contain_text(f"{renamed}Runs at home")
    changed = _connections(server, admin)[renamed]
    assert (changed["context_window"], changed["base_url"], changed["has_api_key"]) == (
        32768,
        default_model.endpoint.url,
        True,
    )
    # The key of a connection to the household's own server can be removed.
    dialog = _edit(page, renamed)
    dialog.get_by_label("Remove the API key").check()
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden(timeout=30_000)
    assert _connections(server, admin)[renamed]["has_api_key"] is False


@pytest.mark.spec("UX-025")
def test_a_change_that_fails_its_test_is_not_saved(
    page: Page, server: Server, admin: Account, default_model: HarnessModel
) -> None:
    name = f"Laptop {uuid4().hex[:6]}"
    _add(server, admin, {"name": name, "kind": "openai", "base_url": default_model.endpoint.url, "location": "local"})
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    _settings(page, admin)
    dialog = _edit(page, name)
    dialog.get_by_label("Address").fill(f"http://127.0.0.1:{closed}/v1")
    dialog.get_by_role("button", name="Save").click()
    result = dialog.get_by_role("alert")
    expect(result).to_contain_text(str(closed), timeout=30_000)
    dialog.get_by_role("button", name="Cancel").click()
    assert _connections(server, admin)[name]["base_url"] == default_model.endpoint.url


@pytest.mark.spec("UX-025")
def test_openrouter_asks_only_for_a_name_and_a_new_key(
    page: Page, server: Server, admin: Account, default_model: HarnessModel
) -> None:
    name = f"OpenRouter {uuid4().hex[:6]}"
    _add(
        server,
        admin,
        {
            "name": name,
            "kind": "openrouter",
            "base_url": default_model.endpoint.openrouter_url,
            "api_key": f"sk-or-v1-{uuid4().hex}",
        },
    )
    _settings(page, admin)
    dialog = _edit(page, name)
    expect(dialog.get_by_label("Name", exact=True)).to_have_value(name)
    expect(dialog.get_by_label(re.compile("^New API key"))).to_have_value("")
    expect(dialog.get_by_label("Address")).to_have_count(0)
    expect(dialog.get_by_label("Context window")).to_have_count(0)
    expect(dialog.get_by_label("Remove the API key")).to_have_count(0)
    renamed = f"Router {uuid4().hex[:6]}"
    dialog.get_by_label("Name", exact=True).fill(renamed)
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden(timeout=30_000)
    assert _connections(server, admin)[renamed]["has_api_key"] is True
