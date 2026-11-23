"""Approvals, tool activity and tool permissions in the web client (UX-022, UX-023, CNV-013, AGT-034, ADR-0090,
ADR-0113).

The model the tests serve calls the tool named in a message `tool:<name> <arguments>`, then answers
`Tool said: <result>` (tests/support/model.py). A search needs internet access, which a chat has only
once its user gives it.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, create_account
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _search(query: str) -> str:
    return f"tool:web_search {json.dumps({'query': query})}"


def _searched(page: Page, query: str) -> None:
    """Search, in a chat that has internet access: the answer arrives without asking."""
    _send(page, _search(query))
    expect(page.get_by_role("main")).to_contain_text(f"Result 0 about {query}", timeout=30_000)


@pytest.mark.spec("UX-022", "UX-023", "AGT-034", "AGT-006", "UX-007")
def test_internet_access_is_asked_shown_in_full_and_remembered_in_the_chat(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, _search(f"second {mark}"))
    approval = page.get_by_role("region", name="Approval needed")
    expect(approval).to_be_visible(timeout=30_000)
    # What internet access lets the assistant do, what could go out, and the search that waits for it.
    expect(approval).to_contain_text("Access the internet")
    expect(approval).to_contain_text("could be sent out")
    expect(approval).to_contain_text("Search the web")
    expect(approval).to_contain_text(f"second {mark}")
    expect(approval).to_contain_text("search service")
    expect(approval).not_to_contain_text("trying to steer")
    expect(approval).to_contain_text("Denied in")
    # In place of the message box, with Deny first; never only once.
    expect(page.get_by_label("Message")).to_have_count(0)
    buttons = approval.get_by_role("button")
    expect(buttons).to_have_text(["Deny", "Allow for this turn", "Allow in this chat"])
    assert accessibility_violations(page) == []
    # Opened again later, it still asks.
    page.reload()
    expect(approval).to_be_visible(timeout=30_000)
    approval.get_by_role("button", name="Allow in this chat").click()
    main = page.get_by_role("main")
    expect(main).to_contain_text(f"Result 0 about second {mark}", timeout=30_000)
    expect(page.get_by_label("Message")).to_be_visible()
    # The call says how it was decided.
    expect(main).to_contain_text("Allowed in this chat")
    # Later searches in this chat do not ask.
    _searched(page, f"third {mark}")
    # The chat's settings show what was allowed, and its user withdraws it.
    page.get_by_role("button", name="Chat settings").click()
    dialog = page.get_by_role("dialog", name="Chat settings")
    allowed = dialog.get_by_role("region", name="Allowed in this chat")
    expect(allowed).to_contain_text("Internet access")
    allowed.get_by_role("button", name="Withdraw").click()
    expect(allowed).to_contain_text("Nothing")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Save").click()
    _send(page, _search(f"fourth {mark}"))
    expect(approval).to_be_visible(timeout=30_000)
    # The chat now holds content from elsewhere: the request says so.
    expect(approval).to_contain_text("trying to steer")
    approval.get_by_role("button", name="Deny").click()
    expect(main).to_contain_text("Denied", timeout=30_000)
    expect(page.get_by_label("Message")).to_be_visible()


@pytest.mark.spec("UX-023", "AGT-008", "UX-007")
def test_the_activity_page_lists_every_tool_call(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, _search(f"approved {mark}"))
    page.get_by_role("region", name="Approval needed").get_by_role("button", name="Allow for this turn").click()
    expect(page.get_by_role("main")).to_contain_text(f"Result 0 about approved {mark}", timeout=30_000)
    # Once the turn's answer is in, a command, which asks nothing.
    expect(page.get_by_label("Message")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("button", name="Send")).to_be_visible(timeout=30_000)
    _send(page, f"run:echo listed {mark}")
    expect(page.locator("summary", has_text="Sandbox command")).to_be_visible(timeout=30_000)
    page.get_by_role("link", name="Settings").click()
    page.get_by_role("navigation", name="Settings sections").get_by_role("button", name="Activity").click()
    activity = page.get_by_role("region", name="Activity")
    calls = activity.get_by_role("list", name="Tool calls").get_by_role("listitem")
    expect(calls).to_have_count(2, timeout=30_000)
    # Newest first, each with its outcome.
    expect(calls.first).to_contain_text("No approval needed")
    expect(calls.last).to_contain_text("Search the web")
    expect(calls.last).to_contain_text("Allowed for this turn")
    # Content-free: the query is not there.
    expect(activity).not_to_contain_text(mark)
    assert accessibility_violations(page) == []
    activity.get_by_label("Tool", exact=True).select_option(label="Read web pages")
    expect(activity).to_contain_text("No tool calls")
    activity.get_by_label("Tool", exact=True).select_option(label="All tools")
    calls.last.get_by_role("link").click()
    expect(page.get_by_role("main")).to_contain_text(f"Result 0 about approved {mark}", timeout=30_000)


@pytest.mark.spec("UX-023", "AGT-002", "CNV-013", "UX-007")
def test_a_household_admin_sets_what_each_member_may_use(
    page: Page, database: Database, admin: Account, default_model: HarnessModel
) -> None:
    member = create_account(database, admin.tenant_id)
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Household").get_by_role("button", name="Tool permissions").click()
    permissions = page.get_by_role("region", name="Tool permissions")
    permissions.get_by_label("User").select_option(label=member.username)
    expect(permissions.get_by_label("Search the web", exact=True)).to_have_value("default")
    permissions.get_by_label("Search the web", exact=True).select_option(label="Deny")
    permissions.get_by_label("Sends data out", exact=True).select_option(label="Ask")
    # What applies to each tool, and why.
    expect(permissions.get_by_role("row", name="Read web pages")).to_contain_text("Ask")
    assert accessibility_violations(page) == []
    permissions.get_by_role("button", name="Save permissions").click()
    expect(permissions).to_contain_text("Saved")
    # The member finds it switched off, and why.
    page.context.clear_cookies()
    sign_in(page, member)
    page.get_by_role("link", name="Settings").click()
    switch = page.get_by_role("main").get_by_role("switch", name="Search the web", exact=True)
    expect(switch).not_to_be_checked()
    expect(switch).to_be_disabled()
    expect(page.get_by_role("main")).to_contain_text("Turned off by your household's admin")
