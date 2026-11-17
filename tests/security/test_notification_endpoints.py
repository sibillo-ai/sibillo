"""Notifications go only to the browsers' push services (UX-004, ADR-0101, T-39).

A subscription's endpoint comes from the client, and the worker sends
requests to it. The API accepts only `https` endpoints on the hosts of
ADR-0101, and the worker checks again before it sends, so that a row written
some other way cannot make it call an address of the instance or of the
household's network.
"""

from __future__ import annotations

import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.push import APPLE, FCM, MOZILLA, WINDOWS, BrowserSubscription, PushService
from tests.support.runs import create_conversation, start_run
from tests.support.server import Server

PUSH_TIMEOUT_SECONDS = 15


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _with_endpoint(endpoint: str) -> dict[str, Any]:
    return BrowserSubscription().to_json() | {"endpoint": endpoint}


@pytest.mark.spec("UX-004")
@pytest.mark.parametrize("host", [FCM, MOZILLA, APPLE, WINDOWS])
def test_the_push_services_are_accepted(server: Server, token: str, host: str) -> None:
    with server.client(token) as client:
        response = client.put("/me/notifications", json=BrowserSubscription(host).to_json())
    assert response.status_code == 200, response.text
    assert body(response)["subscribed"] is True


@pytest.mark.spec("UX-004")
@pytest.mark.parametrize(
    "endpoint",
    [
        f"http://{FCM}/fcm/send/abc",
        f"https://{FCM}:8443/fcm/send/abc",
        f"https://user:secret@{FCM}/fcm/send/abc",
        f"https://{FCM}.attacker.example/fcm/send/abc",
        "https://notify.windows.com/w/?token=abc",
        "https://evilnotify.windows.com/w/?token=abc",
        "https://example.org/push",
        "https://127.0.0.1/push",
        "https://[::1]/push",
        "https://localhost/push",
        "https://192.168.1.1/push",
        "https://sandboxd/push",
        f"wss://{FCM}/fcm/send/abc",
    ],
)
def test_other_endpoints_are_refused(server: Server, token: str, endpoint: str) -> None:
    with server.client(token) as client:
        response = client.put("/me/notifications", json=_with_endpoint(endpoint))
        assert_problem(response, 422, "notification.endpoint_refused")
        assert body(client.get("/me/notifications"))["subscribed"] is False


class _Listener:
    """A plain HTTP server on the loopback address that counts the requests it receives."""

    def __init__(self) -> None:
        self.requests = 0
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                listener.requests += 1
                self.send_response(201)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.port = self.http.server_address[1]


@pytest.mark.spec("UX-004", "OBS-006")
def test_the_worker_checks_the_endpoint_again_before_it_sends(
    server: Server, database: Database, account: Account, token: str, push_service: PushService
) -> None:
    listener = _Listener()
    try:
        # A subscription on a push service, through the API, for this session.
        good = BrowserSubscription()
        with server.client(token) as client:
            assert client.put("/me/notifications", json=good.to_json()).status_code == 200
        # A row written some other way, for another session of the same user, pointing at the loopback address.
        login(server, account, "other device")
        bad = _with_endpoint(f"http://127.0.0.1:{listener.port}/push")
        keys: dict[str, str] = bad["keys"]
        with database.superuser() as conn:
            (session_id,) = conn.execute(
                "SELECT id FROM device_sessions WHERE user_id = %s AND device_name = 'other device'", (account.id,)
            ).fetchone() or (None,)
            assert isinstance(session_id, uuid.UUID)
            conn.execute(
                "INSERT INTO notification_subscriptions (tenant_id, owner_id, device_session_id, endpoint, p256dh,"
                " auth, created_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
                (account.tenant_id, account.id, session_id, bad["endpoint"], keys["p256dh"], keys["auth"]),
            )
        conversation_id = create_conversation(server, token)["id"]
        start_run(server, token, conversation_id, "wait:1 ||| hello", stop_after=1)
        deadline = time.monotonic() + PUSH_TIMEOUT_SECONDS
        while not push_service.pushes(good):
            assert time.monotonic() < deadline, "the run sent no notification"
            time.sleep(0.1)
        time.sleep(1)
        assert listener.requests == 0
    finally:
        listener.http.shutdown()
