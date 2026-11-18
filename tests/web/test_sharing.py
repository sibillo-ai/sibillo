"""Sharing into the app from other apps (UX-006, ADR-0102).

Chromium in tests has no share sheet: a test shares as the system does, by
submitting from a page of the app, once its service worker controls it, a
form that posts to `/share` (test-harness.md, "Web").
"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.web.conftest import accessibility_violations, sign_in

# Submits a share as the system's share sheet does. The form is submitted after the script returns, since
# the navigation it starts ends the page's scripts.
SHARE = """async ({ fields, files }) => {
  await navigator.serviceWorker.ready;
  if (!navigator.serviceWorker.controller) {
    const container = navigator.serviceWorker;
    await new Promise((resolve) => container.addEventListener("controllerchange", resolve, { once: true }));
  }
  const form = document.createElement("form");
  form.method = "post";
  form.action = "/share";
  form.enctype = "multipart/form-data";
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.append(input);
  }
  const picker = document.createElement("input");
  picker.type = "file";
  picker.name = "files";
  picker.multiple = true;
  const transfer = new DataTransfer();
  for (const file of files) transfer.items.add(new File([file.content], file.name, { type: file.type }));
  picker.files = transfer.files;
  form.append(picker);
  form.hidden = true;
  document.body.append(form);
  setTimeout(() => form.submit(), 0);
}"""
RECIPE = {"title": "A recipe", "text": "Try this one", "url": "https://example.org/recipe"}
RECIPE_MESSAGE = "A recipe\n\nTry this one\n\nhttps://example.org/recipe"
NOTE = {"name": "note.txt", "type": "text/plain", "content": "basil, tomatoes, garlic"}


def _share(page: Page, fields: dict[str, str], files: list[dict[str, str]]) -> None:
    page.evaluate(SHARE, {"fields": fields, "files": files})
    # The service worker keeps the share and opens the app on it.
    page.wait_for_url(re.compile(r"/(\?shared=1)?$"))


def _conversations(page: Page) -> list[dict[str, Any]]:
    response = page.request.get("/v1/conversations")
    assert response.status == 200, response.text()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _uploads(page: Page, conversation_id: str) -> list[str]:
    response = page.request.get(f"/v1/conversations/{conversation_id}/workspace/entries", params={"path": "uploads"})
    assert response.status == 200, response.text()
    return [entry["name"] for entry in response.json()["entries"]]


def _attached(page: Page, name: str) -> None:
    """Waits until the attachment `name` has uploaded."""
    chip = page.get_by_role("list", name="Attachments").get_by_role("listitem").filter(has_text=name)
    expect(chip).to_be_visible(timeout=30_000)
    expect(chip).not_to_contain_text("Uploading", timeout=30_000)
    expect(chip).not_to_contain_text("Saving", timeout=30_000)


@pytest.mark.spec("UX-006", "CNV-017", "UX-007")
def test_a_share_opens_a_new_chat_with_its_text_and_files_and_sends_nothing(page: Page, member: Account) -> None:
    sign_in(page, member)
    _share(page, RECIPE, [NOTE])
    box = page.get_by_label("Message")
    expect(box).to_have_value(RECIPE_MESSAGE)
    # Where the content came from is said above the message box.
    expect(page.get_by_text("Shared from another app", exact=False)).to_be_visible()
    _attached(page, "note.txt")
    # The share is read once: the address no longer asks for it.
    page.wait_for_url(re.compile(r"/$"))
    assert accessibility_violations(page) == []
    # The attachment made the conversation and uploaded into its workspace; nothing was sent.
    conversations = _conversations(page)
    assert len(conversations) == 1
    conversation_id = conversations[0]["id"]
    assert _uploads(page, conversation_id) == ["note.txt"]
    messages = page.request.get(f"/v1/conversations/{conversation_id}/messages")
    assert messages.status == 200, messages.text()
    assert messages.json()["items"] == []
    # The user sends it, with its attachment.
    box.fill("what can I cook with this")
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_role("main")).to_contain_text("Echo: what can I cook with this", timeout=30_000)
    expect(page.get_by_role("main").get_by_role("button", name=re.compile("note.txt"))).to_be_visible()


@pytest.mark.spec("UX-006")
def test_a_share_is_offered_once(page: Page, member: Account) -> None:
    sign_in(page, member)
    _share(page, {"title": "", "text": "only once", "url": ""}, [])
    expect(page.get_by_label("Message")).to_have_value("only once")
    page.goto("/?shared=1")
    expect(page.get_by_role("alert")).to_contain_text("Nothing arrived")
    expect(page.get_by_label("Message")).to_have_value("")


@pytest.mark.spec("UX-006")
def test_a_share_waits_while_the_user_signs_in(page: Page, member: Account) -> None:
    page.goto("/")
    page.get_by_label("Username").wait_for()
    _share(page, RECIPE, [NOTE])
    # Nothing is offered on the sign-in screen; it is once the user has signed in.
    page.get_by_label("Username").fill(member.username)
    page.get_by_label("Password").fill(member.password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_label("Message")).to_have_value(RECIPE_MESSAGE)
    _attached(page, "note.txt")


@pytest.mark.spec("UX-006")
def test_a_share_older_than_an_hour_is_not_offered(page: Page, member: Account) -> None:
    page.goto("/")
    page.get_by_label("Username").wait_for()
    _share(page, RECIPE, [NOTE])
    page.get_by_label("Username").wait_for()
    # The user signs in more than an hour later, as someone else might on a shared device.
    page.clock.set_system_time(time.time() + 61 * 60)
    page.get_by_label("Username").fill(member.username)
    page.get_by_label("Password").fill(member.password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_contain_text("Nothing arrived")
    expect(page.get_by_label("Message")).to_have_value("")
    assert _conversations(page) == []


@pytest.mark.spec("UX-006", "UX-014", "UX-007")
def test_when_nothing_arrives_the_chat_says_so_and_what_to_do(page: Page, member: Account) -> None:
    sign_in(page, member)
    page.goto("/?shared=1")
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Nothing arrived")
    expect(alert).to_contain_text("share it again")
    expect(page.get_by_text("Shared from another app", exact=False)).to_have_count(0)
    assert accessibility_violations(page) == []
