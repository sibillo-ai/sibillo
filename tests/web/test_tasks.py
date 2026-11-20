"""Tasks in the web client (UX-031, TSK-001 to TSK-009, ADR-0106).

Tasks are among the user's own settings. Tests fire a task by moving its
schedule's next firing into the past (tests/support/tasks.py); the model the
tests serve answers its instructions.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, login
from tests.support.database import Database
from tests.support.server import Server
from tests.support.tasks import (
    create_task,
    fire_schedule,
    open_grant,
    schedule,
    trigger_of,
    wait_for_conversations,
)
from tests.web.conftest import accessibility_violations, sign_in


def _tasks_page(page: Page) -> None:
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Yours").get_by_role("button", name="Tasks").click()


@pytest.mark.spec("UX-031", "TSK-001", "TSK-003", "UX-007")
def test_a_user_creates_a_scheduled_task_and_sees_when_it_fires(page: Page, member: Account) -> None:
    sign_in(page, member)
    _tasks_page(page)
    tasks = page.get_by_role("region", name="Tasks")
    expect(tasks).to_contain_text("No tasks yet")
    assert accessibility_violations(page) == []

    tasks.get_by_role("button", name="New task").click()
    dialog = page.get_by_role("dialog", name="New task")
    dialog.get_by_label("Name").fill("Morning review")
    dialog.get_by_label("Instructions").fill("Summarize the news of the day.")
    dialog.get_by_label("Time zone").fill("Europe/Rome")
    dialog.get_by_role("button", name="Add a schedule").click()
    dialog.get_by_label("Schedule").fill("0 7 * * 1-5")
    # The schedule is said in words before it is saved.
    expect(dialog).to_contain_text("At 07:00, Monday to Friday")
    dialog.get_by_role("group", name="Grants").get_by_role("checkbox", name="Search the web").check()
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()

    items = tasks.get_by_role("list", name="Your tasks").get_by_role("listitem")
    expect(items).to_have_count(1)
    expect(items.first).to_contain_text("Morning review")
    expect(items.first).to_contain_text("At 07:00, Monday to Friday")
    expect(items.first).to_contain_text("Next:")

    # Paused, it says so; resumed, it fires again.
    items.first.get_by_role("switch", name="Active").click()
    expect(items.first).to_contain_text("Paused")
    items.first.get_by_role("switch", name="Active").click()
    expect(items.first).not_to_contain_text("Paused")


@pytest.mark.spec("UX-031", "TSK-007")
def test_a_webhook_address_is_shown_once_and_can_be_replaced(page: Page, member: Account) -> None:
    sign_in(page, member)
    _tasks_page(page)
    tasks = page.get_by_role("region", name="Tasks")
    tasks.get_by_role("button", name="New task").click()
    dialog = page.get_by_role("dialog", name="New task")
    dialog.get_by_label("Name").fill("Front door")
    dialog.get_by_label("Instructions").fill("Tell me who is at the door.")
    dialog.get_by_role("button", name="Add a webhook").click()
    dialog.get_by_role("button", name="Save").click()

    shown = page.get_by_role("dialog", name="Webhook address")
    expect(shown).to_contain_text("/v1/hooks/")
    expect(shown).to_contain_text("shown only once")
    address = shown.get_by_label("Address").input_value()
    shown.get_by_role("button", name="Done").click()

    item = tasks.get_by_role("list", name="Your tasks").get_by_role("listitem").first
    expect(item).not_to_contain_text(address)
    item.get_by_role("button", name="Replace the webhook address").click()
    confirm = page.get_by_role("alertdialog")
    expect(confirm).to_contain_text("stops working")
    confirm.get_by_role("button", name="Replace").click()
    replaced = page.get_by_role("dialog", name="Webhook address")
    expect(replaced).to_contain_text("/v1/hooks/")
    assert replaced.get_by_label("Address").input_value() != address


@pytest.mark.spec("UX-031", "TSK-005")
def test_grants_that_complete_the_lethal_trifecta_are_shown_with_what_to_remove(page: Page, member: Account) -> None:
    sign_in(page, member)
    _tasks_page(page)
    page.get_by_role("region", name="Tasks").get_by_role("button", name="New task").click()
    dialog = page.get_by_role("dialog", name="New task")
    dialog.get_by_label("Name").fill("Risky")
    dialog.get_by_label("Instructions").fill("Read my files and search the web.")
    dialog.get_by_role("button", name="Add a schedule").click()
    dialog.get_by_label("Schedule").fill("0 7 * * *")
    grants = dialog.get_by_role("group", name="Grants")
    grants.get_by_role("checkbox", name="Search the web").check()
    grants.get_by_role("checkbox", name="Read files").check()
    dialog.get_by_role("button", name="Save").click()
    alert = dialog.get_by_role("alert")
    expect(alert).to_contain_text("could send your data out")
    expect(alert).to_contain_text("Search the web")
    expect(alert).to_contain_text("Read files")
    expect(dialog).to_be_visible()


@pytest.mark.spec("UX-031", "TSK-002", "TSK-004")
def test_a_task_lists_its_conversations_which_show_its_name(
    page: Page, database: Database, server: Server, member: Account
) -> None:
    token = login(server, member)
    task = create_task(
        server,
        token,
        'chain:web_search {"query": "first"} >>> web_search {"query": "second"}',
        name="Evening digest",
        triggers=[schedule()],
    )
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    wait_for_conversations(server, token, task["id"])
    granted = create_task(server, token, "Say hello.", name="Granted", grants=[open_grant("web_search")])
    assert granted["grant_check"]["passes"] is True

    sign_in(page, member)
    _tasks_page(page)
    item = page.get_by_role("region", name="Tasks").get_by_role("listitem").filter(has_text="Evening digest")
    item.get_by_role("link", name="Evening digest").click()
    started = page.get_by_role("list", name="Conversations of this task").get_by_role("listitem")
    expect(started).to_have_count(1)
    expect(started.first).to_contain_text("Completed")
    assert accessibility_violations(page) == []

    started.first.get_by_role("link").click()
    expect(page.get_by_role("main")).to_contain_text("Evening digest")
    # The call no grant covered is shown as such.
    expect(page.get_by_role("main")).to_contain_text("Not allowed to this task")
    conversations = page.get_by_role("navigation", name="Conversations")
    expect(conversations).to_contain_text("Evening digest")


@pytest.mark.spec("UX-031", "TSK-001")
def test_a_user_changes_a_task_from_its_entry(page: Page, server: Server, member: Account) -> None:
    token = login(server, member)
    create_task(server, token, "Summarize the news.", name="Morning review")
    sign_in(page, member)
    _tasks_page(page)
    item = page.get_by_role("region", name="Tasks").get_by_role("list", name="Your tasks").get_by_role("listitem").first
    item.get_by_role("button", name="Edit Morning review").click()
    dialog = page.get_by_role("dialog", name="Edit task")
    expect(dialog.get_by_label("Instructions")).to_have_value("Summarize the news.")
    dialog.get_by_label("Name").fill("Evening review")
    dialog.get_by_label("Instructions").fill("Summarize the day.")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()
    expect(item).to_contain_text("Evening review")


@pytest.mark.spec("UX-031", "UX-032", "TSK-011")
def test_a_task_run_now_appears_as_running_and_then_done(page: Page, server: Server, member: Account) -> None:
    token = login(server, member)
    create_task(server, token, "slow:8", name="Slow digest")
    sign_in(page, member)
    _tasks_page(page)
    item = page.get_by_role("region", name="Tasks").get_by_role("listitem").filter(has_text="Slow digest")
    item.get_by_role("button", name="Run Slow digest now").click()
    # Without reloading, the conversation appears in the list, marked as running, until its run ends.
    conversations = page.get_by_role("navigation", name="Conversations")
    running = conversations.get_by_role("listitem").filter(has_text="Slow digest")
    expect(running).to_contain_text("Running", timeout=10_000)
    expect(running).not_to_contain_text("Running", timeout=20_000)
    item.get_by_role("link", name="Slow digest").click()
    started = page.get_by_role("list", name="Conversations of this task").get_by_role("listitem")
    expect(started).to_have_count(1)
    expect(started.first).to_contain_text("Completed")


@pytest.mark.spec("UX-033", "UX-004")
def test_notifications_that_are_off_show_a_sign_until_dismissed(page: Page, member: Account) -> None:
    sign_in(page, member)
    sign = page.get_by_role("region", name="Notifications are off")
    expect(sign).to_be_visible()
    expect(sign.get_by_role("button", name="Turn on")).to_be_visible()
    assert accessibility_violations(page) == []
    sign.get_by_role("button", name="Hide").click()
    expect(sign).to_be_hidden()
    page.reload()
    expect(page.get_by_role("link", name="Settings")).to_be_visible()
    expect(page.get_by_role("region", name="Notifications are off")).to_be_hidden()
