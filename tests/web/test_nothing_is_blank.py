"""Nothing is blank in the web client (UX-038, ADR-0111).

An empty list says what it is for and offers the action that adds its first
entry; a list that is loading says so, rather than that it is empty; an
action in progress shows it, and cannot be started a second time.

Tests hold the client's requests in the browser to see what it shows while
they are on their way, then let them through.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route, expect

from tests.support.accounts import Account, login
from tests.support.server import Server
from tests.support.tasks import create_task
from tests.web.conftest import accessibility_violations, sign_in


class Held:
    """The requests of one method to one address, held until released."""

    def __init__(self, page: Page, url: re.Pattern[str], method: str) -> None:
        self.routes: list[Route] = []
        self._released = False

        def handle(route: Route) -> None:
            if route.request.method == method and not self._released:
                self.routes.append(route)
            else:
                route.fallback()

        self._handle: Callable[[Route], None] = handle
        page.route(url, handle)

    def release(self) -> None:
        """Let the held requests through, and those that follow, which are not counted."""
        self._released = True
        for route in self.routes:
            route.continue_()


def _settings(page: Page, group: str, section: str) -> None:
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name=group).get_by_role("button", name=section).click()


@pytest.mark.spec("UX-038")
def test_an_empty_list_says_what_it_is_for_and_offers_its_first_entry(page: Page, member: Account) -> None:
    sign_in(page, member)
    conversations = page.get_by_role("navigation", name="Conversations")
    expect(conversations).to_contain_text("No conversations yet")
    expect(conversations).to_contain_text("Your conversations appear here")

    _settings(page, "Yours", "Memory")
    memory = page.get_by_role("region", name="Memory")
    expect(memory).to_contain_text("Nothing remembered yet")
    expect(memory).to_contain_text("What the assistant remembers about you appears here")
    expect(memory.get_by_role("button", name="Add")).to_have_count(1)
    assert accessibility_violations(page) == []

    _settings(page, "Yours", "Tasks")
    tasks = page.get_by_role("region", name="Tasks")
    expect(tasks).to_contain_text("No tasks yet")
    expect(tasks).to_contain_text("A task starts a conversation on its own")
    expect(tasks.get_by_role("button", name="New task")).to_have_count(1)


@pytest.mark.spec("UX-038")
def test_an_empty_household_list_offers_its_first_entry_to_a_tenant_admin(page: Page, admin: Account) -> None:
    sign_in(page, admin)
    _settings(page, "Household", "MCP servers")
    servers = page.get_by_role("region", name="MCP servers")
    expect(servers).to_contain_text("No server yet")
    expect(servers).to_contain_text("An MCP server brings the tools of a service")
    expect(servers.get_by_role("button", name="Add a server")).to_have_count(1)
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-038")
def test_a_list_that_is_loading_says_so_and_not_that_it_is_empty(page: Page, member: Account) -> None:
    held = Held(page, re.compile(r"/v1/conversation-list(\?|$)"), "GET")
    sign_in(page, member)
    conversations = page.get_by_role("navigation", name="Conversations")
    expect(conversations.get_by_role("status").filter(has_text="Loading")).to_be_visible()
    expect(conversations).not_to_contain_text("No conversations yet")
    held.release()
    expect(conversations).to_contain_text("No conversations yet")
    expect(conversations.get_by_role("status").filter(has_text="Loading")).to_have_count(0)

    held = Held(page, re.compile(r"/v1/me/memory$"), "GET")
    _settings(page, "Yours", "Memory")
    memory = page.get_by_role("region", name="Memory")
    expect(memory.get_by_role("status").filter(has_text="Loading")).to_be_visible()
    expect(memory).not_to_contain_text("Nothing remembered yet")
    held.release()
    expect(memory).to_contain_text("Nothing remembered yet")
    expect(memory.get_by_role("status").filter(has_text="Loading")).to_have_count(0)


@pytest.mark.spec("UX-038")
def test_an_action_in_progress_shows_it_and_is_not_started_twice(page: Page, server: Server, member: Account) -> None:
    create_task(server, login(server, member), "Summarize the news.", name="Morning review")
    sign_in(page, member)

    _settings(page, "Yours", "Memory")
    memory = page.get_by_role("region", name="Memory")
    memory.get_by_role("button", name="Add").click()
    dialog = page.get_by_role("dialog", name="Add to memory")
    dialog.get_by_label("Text").fill("Lives in Bologna.")
    held = Held(page, re.compile(r"/v1/me/memory/items$"), "POST")
    save = dialog.get_by_role("button", name="Save")
    save.click()
    expect(save).to_have_attribute("aria-busy", "true")
    expect(save).to_be_disabled()
    save.click(force=True)
    held.release()
    expect(dialog).to_be_hidden()
    items = memory.get_by_role("list", name="Memory items").get_by_role("listitem")
    expect(items).to_have_count(1)
    assert len(held.routes) == 1

    held = Held(page, re.compile(r"/v1/me/memory/items/[^/]+$"), "DELETE")
    delete = items.first.get_by_role("button", name="Delete")
    delete.click()
    expect(delete).to_have_attribute("aria-busy", "true")
    expect(delete).to_be_disabled()
    delete.click(force=True)
    held.release()
    expect(memory).to_contain_text("Nothing remembered yet")
    expect(page.get_by_role("alert")).to_have_count(0)
    assert len(held.routes) == 1

    _settings(page, "Yours", "Tasks")
    task = page.get_by_role("region", name="Tasks").get_by_role("listitem").filter(has_text="Morning review")
    held = Held(page, re.compile(r"/v1/tasks/[^/]+/fire$"), "POST")
    run = task.get_by_role("button", name="Run Morning review now")
    run.click()
    expect(run).to_have_attribute("aria-busy", "true")
    expect(run).to_be_disabled()
    run.click(force=True)
    held.release()
    expect(run).not_to_have_attribute("aria-busy", "true")
    assert len(held.routes) == 1
