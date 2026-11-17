"""Notifications in the web client (UX-004, ADR-0039, ADR-0101).

Chromium in tests reaches no push service: the page's `PushManager` returns a
subscription the test made, on the push services' hosts, and pushes are
delivered to the app's service worker through the DevTools protocol
(test-harness.md, "Web"). Playwright's headless shell has no notifications
and denies them whatever is granted, so these tests drive Chromium itself, in
its headless mode.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.support.accounts import Account
from tests.support.database import Database, uuid7
from tests.support.push import BrowserSubscription
from tests.web.conftest import accessibility_violations, sign_in

# The page's push manager answers with the subscription the test made, as a browser would.
FAKE_PUSH_MANAGER = """(subscription) => {
  let current = null;
  const make = () => ({
    endpoint: subscription.endpoint,
    expirationTime: null,
    options: { userVisibleOnly: true },
    toJSON: () => ({ endpoint: subscription.endpoint, expirationTime: null, keys: subscription.keys }),
    getKey: () => null,
    unsubscribe: async () => { current = null; return true; },
  });
  PushManager.prototype.subscribe = async function () { current = current ?? make(); return current; };
  PushManager.prototype.getSubscription = async function () { return current; };
  PushManager.prototype.permissionState = async function () { return "granted"; };
}"""
# Counts, in the service worker, the notifications it has finished showing. Chromium's `getNotifications()`
# can lose a notification that is still being shown while it reads, so tests read the list once, after
# every notification is shown, rather than poll it.
COUNT_SHOWN = """() => {
  self.__shown = 0;
  const show = self.registration.showNotification.bind(self.registration);
  self.registration.showNotification = (title, options) =>
    show(title, options).then(() => { self.__shown += 1; });
}"""
# The notifications the service worker shows.
SHOWN = """async () => {
  const registration = await navigator.serviceWorker.ready;
  const shown = await registration.getNotifications();
  return shown.map((n) => ({ title: n.title, body: n.body, tag: n.tag }));
}"""
KINDS = ("run_finished", "run_failed", "approval_pending", "question_pending")


@pytest.fixture(scope="module")
def chromium(playwright: Playwright) -> Iterator[Browser]:
    """Chromium itself, which shows notifications, rather than the headless shell, which never does."""
    browser = playwright.chromium.launch(channel="chromium")
    yield browser
    browser.close()


@pytest.fixture
def page(chromium: Browser, web_origin: str) -> Iterator[Page]:
    context = chromium.new_context(base_url=web_origin)
    page = context.new_page()
    page.set_default_timeout(15_000)
    yield page
    context.close()


def _notifications_page(page: Page, member: Account, subscription: BrowserSubscription) -> None:
    page.context.grant_permissions(["notifications"])
    page.add_init_script(f"({FAKE_PUSH_MANAGER})({json.dumps(subscription.to_json())})")
    sign_in(page, member)


def _subscribed(page: Page) -> bool:
    response = page.request.get("/v1/me/notifications")
    assert response.status == 200, response.text()
    return bool(response.json()["subscribed"])


@pytest.mark.spec("UX-004", "UX-007")
def test_notifications_are_turned_on_and_off_on_this_device(page: Page, member: Account, database: Database) -> None:
    subscription = BrowserSubscription()
    _notifications_page(page, member, subscription)
    page.goto("/settings?section=notifications")
    switch = page.get_by_role("switch", name="Notifications on this device")
    expect(switch).not_to_be_checked()
    # What the push service learns is said before the user turns them on (ADR-0039).
    expect(page.get_by_text("push service", exact=False).first).to_be_visible()
    assert accessibility_violations(page) == []
    switch.click()
    expect(switch).to_be_checked()
    assert _subscribed(page)
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT endpoint, p256dh, auth FROM notification_subscriptions WHERE owner_id = %s", (member.id,)
        ).fetchall()
    keys = subscription.to_json()["keys"]
    assert rows == [(subscription.endpoint, keys["p256dh"], keys["auth"])]
    # A reload shows the device's state.
    page.reload()
    expect(page.get_by_role("switch", name="Notifications on this device")).to_be_checked()
    page.get_by_role("switch", name="Notifications on this device").click()
    expect(page.get_by_role("switch", name="Notifications on this device")).not_to_be_checked()
    assert not _subscribed(page)


@pytest.mark.spec("UX-004")
def test_a_push_shows_a_notification_that_reveals_nothing(page: Page, member: Account) -> None:
    _notifications_page(page, member, BrowserSubscription())
    page.evaluate("async () => { await navigator.serviceWorker.ready; }")
    conversations: dict[str, str] = {}
    for kind in KINDS:
        response = page.request.post(
            "/v1/conversations", data={"title": f"Secret plans {kind}"}, headers={"X-Sibillo-Request": "1"}
        )
        assert response.status == 201, response.text()
        conversations[kind] = str(response.json()["id"])

    devtools = page.context.new_cdp_session(page)
    send = cast("Callable[[str, dict[str, Any] | None], dict[str, Any]]", devtools.send)  # pyright: ignore[reportUnknownMemberType]
    registrations: list[dict[str, Any]] = []

    def updated(event: dict[str, Any]) -> None:
        registrations.extend(cast("list[dict[str, Any]]", event["registrations"]))

    devtools.on("ServiceWorker.workerRegistrationUpdated", updated)  # pyright: ignore[reportUnknownMemberType]
    send("ServiceWorker.enable", None)
    deadline = time.monotonic() + 15
    while not registrations:
        assert time.monotonic() < deadline, "no service worker registration"
        page.wait_for_timeout(100)
    registration_id = registrations[0]["registrationId"]
    origin = page.evaluate("location.origin")
    (worker,) = page.context.service_workers
    worker.evaluate(COUNT_SHOWN)
    for kind in KINDS:
        payload = {"kind": kind, "conversation_id": conversations[kind], "run_id": str(uuid7())}
        send(
            "ServiceWorker.deliverPushMessage",
            {"origin": origin, "registrationId": registration_id, "data": json.dumps(payload)},
        )

    deadline = time.monotonic() + 15
    while (count := cast("int", worker.evaluate("self.__shown"))) < len(KINDS):
        assert time.monotonic() < deadline, f"{count} of {len(KINDS)} notifications shown"
        page.wait_for_timeout(100)
    shown = cast("list[dict[str, str]]", page.evaluate(SHOWN))
    # One per conversation, each with its own text, and none naming the conversation.
    assert sorted(item["tag"] for item in shown) == sorted(conversations.values())
    texts = {(item["title"], item["body"]) for item in shown}
    assert len(texts) == len(KINDS)
    for item in shown:
        assert item["title"].strip()
        assert "Secret" not in item["title"] + item["body"]
