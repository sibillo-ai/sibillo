"""The stream of the user's changes (API-008, ADR-0108).

A client reads `GET /me/events` in the background while the test makes
changes; each change must reach the stream of its user within a second of
its transaction, and nobody else's.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from tests.support.accounts import body
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server
from tests.support.tasks import create_task, wait_for_conversations

# A change reaches the stream within a second; the test allows for a busy machine.
ARRIVAL_SECONDS = 3
# How long the model takes to write a title, when the test makes it slow (tests/support/model.py).
SLOW_TITLE_SECONDS = 6


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


class Changes:
    """The change events one client received so far."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.opened = threading.Event()
        self._lock = threading.Lock()

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

    def wait_for(self, predicate: Callable[[dict[str, Any]], bool], timeout: float = ARRIVAL_SECONDS) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                found = [event for event in self.events if predicate(event)]
            if found:
                return found[0]
            time.sleep(0.05)
        raise AssertionError(f"no such change arrived; received {self.events}")


@contextmanager
def following(server: Server, token: str) -> Generator[Changes]:
    """Read the user's stream of changes in the background while the block runs."""
    changes = Changes()
    stop = threading.Event()

    def read() -> None:
        with (
            httpx.Client(
                base_url=server.base_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(10, read=60),
            ) as client,
            client.stream("GET", "/me/events") as response,
        ):
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            changes.opened.set()
            name, data = "", ""
            for line in response.iter_lines():
                if stop.is_set():
                    return
                if line.startswith("event:"):
                    name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data += line.removeprefix("data:").strip()
                elif line == "" and data:
                    event = json.loads(data)
                    assert event["type"] == name
                    changes.add(event)
                    name, data = "", ""

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    assert changes.opened.wait(10), "the stream did not open"
    # The API listens before it answers; a moment more for the stream to be registered.
    time.sleep(0.3)
    try:
        yield changes
    finally:
        stop.set()


@pytest.mark.spec("API-008")
def test_conversations_and_runs_reach_the_stream_of_their_user(server: Server, member: Member) -> None:
    with following(server, member.token) as changes:
        conversation_id = create_conversation(server, member.token)["id"]
        changes.wait_for(lambda e: e == {"type": "conversation_created", "conversation_id": conversation_id})
        run_id, _ = start_run(server, member.token, conversation_id, "Hello")
        wait_for_run(server, member.token, run_id)
        started = changes.wait_for(lambda e: e["type"] == "run_started" and e.get("run_id") == run_id)
        finished = changes.wait_for(lambda e: e["type"] == "run_finished" and e.get("run_id") == run_id)
    for event in (started, finished):
        assert event == {"type": event["type"], "conversation_id": conversation_id, "run_id": run_id}


@pytest.mark.spec("CNV-006", "API-008")
def test_a_run_ends_before_a_slow_title_which_the_stream_then_announces(server: Server, member: Member) -> None:
    conversation_id = create_conversation(server, member.token)["id"]
    with following(server, member.token) as changes:
        began = time.monotonic()
        run_id, events = start_run(
            server, member.token, conversation_id, f"slow-title:{SLOW_TITLE_SECONDS} ||| plan a trip"
        )
        assert wait_for_run(server, member.token, run_id)["status"] == "completed"
        # The answer did not wait for the title (ADR-0146).
        assert time.monotonic() - began < SLOW_TITLE_SECONDS
        assert not [e for e in events if e.type == "CUSTOM" and e.data.get("name") == "sibillo.title"]
        with server.client(member.token) as client:
            assert body(client.get(f"/conversations/{conversation_id}"))["title"] == ""
        titled = changes.wait_for(
            lambda e: e["type"] == "conversation_titled", timeout=SLOW_TITLE_SECONDS + ARRIVAL_SECONDS
        )
    assert titled == {"type": "conversation_titled", "conversation_id": conversation_id}
    with server.client(member.token) as client:
        assert body(client.get(f"/conversations/{conversation_id}"))["title"]


@pytest.mark.spec("API-008", "TSK-002")
def test_a_task_s_firing_reaches_the_stream(server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    with following(server, member.token) as changes:
        with server.client(member.token) as client:
            assert client.post(f"/tasks/{task['id']}/fire").status_code == 202
        changes.wait_for(lambda e: e == {"type": "task_fired", "task_id": task["id"]}, timeout=10)
        (item,) = wait_for_conversations(server, member.token, task["id"])
        changes.wait_for(lambda e: e == {"type": "conversation_created", "conversation_id": item["conversation_id"]})
        changes.wait_for(lambda e: e["type"] == "run_finished" and e.get("conversation_id") == item["conversation_id"])


@pytest.mark.spec("API-008", "TEN-007")
def test_no_change_reaches_another_user_s_stream(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    other = new_member(database, server, default_model)
    with following(server, other.token) as theirs, following(server, member.token) as mine:
        conversation_id = create_conversation(server, member.token)["id"]
        mine.wait_for(lambda e: e.get("conversation_id") == conversation_id)
        time.sleep(1)
        assert [e for e in theirs.events if e.get("conversation_id") == conversation_id] == []


@pytest.mark.spec("API-008")
def test_the_stream_needs_a_session(server: Server) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        assert client.get("/me/events").status_code == 401
