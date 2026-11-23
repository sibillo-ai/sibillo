"""The interface in every language (I18N-002, I18N-004, I18N-005, I18N-006, ADR-0135).

The tests find elements by the texts of the translation resources, so that
they follow the translations rather than copy them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.support.accounts import Account
from tests.support.database import ROOT
from tests.web.conftest import accessibility_violations, sign_in

LOCALES = ROOT / "src" / "web" / "src" / "locales"
REQUEST = {"X-Sibillo-Request": "1"}


def _text(tag: str, key: str) -> str:
    tree: object = json.loads((LOCALES / f"{tag}.json").read_text())
    for part in key.split("."):
        tree = cast(dict[str, object], tree)[part]
    assert isinstance(tree, str)
    return tree


def _document(page: Page) -> tuple[str, str]:
    lang, direction = page.evaluate("[document.documentElement.lang, document.documentElement.dir]")
    return lang, direction


def _set_language(page: Page, language: str | None) -> None:
    settings = page.request.get("/v1/me/settings")
    assert settings.ok, settings.text()
    # The built-in instructions are only read, never sent back.
    body = {key: value for key, value in settings.json().items() if key != "built_in_base_instructions"}
    body["language"] = language
    response = page.request.put("/v1/me/settings", data=body, headers=REQUEST)
    assert response.ok, response.text()


@contextmanager
def _browser_page(browser: Browser, web_origin: str, locale: str) -> Generator[Page]:
    """A page of a browser whose language is `locale`."""
    context = browser.new_context(base_url=web_origin, locale=locale)
    page = context.new_page()
    page.set_default_timeout(15_000)
    try:
        yield page
    finally:
        context.close()


@pytest.mark.spec("I18N-004", "I18N-005")
def test_before_sign_in_the_browsers_language_decides(browser: Browser, web_origin: str) -> None:
    with _browser_page(browser, web_origin, "it-IT") as page:
        _italian_sign_in(page)


def _italian_sign_in(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_role("button", name=_text("it", "signIn.submit"))).to_be_visible()
    expect(page.get_by_label(_text("it", "signIn.username"))).to_be_visible()
    assert _document(page) == ("it", "ltr")
    assert accessibility_violations(page) == []


@pytest.mark.spec("I18N-004", "I18N-005")
def test_a_right_to_left_language_mirrors_the_page(browser: Browser, web_origin: str, member: Account) -> None:
    with _browser_page(browser, web_origin, "ar-EG") as page:
        _arabic_session(page, member)


def _arabic_session(page: Page, member: Account) -> None:
    page.goto("/")
    assert _document(page) == ("ar", "rtl")
    sign_in_button = page.get_by_role("button", name=_text("ar", "signIn.submit"))
    expect(sign_in_button).to_be_visible()
    page.get_by_label(_text("ar", "signIn.username")).fill(member.username)
    page.get_by_label(_text("ar", "signIn.password")).fill(member.password)
    sign_in_button.click()
    message = page.get_by_label(_text("ar", "composer.label"))
    message.wait_for()
    # Wide enough for the conversation list beside the chat: it is on the right, where the reader starts.
    page.set_viewport_size({"width": 1280, "height": 800})
    navigation, main = page.get_by_role("navigation").first.bounding_box(), page.get_by_role("main").bounding_box()
    assert navigation is not None
    assert main is not None
    assert navigation["x"] > main["x"]
    # What the user writes takes its own direction, whatever the interface's.
    mark = f"Hello there {uuid4().hex[:8]}"
    message.fill(mark)
    page.get_by_role("button", name=_text("ar", "composer.send")).click()
    written = page.get_by_role("main").get_by_text(mark, exact=True).first
    expect(written).to_be_visible()
    assert written.evaluate("(element) => element.matches(':dir(ltr)')")
    assert accessibility_violations(page) == []


@pytest.mark.spec("I18N-002", "I18N-004", "I18N-005")
def test_the_preferred_language_changes_the_interface_at_once(page: Page, member: Account) -> None:
    sign_in(page, member)
    page.get_by_role("link", name="Settings").click()
    language = page.get_by_role("region", name="Assistant").get_by_label("Language", exact=True)
    # A translation a person has reviewed is named only; one a model made says so.
    expect(language.locator("option[value='it']")).to_have_text(re.compile(r"^\s*Italiano — Italian\s*$"))
    expect(language.locator("option[value='de']")).to_have_text(re.compile(r"^\s*Deutsch — German\s*\S"))
    assert accessibility_violations(page) == []
    page.evaluate("window.__notReloaded = true")
    language.select_option("ar")
    # At once, without reloading.
    expect(page.get_by_role("link", name=_text("ar", "shell.settings"))).to_be_visible()
    assert _document(page) == ("ar", "rtl")
    assert page.evaluate("window.__notReloaded === true")
    assert accessibility_violations(page) == []
    # Without a preferred language, the browser's decides again.
    page.get_by_role("region", name=_text("ar", "assistant.title")).get_by_label(
        _text("ar", "assistant.language"), exact=True
    ).select_option("")
    expect(page.get_by_role("link", name="Settings")).to_be_visible()
    assert _document(page) == ("en", "ltr")
    assert page.evaluate("window.__notReloaded === true")


@pytest.mark.spec("I18N-006")
def test_dates_follow_the_interface_language(page: Page, member: Account) -> None:
    sign_in(page, member)
    text = f"Likes figs {uuid4().hex[:8]}"
    created = page.request.post("/v1/me/memory/items", data={"text": text}, headers=REQUEST)
    assert created.ok, created.text()
    _set_language(page, "it")
    page.goto("/settings?section=memory")
    item = page.get_by_role("listitem").filter(has_text=text)
    today = page.evaluate("new Intl.DateTimeFormat('it', { dateStyle: 'medium' }).format(new Date())")
    expect(item).to_contain_text(today)
    assert _document(page) == ("it", "ltr")
