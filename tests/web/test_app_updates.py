"""A new version of the app takes over (UX-040, ADR-0112).

A test deploys a new version as a deployment does for the browser: the
service worker the server serves changes. Only its bytes change, so the new
worker has nothing new to fetch, and the file is put back afterwards.

Chromium in tests does not hide a page; a test says the app went out of
view, or came back, as the browser says it: by the page's visibility and
its `visibilitychange` event.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.web.conftest import accessibility_violations, sign_in

# Waits until the service worker controls the page, and marks the page, which a reload forgets.
CONTROLLED = """async () => {
  await navigator.serviceWorker.ready;
  if (!navigator.serviceWorker.controller) {
    const container = navigator.serviceWorker;
    await new Promise((resolve) => container.addEventListener("controllerchange", resolve, { once: true }));
  }
  window.oldVersion = true;
}"""
# The app goes out of view, or comes back into it.
SEEN = """(state) => {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  Object.defineProperty(document, "hidden", { value: state === "hidden", configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}"""
READY = "A new version of Sibillo is ready"


@pytest.fixture
def deploy(web_build: Path) -> Iterator[Callable[[], None]]:
    """Deploys a new version, once the old one runs: the service worker the server serves changes."""
    worker = web_build / "sw.js"
    old = worker.read_text()

    def new_version() -> None:
        worker.write_text(f"{old}\n// a new version\n")

    try:
        yield new_version
    finally:
        worker.write_text(old)


def _old_version(page: Page) -> bool:
    return page.evaluate("window.oldVersion === true")


@pytest.mark.spec("UX-040")
def test_a_first_visit_changes_nothing(page: Page, member: Account) -> None:
    sign_in(page, member)
    page.evaluate(CONTROLLED)
    page.wait_for_timeout(500)
    assert _old_version(page)
    expect(page.get_by_text(READY)).to_have_count(0)


@pytest.mark.spec("UX-040")
def test_out_of_view_with_nothing_typed_the_new_version_loads(
    page: Page, member: Account, deploy: Callable[[], None]
) -> None:
    sign_in(page, member)
    page.evaluate(CONTROLLED)
    deploy()
    # The app goes out of view: it looks for a new version and, finding one, loads it.
    with page.expect_event("load", timeout=20_000):
        page.evaluate(SEEN, "hidden")
    page.get_by_label("Message").wait_for()
    assert not _old_version(page)
    expect(page.get_by_text(READY)).to_have_count(0)


@pytest.mark.spec("UX-040")
def test_with_text_typed_the_new_version_waits_and_says_it_is_ready(
    page: Page, member: Account, deploy: Callable[[], None]
) -> None:
    sign_in(page, member)
    page.evaluate(CONTROLLED)
    page.get_by_label("Message").fill("half a thought")
    deploy()
    # The app comes back into view: it finds the new version, and keeps what was typed.
    page.evaluate(SEEN, "visible")
    expect(page.get_by_text(READY)).to_be_visible(timeout=20_000)
    assert _old_version(page)
    assert accessibility_violations(page) == []
    # Out of view, the typed text still keeps the page as it is.
    page.evaluate(SEEN, "hidden")
    page.wait_for_timeout(1_000)
    assert _old_version(page)
    expect(page.get_by_label("Message")).to_have_value("half a thought")
    # The user loads it.
    page.evaluate(SEEN, "visible")
    with page.expect_event("load", timeout=20_000):
        page.get_by_role("button", name="Load it").click()
    page.get_by_label("Message").wait_for()
    assert not _old_version(page)


@pytest.mark.spec("UX-040")
def test_an_open_app_looks_for_a_new_version_every_hour(
    page: Page, member: Account, deploy: Callable[[], None]
) -> None:
    page.clock.install()
    sign_in(page, member)
    page.evaluate(CONTROLLED)
    page.get_by_label("Message").fill("still writing")
    deploy()
    page.clock.run_for(60 * 60 * 1000)
    expect(page.get_by_text(READY)).to_be_visible(timeout=20_000)
    expect(page.get_by_label("Message")).to_have_value("still writing")
