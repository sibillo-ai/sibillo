"""Notifications on the user's devices, through Web Push (UX-004, ADR-0039, ADR-0101).

The worker sends to the push service the tests serve, which stands in for the
browsers' push services (tests/support/push.py). Tests subscribe as a browser
does, decrypt what arrives and check its signature. A client follows a run
while it reads the run's event stream: tests leave the stream at the run's
first event, and the served model waits before it answers (`wait:`), so that
the run ends after the client has gone.
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.push import FCM, MOZILLA, BrowserSubscription, Push, PushService, from_b64url, vapid_claims
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
def test_a_run_that_ends_while_nobody_follows_it_notifies_without_content(
    server: Server, token: str, push_service: PushService
) -> None:
    subscription = subscribe(server, token)
    conversation_id = create_conversation(server, token, "Secret plans")["id"]
    before = datetime.datetime.now(datetime.UTC)
    run_id = leave_early(server, token, conversation_id, WAIT + "the private words")
    (push,) = pushed(push_service, subscription)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    # Only the kind and the identifiers.
    assert subscription.decrypt(push) == {"kind": "run_finished", "conversation_id": conversation_id, "run_id": run_id}
    assert push.headers["ttl"] == str(24 * 60 * 60)
    assert push.headers["urgency"] == "normal"
    # Signed by the instance, for this push service.
    claims = vapid_claims(push, settings(server, token)["public_key"])
    assert claims["aud"] == f"https://{FCM}"
    assert claims["sub"] == server.public_origin
    expires = datetime.datetime.fromtimestamp(claims["exp"], datetime.UTC)
    assert before < expires <= before + datetime.timedelta(hours=24, minutes=1)


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
@pytest.mark.parametrize(
    ("text", "status", "kind", "urgency"),
    [
        pytest.param(
            f"tool:save_skill {json.dumps({'path': '/scratch/nothing'})}",
            "interrupted",
            "approval_pending",
            "high",
            id="approval",
        ),
        pytest.param(
            f"tool:ask_user_question {json.dumps({'questions': [QUESTION]})}",
            "interrupted",
            "question_pending",
            "high",
            id="question",
        ),
        # Refused as a content filter refuses: the run fails at once, with no retries (MOD-015).
        pytest.param("refuse", "failed", "run_failed", "normal", id="failure"),
    ],
)
def test_each_kind_of_run_end_has_its_notification(
    server: Server, token: str, push_service: PushService, text: str, status: str, kind: str, urgency: str
) -> None:
    subscription = subscribe(server, token)
    conversation_id = create_conversation(server, token)["id"]
    run_id = leave_early(server, token, conversation_id, WAIT + text)
    (push,) = pushed(push_service, subscription)
    assert wait_for_run(server, token, run_id)["status"] == status
    assert subscription.decrypt(push) == {"kind": kind, "conversation_id": conversation_id, "run_id": run_id}
    assert push.headers["urgency"] == urgency


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
def test_every_subscribed_device_is_notified_but_not_a_signed_out_one(
    server: Server, database: Database, account: Account, token: str, push_service: PushService
) -> None:
    phone = subscribe(server, token)
    laptop_token = login(server, account, "laptop")
    laptop = subscribe(server, laptop_token, BrowserSubscription(MOZILLA))
    tablet_token = login(server, account, "tablet")
    tablet = subscribe(server, tablet_token)
    # Signing out of the tablet ends its notifications.
    with server.client(tablet_token) as client:
        assert client.post("/auth/logout").status_code == 204
    with database.superuser() as conn:
        endpoints = {
            row[0]
            for row in conn.execute(
                "SELECT endpoint FROM notification_subscriptions WHERE owner_id = %s", (account.id,)
            ).fetchall()
        }
    assert endpoints == {phone.endpoint, laptop.endpoint}
    conversation_id = create_conversation(server, token)["id"]
    run_id = leave_early(server, token, conversation_id, WAIT + "hello")
    (on_phone,) = pushed(push_service, phone)
    (on_laptop,) = pushed(push_service, laptop)
    expected = {"kind": "run_finished", "conversation_id": conversation_id, "run_id": run_id}
    assert phone.decrypt(on_phone) == expected
    assert laptop.decrypt(on_laptop) == expected
    assert vapid_claims(on_laptop, settings(server, token)["public_key"])["aud"] == f"https://{MOZILLA}"
    quiet(push_service, tablet)


@pytest.mark.spec("UX-004")
def test_the_subscription_of_an_expired_session_is_not_used(
    server: Server, database: Database, account: Account, token: str, push_service: PushService
) -> None:
    old_token = login(server, account, "old phone")
    old = subscribe(server, old_token)
    current = subscribe(server, token)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE device_sessions SET expires_at = now() - interval '1 minute'"
            " WHERE id = (SELECT device_session_id FROM notification_subscriptions WHERE endpoint = %s)",
            (old.endpoint,),
        )
    conversation_id = create_conversation(server, token)["id"]
    leave_early(server, token, conversation_id, WAIT + "hello")
    pushed(push_service, current)
    quiet(push_service, old)


@pytest.mark.spec("UX-004")
def test_a_subscription_the_push_service_says_is_gone_is_deleted(
    server: Server, token: str, push_service: PushService
) -> None:
    subscription = subscribe(server, token)
    push_service.gone(subscription)
    conversation_id = create_conversation(server, token)["id"]
    leave_early(server, token, conversation_id, WAIT + "hello")
    pushed(push_service, subscription)
    deadline = time.monotonic() + PUSH_TIMEOUT_SECONDS
    while settings(server, token)["subscribed"]:
        assert time.monotonic() < deadline, "the subscription was kept"
        time.sleep(0.1)


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
