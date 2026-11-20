"""The top bar of every page and the way back on a phone (UX-039, ADR-0111).

The model the tests serve answers `Echo: <message>` (tests/support/model.py).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, FloatRect, Locator, Page, ViewportSize, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in

PHONE: ViewportSize = {"width": 390, "height": 844}
# The top bar is 56 px high, under the edge of the screen.
TOP_BAR = 64


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _box(locator: Locator) -> FloatRect:
    box = locator.bounding_box()
    assert box is not None, "not laid out"
    return box


def _in_top_bar(locator: Locator) -> bool:
    box = _box(locator)
    return box["y"] + box["height"] <= TOP_BAR


def _model_button(page: Page) -> Locator:
    return page.get_by_role("button", name=re.compile("test-model"))


@pytest.fixture
def phone(browser: Browser, web_origin: str) -> Iterator[Page]:
    context = browser.new_context(base_url=web_origin, viewport=PHONE, has_touch=True, is_mobile=True)
    try:
        yield context.new_page()
    finally:
        context.close()


@pytest.mark.spec("UX-039", "UX-015")
def test_a_new_chat_chooses_its_model_with_the_greeting(page: Page, member: Account) -> None:
    sign_in(page, member)
    model = _model_button(page)
    expect(model).to_be_visible()
    # Not in the message box: between the greeting and the message box.
    expect(page.locator("form").get_by_role("button", name=re.compile("test-model"))).to_have_count(0)
    greeting = _box(page.get_by_role("heading", level=1))
    box = _box(page.get_by_label("Message"))
    assert greeting["y"] < _box(model)["y"] < box["y"]
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-039", "UX-015", "UX-008")
def test_a_conversations_model_is_in_its_top_bar(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, "the model on top")
    expect(page.get_by_role("main")).to_contain_text("Echo: the model on top", timeout=30_000)
    model = _model_button(page)
    expect(model).to_be_visible()
    expect(page.locator("form").get_by_role("button", name=re.compile("test-model"))).to_have_count(0)
    assert _in_top_bar(model)
    # The bar keeps the conversation's cost and its files beside it.
    assert _in_top_bar(page.get_by_text("This conversation", exact=True))
    assert _in_top_bar(page.get_by_role("button", name="Files"))
    # It still chooses the model.
    model.click()
    expect(page.get_by_role("dialog", name="Choose a model")).to_be_visible()
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-039", "UX-015", "UX-008")
def test_on_a_phone_the_conversations_top_bar_holds_its_model(
    phone: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(phone, member)
    _send(phone, "the model on a phone")
    expect(phone.get_by_role("main")).to_contain_text("Echo: the model on a phone", timeout=30_000)
    for control in (
        phone.get_by_role("button", name="Open the conversation list"),
        _model_button(phone),
        phone.get_by_role("button", name="Files"),
        phone.get_by_text("This conversation", exact=True),
    ):
        expect(control).to_be_visible()
        assert _in_top_bar(control)
    expect(phone.locator("form").get_by_role("button", name=re.compile("test-model"))).to_have_count(0)
    assert accessibility_violations(phone) == []


@pytest.mark.spec("UX-039", "CNV-011")
def test_on_a_phone_the_temporary_chat_is_at_the_top_right(phone: Page, member: Account) -> None:
    sign_in(phone, member)
    menu = phone.get_by_role("button", name="Open the conversation list")
    temporary = phone.get_by_role("button", name="Temporary chat")
    assert _in_top_bar(menu)
    assert _in_top_bar(temporary)
    # One bar: the two sit on the same line, the temporary chat at its right end.
    assert abs(_box(menu)["y"] - _box(temporary)["y"]) < 8
    right = _box(temporary)
    assert right["x"] + right["width"] >= PHONE["width"] - 24


@pytest.mark.spec("UX-039")
def test_on_a_phone_the_conversation_list_takes_the_whole_screen(phone: Page, member: Account) -> None:
    sign_in(phone, member)
    phone.get_by_role("button", name="Open the conversation list").click()
    conversations = phone.get_by_role("navigation", name="Conversations")
    expect(conversations).to_be_visible()
    box = _box(conversations)
    assert box["x"] <= 0
    assert box["width"] >= PHONE["width"]
    assert accessibility_violations(phone) == []


@pytest.mark.spec("UX-039")
def test_on_a_phone_the_devices_back_closes_the_conversation_list(
    phone: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(phone, member)
    _send(phone, "behind the list")
    expect(phone.get_by_role("main")).to_contain_text("Echo: behind the list", timeout=30_000)
    conversation = phone.url
    phone.get_by_role("button", name="Open the conversation list").click()
    expect(phone.get_by_role("link", name="New chat")).to_be_visible()
    phone.go_back()
    expect(phone.get_by_role("link", name="New chat")).to_be_hidden()
    assert phone.url == conversation
    expect(phone.get_by_role("main")).to_contain_text("Echo: behind the list")


@pytest.mark.spec("UX-039", "UX-015")
def test_on_a_phone_back_leads_from_a_section_to_the_settings_and_to_the_list(phone: Page, member: Account) -> None:
    sign_in(phone, member)
    phone.get_by_role("button", name="Open the conversation list").click()
    phone.get_by_role("link", name="Settings").click()
    sections = phone.get_by_role("navigation", name="Settings sections")
    expect(sections).to_be_visible()
    # The bar says where the user is, and Back is in it.
    assert _in_top_bar(phone.get_by_role("main").get_by_text("Settings", exact=True).first)
    expect(phone.get_by_role("button", name="Back to the conversations")).to_be_visible()

    # A section names itself in the bar; the bar's Back returns to the sections.
    sections.get_by_role("button", name="Assistant").click()
    expect(sections).to_be_hidden()
    assert _in_top_bar(phone.get_by_role("main").get_by_text("Assistant", exact=True).first)
    phone.get_by_role("button", name="Back to the settings").click()
    expect(sections).to_be_visible()

    # The device's own Back does the same.
    sections.get_by_role("button", name="Assistant").click()
    expect(sections).to_be_hidden()
    phone.go_back()
    expect(sections).to_be_visible()
    assert accessibility_violations(phone) == []

    # From the sections, Back leads to the conversation list.
    phone.get_by_role("button", name="Back to the conversations").click()
    expect(phone.get_by_role("link", name="New chat")).to_be_visible()


@pytest.mark.spec("UX-039")
def test_on_a_phone_the_devices_back_leads_from_the_settings_to_the_list(phone: Page, member: Account) -> None:
    sign_in(phone, member)
    phone.get_by_role("button", name="Open the conversation list").click()
    phone.get_by_role("link", name="Settings").click()
    expect(phone.get_by_role("navigation", name="Settings sections")).to_be_visible()
    phone.go_back()
    expect(phone.get_by_role("link", name="New chat")).to_be_visible()


@pytest.mark.spec("UX-039")
def test_settings_opened_by_their_address_lead_back_to_the_list(phone: Page, member: Account) -> None:
    sign_in(phone, member)
    phone.goto("/settings?section=assistant")
    phone.get_by_role("button", name="Back to the settings").click()
    expect(phone.get_by_role("navigation", name="Settings sections")).to_be_visible()
    phone.get_by_role("button", name="Back to the conversations").click()
    expect(phone.get_by_role("link", name="New chat")).to_be_visible()
