"""Notifications on the user's devices, through Web Push (UX-004, ADR-0039, ADR-0101).

The worker sends to the push service the tests serve, which stands in for the
browsers' push services (tests/support/push.py). Tests subscribe as a browser
does, decrypt what arrives and check its signature. A client follows a run
while it reads the run's event stream: tests leave the stream at the run's
first event, and the served model waits before it answers (`wait:`), so that
the run ends after the client has gone.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.push import BrowserSubscription, Push, PushService, from_b64url
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server

PUSH_TIMEOUT_SECONDS = 15
# How long a test waits to be sure that no notification comes.
QUIET_SECONDS = 1
# Long enough for the client to leave the run's stream before the run ends.
WAIT = "wait:1 ||| "
QUESTION = {
    "header": "Colour",
    "question": "Which colour?",
    "options": [{"label": "Red"}, {"label": "Blue"}],
    "multi_select": False,
}


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def settings(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/me/notifications")
    assert response.status_code == 200, response.text
    return body(response)


def subscribe(server: Server, token: str, subscription: BrowserSubscription | None = None) -> BrowserSubscription:
    subscription = subscription or BrowserSubscription()
    with server.client(token) as client:
        response = client.put("/me/notifications", json=subscription.to_json())
    assert response.status_code == 200, response.text
    assert body(response)["subscribed"] is True
    return subscription


def leave_early(server: Server, token: str, conversation_id: str, text: str) -> str:
    """Start a run and leave its stream at its first event, as a user who closes the app; return its ID."""
    run_id, events = start_run(server, token, conversation_id, text, stop_after=1)
    assert events[0].type == "RUN_STARTED"
    return run_id


def pushed(push_service: PushService, subscription: BrowserSubscription, count: int = 1) -> list[Push]:
    """The first `count` pushes for `subscription`, once they have arrived."""
    deadline = time.monotonic() + PUSH_TIMEOUT_SECONDS
    while len(pushes := push_service.pushes(subscription)) < count:
        assert time.monotonic() < deadline, f"{len(pushes)} of {count} notification(s) arrived"
        time.sleep(0.1)
    return pushes[:count]


def quiet(push_service: PushService, *subscriptions: BrowserSubscription) -> None:
    """No notification arrives for `subscriptions`."""
    time.sleep(QUIET_SECONDS)
    for subscription in subscriptions:
        assert push_service.pushes(subscription) == []


@pytest.mark.spec("UX-004")
def test_notifications_are_off_until_turned_on_on_a_device(server: Server, account: Account, token: str) -> None:
    before = settings(server, token)
    assert before["available"] is True
    assert before["subscribed"] is False
    key = from_b64url(before["public_key"])
    assert len(key) == 65
    assert key[0] == 4, "an uncompressed P-256 point"
    subscribe(server, token)
    assert settings(server, token)["subscribed"] is True
    # Another device of the same user is still off.
    other = login(server, account, "other device")
    assert settings(server, other)["subscribed"] is False
    # Turning them off on the first device.
    with server.client(token) as client:
        assert client.delete("/me/notifications").status_code == 204
    assert settings(server, token)["subscribed"] is False


@pytest.mark.spec("UX-004")
def test_a_run_that_a_client_follows_to_its_end_sends_nothing(
    server: Server, token: str, push_service: PushService
) -> None:
    subscription = subscribe(server, token)
    conversation_id = create_conversation(server, token)["id"]
    run_id, _ = start_run(server, token, conversation_id, WAIT + "hello")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    quiet(push_service, subscription)


@pytest.mark.spec("UX-004")
def test_a_run_the_user_stops_sends_nothing(server: Server, token: str, push_service: PushService) -> None:
    subscription = subscribe(server, token)
    conversation_id = create_conversation(server, token)["id"]
    run_id = leave_early(server, token, conversation_id, "slow:20")
    with server.client(token) as client:
        assert client.post(f"/runs/{run_id}/cancel").status_code == 200
    assert wait_for_run(server, token, run_id)["status"] == "cancelled"
    quiet(push_service, subscription)


@pytest.mark.spec("UX-004")
def test_without_a_public_origin_notifications_are_unavailable(server: Server, account: Account, token: str) -> None:
    api, origin = server.start_twin_api(without=("SIBILLO_PUBLIC_ORIGIN",))
    try:
        twin = server.client(token)
        twin.base_url = f"{origin}/v1"
        with twin as client:
            response = client.get("/me/notifications")
            assert response.status_code == 200, response.text
            assert body(response)["available"] is False
            assert "public_key" not in body(response)
            refused = client.put("/me/notifications", json=BrowserSubscription().to_json())
            assert_problem(refused, 503, "notification.unavailable")
    finally:
        api.close()
    assert settings(server, token)["subscribed"] is False
