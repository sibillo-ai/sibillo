"""Tasks through the API, and the time they wait for (TSK-001 to TSK-010, ADR-0106).

See specs/contracts/test-harness.md ("Tasks"). Tests never wait for a
schedule: they move a trigger's next firing, or its next poll, into the past
as superuser, and the worker, which sweeps every second in tests, does the
rest. Everything else goes through the API.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import time
import uuid
import zoneinfo
from typing import Any

import httpx

from tests.support.accounts import body
from tests.support.database import Database, uuid7
from tests.support.server import Server, fresh_source

# How long a test waits for the worker to fire a task and finish its run.
FIRING_TIMEOUT_SECONDS = 20
# How long a test waits to be sure that nothing fired: a few sweeps of the worker.
QUIET_SECONDS = 3
FINAL_OUTCOMES = frozenset({"completed", "failed", "cancelled", "interrupted"})
# A schedule that would not fire during a test by itself: every day at 07:00, since a day long gone (ADR-0109).
START = "2026-01-01T07:00:00"
DAILY = ["RRULE:FREQ=DAILY"]


def schedule(*recurrence: str, start: str = START) -> dict[str, Any]:
    """A schedule trigger: its start, in the task's time zone, and its lines of RFC 5545; once without lines."""
    return {"kind": "schedule", "start": start, "recurrence": list(recurrence) if recurrence else list(DAILY)}


def once(start: str) -> dict[str, Any]:
    """A schedule that fires once, at its start."""
    return {"kind": "schedule", "start": start, "recurrence": []}


def local(when: datetime.datetime, zone: str = "Europe/Rome") -> str:
    """The instant as a start in the task's time zone, as a schedule takes it."""
    return when.astimezone(zoneinfo.ZoneInfo(zone)).replace(tzinfo=None).isoformat(timespec="seconds")


def webhook() -> dict[str, Any]:
    return {"kind": "webhook"}


def on_event(server_id: str, event: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"kind": "mcp_event", "server_id": server_id, "event": event, "arguments": arguments or {}}


def open_grant(tool: str) -> dict[str, Any]:
    return {"tool": tool, "arguments": None}


def fixed_grant(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"tool": tool, "arguments": arguments}


def task_request(instructions: str = "Say hello.", **fields: Any) -> dict[str, Any]:
    """A request to create a task: a daily schedule in Rome unless `fields` say otherwise."""
    return {
        "name": f"Task {uuid.uuid4().hex[:8]}",
        "instructions": instructions,
        "time_zone": "Europe/Rome",
        "triggers": [schedule()],
        **fields,
    }


def try_create(server: Server, token: str, request: dict[str, Any]) -> httpx.Response:
    with server.client(token) as client:
        return client.post("/tasks", json=request)


def create_task(server: Server, token: str, instructions: str = "Say hello.", **fields: Any) -> dict[str, Any]:
    response = try_create(server, token, task_request(instructions, **fields))
    assert response.status_code == 201, response.text
    return body(response)


def get_task(server: Server, token: str, task_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200, response.text
    return body(response)


def update_task(server: Server, token: str, task_id: str, **fields: Any) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.patch(f"/tasks/{task_id}", json=fields)
    assert response.status_code == 200, response.text
    return body(response)


def trigger_of(task: dict[str, Any], kind: str) -> dict[str, Any]:
    (found,) = [trigger for trigger in task["triggers"] if trigger["kind"] == kind]
    return found


def conversations_of(server: Server, token: str, task_id: str) -> list[dict[str, Any]]:
    """The conversations the task started, newest first, as the API lists them."""
    with server.client(token) as client:
        response = client.get(f"/tasks/{task_id}/conversations", params={"limit": 100})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = body(response)["items"]
    return items


def wait_for_conversations(
    server: Server, token: str, task_id: str, count: int = 1, timeout: float = FIRING_TIMEOUT_SECONDS
) -> list[dict[str, Any]]:
    """The task's conversations, once `count` of them exist and their first runs have ended."""
    deadline = time.monotonic() + timeout
    while True:
        found = conversations_of(server, token, task_id)
        if len(found) >= count and all(item["outcome"] in FINAL_OUTCOMES for item in found):
            return found
        assert time.monotonic() < deadline, f"the task started {len(found)} of {count} conversations: {found}"
        time.sleep(0.2)


def stays_quiet(server: Server, token: str, task_id: str, count: int = 0) -> None:
    """The task started exactly `count` conversations, also after a few sweeps of the worker."""
    time.sleep(QUIET_SECONDS)
    assert len(conversations_of(server, token, task_id)) == count


def fire_schedule(database: Database, trigger_id: str, ago: datetime.timedelta = datetime.timedelta(seconds=1)) -> None:
    """Move a schedule's next firing into the past, as if that time had come `ago` ago."""
    with database.superuser() as conn:
        updated = conn.execute(
            "UPDATE task_triggers SET next_fire_at = now() - %s WHERE id = %s AND kind = 'schedule'",
            (ago, uuid.UUID(trigger_id)),
        ).rowcount
    assert updated == 1


def poll_now(database: Database, trigger_id: str) -> None:
    """Make the worker poll an event subscription at its next sweep, as if a minute had passed."""
    with database.superuser() as conn:
        updated = conn.execute(
            "UPDATE task_triggers SET next_poll_at = now() - interval '1 second' WHERE id = %s",
            (uuid.UUID(trigger_id),),
        ).rowcount
    assert updated == 1


def arrange_done_firings(database: Database, task_id: str, count: int) -> None:
    """Firings of the task that ran in the last hour, as the worker records them (TSK-009)."""
    with database.superuser() as conn:
        tenant_id, owner_id = conn.execute(
            "SELECT tenant_id, owner_id FROM tasks WHERE id = %s", (uuid.UUID(task_id),)
        ).fetchone() or (None, None)
        assert tenant_id is not None
        for _ in range(count):
            conn.execute(
                "INSERT INTO task_firings (id, tenant_id, owner_id, task_id, trigger_kind, fire_key, status,"
                " created_at, started_at, finished_at) VALUES (%s, %s, %s, %s, 'schedule', %s, 'done',"
                " now() - interval '10 minutes', now() - interval '10 minutes', now() - interval '9 minutes')",
                (uuid7(), tenant_id, owner_id, uuid.UUID(task_id), f"arranged:{uuid7()}"),
            )


def firings(database: Database, task_id: str) -> list[dict[str, Any]]:
    """The task's firings as the database holds them, oldest first."""
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT status, trigger_kind, fire_key, without_grants, conversation_id, started_at, finished_at"
            " FROM task_firings WHERE task_id = %s ORDER BY created_at",
            (uuid.UUID(task_id),),
        ).fetchall()
    names = ("status", "trigger_kind", "fire_key", "without_grants", "conversation_id", "started_at", "finished_at")
    return [dict(zip(names, row, strict=True)) for row in rows]


def hook(server: Server, webhook_path: str, content: bytes | str = b"", *, source: str | None = None) -> httpx.Response:
    """A request to a webhook trigger's address, as a home automation rule sends one (TSK-007)."""
    assert webhook_path.startswith("/v1/hooks/"), webhook_path
    data = content.encode() if isinstance(content, str) else content
    with server.client(source=source or fresh_source()) as client:
        return client.post(webhook_path.removeprefix("/v1"), content=data, headers={"Content-Type": "text/plain"})


def token_hash(webhook_path: str) -> bytes:
    """The SHA-256 of the token of a webhook trigger's address, as the database keeps it."""
    return hashlib.sha256(webhook_path.rsplit("/", 1)[1].encode()).digest()


def chain(*calls: tuple[str, dict[str, Any]]) -> str:
    """A model script that calls each tool in turn, one per answer (tests/support/model.py)."""
    return "chain:" + " >>> ".join(f"{name} {json.dumps(arguments)}" for name, arguments in calls)


def path_runs(server: Server, token: str, conversation_id: str) -> list[dict[str, Any]]:
    """The runs of the conversation's active path, with how their calls were decided."""
    with server.client(token) as client:
        response = client.get(f"/conversations/{conversation_id}/messages", params={"limit": 100})
    assert response.status_code == 200, response.text
    runs: list[dict[str, Any]] = body(response)["runs"]
    return runs


def outcomes(server: Server, token: str, conversation_id: str) -> list[str]:
    """How each call of the conversation that needed a decision was decided, in order."""
    return [approval["outcome"] for run in path_runs(server, token, conversation_id) for approval in run["approvals"]]
