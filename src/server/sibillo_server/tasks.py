"""Tasks and their triggers: conversations that start without a message (TSK-001 to TSK-010, ADR-0106).

A user's task holds instructions, settings, triggers and grants; row-level
security keeps it theirs. A trigger that fires records a firing, at most once
for what it stands for, and at most 10 an hour; the worker starts each firing
as a new conversation, one at a time per task. Webhook triggers and MCP event
deliveries reach the API without a session: the token, or the signature,
authenticates them as their trigger, and their answers tell nothing of what
they belong to.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import secrets
import time
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

import jsonschema
from croniter import croniter
from fastapi import APIRouter, Body, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine, request_source
from sibillo_server.changes import announce
from sibillo_server.changes import event as change_event
from sibillo_server.connections import SecretKey, allowed, offered
from sibillo_server.conversations import decode_cursor, encode_cursor
from sibillo_server.credentials import uuid7
from sibillo_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction
from sibillo_server.encryption import decrypt_labelled
from sibillo_server.mcp_events import fresh, reviewed, signature_valid
from sibillo_server.mcp_servers import servers_of, tool_status
from sibillo_server.memory import memory_enabled
from sibillo_server.permissions import permissions_of
from sibillo_server.settings import new_conversation
from sibillo_server.task_policy import Check, Grant, check, refusal

router = APIRouter()

MAX_TASKS = 50
MAX_TRIGGERS = 5
# A task starts at most this many conversations an hour (TSK-009).
FIRINGS_PER_HOUR = 10
# A schedule fires at most once every 15 minutes (TSK-003).
MIN_SCHEDULE_GAP = datetime.timedelta(minutes=15)
# How many firing times are looked at to find a schedule's shortest gap.
SCHEDULE_SAMPLES = 2000
SCHEDULE_START = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
# A webhook request's body, and a delivery of MCP events (TSK-007, TSK-008).
WEBHOOK_BODY_BYTES = 64 * 1024
DELIVERY_BODY_BYTES = 256 * 1024
# What a firing keeps of an event's data.
EVENT_BYTES = 64 * 1024
HOOKS_PER_ADDRESS = 30
HOOKS_PER_SOURCE = 60
DELIVERIES_PER_SOURCE = 120
HOOK_PREFIX = "/v1/hooks/"
EVENTS_PREFIX = "/v1/mcp-events/"
SECRET_LABEL = "secret"  # noqa: S105 - a label of encrypted data, not a secret
# A poll is never sooner than a minute after the last one (TSK-008).
MIN_POLL_SECONDS = 60

TASK_COLUMNS = (
    "id, name, instructions, connection_id, model, reasoning, disabled_tools, disabled_skills, disabled_servers,"
    " uses_memory, time_zone, paused_at, skipped_count, last_skipped_at, created_at, updated_at"
)
TRIGGER_COLUMNS = (
    "id, task_id, kind, schedule, next_fire_at, token_hash, server_id, server_generation, event_name,"
    " event_arguments, delivery, cursor, next_poll_at, secret_ciphertext, refresh_before, problem, created_at"
)


# --- Limits of requests without a session ---


class _Window:
    """At most `limit` uses of a key a minute, per API process."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._times: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

    def take(self, key: str) -> None:
        now = time.monotonic()
        times = self._times[key]
        while times and times[0] <= now - 60:
            times.popleft()
        if len(times) >= self._limit:
            raise errors.rate_limited(max(1, int(times[0] + 60 - now) + 1))
        times.append(now)
        if len(self._times) > 100_000:
            self._times = collections.defaultdict(
                collections.deque, {k: v for k, v in self._times.items() if v and v[-1] > now - 60}
            )


_BY_ADDRESS = _Window(HOOKS_PER_ADDRESS)
_BY_SOURCE = _Window(HOOKS_PER_SOURCE)
_DELIVERIES = _Window(DELIVERIES_PER_SOURCE)
# Delivery IDs seen in the last minutes; older deliveries are refused by their timestamp anyway.
_SEEN: dict[str, float] = {}


def _seen_before(delivery: str) -> bool:
    now = time.monotonic()
    if len(_SEEN) > 10_000:
        for key in [key for key, at in _SEEN.items() if at < now - 600]:
            del _SEEN[key]
    if delivery in _SEEN and _SEEN[delivery] > now - 600:
        return True
    _SEEN[delivery] = now
    return False


# --- Schedules (TSK-003) ---


def _zone(name: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        raise errors.invalid("/time_zone", "unknown") from None


def check_schedule(expression: str, location: str) -> None:
    """A cron expression of five fields that fires at most once every 15 minutes."""
    if len(expression.split()) != 5 or not croniter.is_valid(expression):
        raise errors.invalid(location, "invalid_schedule")
    iterator = croniter(expression, SCHEDULE_START)
    previous: datetime.datetime = iterator.get_next(datetime.datetime)
    for _ in range(SCHEDULE_SAMPLES):
        current: datetime.datetime = iterator.get_next(datetime.datetime)
        if current - previous < MIN_SCHEDULE_GAP:
            raise errors.invalid(location, "too_often")
        previous = current


def next_fire(expression: str, zone: str, after: datetime.datetime) -> datetime.datetime:
    """The schedule's next firing time after `after`, in the task's time zone, as a UTC instant."""
    local = after.astimezone(zoneinfo.ZoneInfo(zone))
    found: datetime.datetime = croniter(expression, local).get_next(datetime.datetime)
    return found.astimezone(datetime.UTC)


# --- Reading tasks ---


@dataclass(frozen=True)
class TaskState:
    """A task with its triggers and grants, as the database holds them."""

    row: Any
    triggers: list[Any]
    grants: list[Grant]


async def find_task(connection: AsyncConnection, task_id: uuid.UUID, *, lock: bool = False) -> TaskState:
    row = (
        await connection.execute(
            text(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = :id{' FOR UPDATE' if lock else ''}"),  # noqa: S608
            {"id": task_id},
        )
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    triggers = list(
        (
            await connection.execute(
                text(f"SELECT {TRIGGER_COLUMNS} FROM task_triggers WHERE task_id = :id ORDER BY created_at, id"),  # noqa: S608
                {"id": task_id},
            )
        ).all()
    )
    grants = [
        Grant(row.tool, row.arguments)
        for row in await connection.execute(
            text("SELECT tool, arguments FROM task_grants WHERE task_id = :id ORDER BY created_at, id"), {"id": task_id}
        )
    ]
    return TaskState(row, triggers, grants)


def has_event_trigger(kinds: Sequence[str]) -> bool:
    return any(kind in ("webhook", "mcp_event") for kind in kinds)


async def grant_check(connection: AsyncConnection, state: TaskState) -> Check:
    """The check of TSK-005 as the task and its user's memory stand now."""
    memory = bool(state.row.uses_memory) and await memory_enabled(connection)
    return check(state.grants, memory=memory, event_trigger=has_event_trigger([t.kind for t in state.triggers]))


def _check_out(found: Check) -> schemas.GrantCheck:
    return schemas.GrantCheck(
        passes=found.passes,
        private_data=list(found.private_data),
        untrusted_content=list(found.untrusted_content),
        external_communication=list(found.external_communication),
    )


def _trigger(row: Any, webhook_paths: dict[uuid.UUID, str]) -> schemas.TaskTrigger:
    return schemas.TaskTrigger(
        id=row.id,
        kind=row.kind,
        schedule=row.schedule,
        next_fire_at=row.next_fire_at,
        webhook_path=webhook_paths.get(row.id),
        server_id=row.server_id,
        event=row.event_name,
        arguments=row.event_arguments,
        delivery=row.delivery,
        problem=row.problem,
        created_at=row.created_at,
    )


async def task_response(
    connection: AsyncConnection, state: TaskState, webhook_paths: dict[uuid.UUID, str] | None = None
) -> schemas.Task:
    row = state.row
    last = (
        await connection.execute(text("SELECT max(created_at) FROM task_firings WHERE task_id = :id"), {"id": row.id})
    ).scalar_one_or_none()
    return schemas.Task(
        id=row.id,
        name=row.name,
        instructions=row.instructions,
        model=None
        if row.connection_id is None or row.model is None
        else schemas.ModelChoiceOut(connection_id=row.connection_id, model=row.model),
        reasoning=row.reasoning,
        disabled_tools=list(row.disabled_tools),
        disabled_skills=list(row.disabled_skills),
        disabled_servers=list(row.disabled_servers),
        uses_memory=row.uses_memory,
        time_zone=row.time_zone,
        paused=row.paused_at is not None,
        triggers=[_trigger(trigger, webhook_paths or {}) for trigger in state.triggers],
        grants=[
            schemas.TaskGrantOut(tool=grant.tool, arguments=None if grant.arguments is None else dict(grant.arguments))
            for grant in state.grants
        ],
        grant_check=_check_out(await grant_check(connection, state)),
        skipped=schemas.TaskSkipped(count=row.skipped_count, last_at=row.last_skipped_at),
        last_fired_at=last,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- Checking what a task may hold ---


async def server_tools(connection: AsyncConnection, identity: Identity) -> dict[str, uuid.UUID]:
    """The remote MCP servers' tools the user may be offered, by model name, with their server (AGT-029)."""
    permissions = await permissions_of(connection, identity.user_id)
    found: dict[str, uuid.UUID] = {}
    for server in await servers_of(connection, enabled_only=True):
        if permissions.denies_server(str(server.id)):
            continue
        rows = await connection.execute(
            text("SELECT name, listed, accepted, problem FROM mcp_server_tools WHERE server_id = :id"),
            {"id": server.id},
        )
        for row in rows:
            if tool_status(row.listed, row.accepted, row.problem) == "accepted":
                found[f"{server.prefix}__{row.name}"] = server.id
    return found


async def _check_grants(
    connection: AsyncConnection, identity: Identity, grants: Sequence[schemas.TaskGrant]
) -> list[tuple[Grant, uuid.UUID | None]]:
    """The grants, each with its server when it names a server's tool; refused when one cannot be given (TSK-004)."""
    permissions = await permissions_of(connection, identity.user_id)
    tools = await server_tools(connection, identity)
    checked: list[tuple[Grant, uuid.UUID | None]] = []
    seen: set[str] = set()
    for index, item in enumerate(grants):
        grant = Grant(item.tool, item.arguments)
        key = json.dumps([grant.tool, grant.arguments], sort_keys=True)
        if key in seen:
            raise errors.invalid(f"/grants/{index}", "duplicate")
        seen.add(key)
        if item.arguments is not None and len(json.dumps(item.arguments).encode()) > 4096:
            raise errors.invalid(f"/grants/{index}/arguments", "too_large")
        reason = refusal(grant, permissions, tools)
        if reason is not None:
            raise errors.ApiError(
                422, "task.grant_not_allowed", "Grant not allowed", detail=f"{grant.tool} cannot be granted: {reason}"
            )
        checked.append((grant, tools.get(grant.tool)))
    return checked


def trifecta(found: Check) -> errors.ApiError:
    return errors.ApiError(
        422,
        "task.lethal_trifecta",
        "Grants refused",
        detail="These grants, with the task's memory and triggers, could send private data out unattended.",
        grant_check=_check_out(found).model_dump(mode="json"),
    )


@dataclass(frozen=True)
class NewTrigger:
    """A trigger to add, checked: what its row holds."""

    kind: str
    schedule: str | None = None
    server_id: uuid.UUID | None = None
    server_generation: uuid.UUID | None = None
    event: str | None = None
    arguments: dict[str, Any] | None = None
    delivery: str | None = None


async def _check_trigger(
    connection: AsyncConnection,
    identity: Identity,
    item: schemas.ScheduleTriggerInput | schemas.WebhookTriggerInput | schemas.EventTriggerInput,
    location: str,
    public_origin: str | None,
) -> NewTrigger:
    if isinstance(item, schemas.ScheduleTriggerInput):
        check_schedule(item.schedule, f"{location}/schedule")
        return NewTrigger("schedule", schedule=item.schedule)
    if isinstance(item, schemas.WebhookTriggerInput):
        return NewTrigger("webhook")
    server = next((s for s in await servers_of(connection, enabled_only=True) if s.id == item.server_id), None)
    permissions = await permissions_of(connection, identity.user_id)
    if server is None or permissions.denies_server(str(server.id)):
        raise errors.invalid(f"{location}/server_id", "not_usable")
    row = (
        await connection.execute(
            text("SELECT listed, accepted FROM mcp_server_events WHERE server_id = :id AND name = :name"),
            {"id": server.id, "name": item.event},
        )
    ).one_or_none()
    if row is None or row.accepted is None or row.listed is None or reviewed(row.listed) != row.accepted:
        raise errors.invalid(f"{location}/event", "not_accepted")
    if len(json.dumps(item.arguments).encode()) > 4096:
        raise errors.invalid(f"{location}/arguments", "too_large")
    try:
        jsonschema.validate(item.arguments, cast(dict[str, Any], row.accepted.get("inputSchema") or {}))
    except jsonschema.ValidationError:
        raise errors.invalid(f"{location}/arguments", "does_not_match_schema") from None
    except jsonschema.SchemaError:
        raise errors.invalid(f"{location}/event", "invalid_schema") from None
    modes = set(cast(list[str], row.listed.get("delivery") or []))
    if public_origin and "webhook" in modes:
        delivery = "webhook"
    elif "poll" in modes:
        delivery = "poll"
    else:
        raise errors.invalid(f"{location}/event", "no_supported_delivery")
    return NewTrigger(
        "mcp_event",
        server_id=server.id,
        server_generation=server.generation,
        event=item.event,
        arguments=item.arguments,
        delivery=delivery,
    )


def _new_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).digest()


async def _insert_trigger(
    connection: AsyncConnection, identity: Identity, task_id: uuid.UUID, zone: str, trigger: NewTrigger
) -> tuple[uuid.UUID, str | None]:
    """Add the trigger: its ID, and a webhook trigger's path, shown once."""
    trigger_id = uuid7()
    token_hash: bytes | None = None
    path: str | None = None
    if trigger.kind == "webhook":
        token, token_hash = _new_token()
        path = f"{HOOK_PREFIX}{token}"
    now = datetime.datetime.now(datetime.UTC)
    await connection.execute(
        text(
            "INSERT INTO task_triggers (id, tenant_id, owner_id, task_id, kind, schedule, next_fire_at, token_hash,"
            " server_id, server_generation, event_name, event_arguments, delivery, next_poll_at, created_at)"
            " VALUES (:id, :tenant, :owner, :task, :kind, :schedule, :next_fire_at, :token_hash, :server,"
            " :generation, :event, CAST(:arguments AS jsonb), :delivery, :next_poll_at, now())"
        ),
        {
            "id": trigger_id,
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "task": task_id,
            "kind": trigger.kind,
            "schedule": trigger.schedule,
            "next_fire_at": None if trigger.schedule is None else next_fire(trigger.schedule, zone, now),
            "token_hash": token_hash,
            "server": trigger.server_id,
            "generation": trigger.server_generation,
            "event": trigger.event,
            "arguments": None if trigger.arguments is None else json.dumps(trigger.arguments),
            "delivery": trigger.delivery,
            # The first poll starts the subscription from now (ADR-0106).
            "next_poll_at": now if trigger.delivery == "poll" else None,
        },
    )
    return trigger_id, path


async def _insert_grants(
    connection: AsyncConnection,
    identity: Identity,
    task_id: uuid.UUID,
    grants: Sequence[tuple[Grant, uuid.UUID | None]],
) -> None:
    await connection.execute(text("DELETE FROM task_grants WHERE task_id = :id"), {"id": task_id})
    for grant, server_id in grants:
        await connection.execute(
            text(
                "INSERT INTO task_grants (id, tenant_id, owner_id, task_id, tool, server_id, arguments, created_at)"
                " VALUES (:id, :tenant, :owner, :task, :tool, :server, CAST(:arguments AS jsonb), clock_timestamp())"
            ),
            {
                "id": uuid7(),
                "tenant": identity.tenant_id,
                "owner": identity.user_id,
                "task": task_id,
                "tool": grant.tool,
                "server": server_id,
                "arguments": None if grant.arguments is None else json.dumps(grant.arguments),
            },
        )


async def _check_model(connection: AsyncConnection, choice: schemas.ModelChoice) -> None:
    if not await offered(connection, choice) or not await allowed(connection, choice):
        raise errors.invalid("/model", "not_offered")


def _unique_violation(error: DBAPIError) -> bool:
    return sqlstate(error) == UNIQUE_VIOLATION


async def create(
    connection: AsyncConnection, identity: Identity, body: schemas.CreateTaskRequest, public_origin: str | None
) -> schemas.Task:
    """Create the task in the caller's transaction, after every check of TSK-001 to TSK-005."""
    _zone(body.time_zone)
    count = (await connection.execute(text("SELECT count(*) FROM tasks"))).scalar_one()
    if count >= MAX_TASKS:
        raise errors.conflict()
    if body.model is not None:
        await _check_model(connection, body.model)
    defaults = await new_conversation(connection)
    triggers = [
        await _check_trigger(connection, identity, item, f"/triggers/{index}", public_origin)
        for index, item in enumerate(body.triggers)
    ]
    grants = await _check_grants(connection, identity, body.grants)
    memory = body.uses_memory and await memory_enabled(connection)
    found = check(
        [grant for grant, _ in grants], memory=memory, event_trigger=has_event_trigger([t.kind for t in triggers])
    )
    if not found.passes:
        raise trifecta(found)
    model = body.model or defaults.model
    task_id = uuid7()
    await connection.execute(
        text(
            "INSERT INTO tasks (id, tenant_id, owner_id, name, instructions, connection_id, model, reasoning,"
            " disabled_tools, disabled_skills, disabled_servers, uses_memory, time_zone, created_at, updated_at)"
            " VALUES (:id, :tenant, :owner, :name, :instructions, :connection, :model, :reasoning, :disabled_tools,"
            " :disabled_skills, :disabled_servers, :uses_memory, :time_zone, now(), now())"
        ),
        {
            "id": task_id,
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "name": body.name,
            "instructions": body.instructions,
            "connection": None if model is None else model.connection_id,
            "model": None if model is None else model.model,
            "reasoning": body.reasoning or defaults.reasoning,
            "disabled_tools": list(body.disabled_tools if body.disabled_tools is not None else defaults.disabled_tools),
            "disabled_skills": list(body.disabled_skills or []),
            "disabled_servers": list(
                body.disabled_servers if body.disabled_servers is not None else defaults.disabled_servers
            ),
            "uses_memory": body.uses_memory,
            "time_zone": body.time_zone,
        },
    )
    paths: dict[uuid.UUID, str] = {}
    for trigger in triggers:
        trigger_id, path = await _insert_trigger(connection, identity, task_id, body.time_zone, trigger)
        if path is not None:
            paths[trigger_id] = path
    await _insert_grants(connection, identity, task_id, grants)
    return await task_response(connection, await find_task(connection, task_id), paths)


def _public_origin(request: Request) -> str | None:
    origin = request.app.state.configuration.public_origin
    return origin if isinstance(origin, str) and origin else None


# --- The user's tasks (TSK-001) ---


@router.post("/tasks", status_code=status.HTTP_201_CREATED, response_model=schemas.Task)
async def create_task(
    body: schemas.CreateTaskRequest, request: Request, identity: Authenticated, engine: Engine
) -> schemas.Task:
    try:
        async with transaction(engine, identity) as connection:
            return await create(connection, identity, body, _public_origin(request))
    except DBAPIError as error:
        if _unique_violation(error):
            raise errors.conflict() from None
        raise


@router.get("/tasks", response_model=schemas.TaskList)
async def list_tasks(identity: Authenticated, engine: Engine) -> schemas.TaskList:
    async with transaction(engine, identity) as connection:
        ids = [row.id for row in await connection.execute(text("SELECT id FROM tasks ORDER BY name, id"))]
        return schemas.TaskList(items=[await task_response(connection, await find_task(connection, i)) for i in ids])


@router.get("/tasks/{task_id}", response_model=schemas.Task)
async def get_task(task_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.Task:
    async with transaction(engine, identity) as connection:
        return await task_response(connection, await find_task(connection, task_id))


async def _restart_triggers(connection: AsyncConnection, state: TaskState, zone: str) -> None:
    """Schedules fire next from now, and event subscriptions start again from now (ADR-0106)."""
    now = datetime.datetime.now(datetime.UTC)
    for trigger in state.triggers:
        if trigger.kind == "schedule":
            await connection.execute(
                text("UPDATE task_triggers SET next_fire_at = :at WHERE id = :id"),
                {"id": trigger.id, "at": next_fire(trigger.schedule, zone, now)},
            )
        elif trigger.kind == "mcp_event":
            await connection.execute(
                text(
                    "UPDATE task_triggers SET cursor = NULL, problem = NULL,"
                    " next_poll_at = CASE WHEN delivery = 'poll' THEN now() END, refresh_before = NULL WHERE id = :id"
                ),
                {"id": trigger.id},
            )


async def change(
    connection: AsyncConnection, identity: Identity, task_id: uuid.UUID, body: schemas.UpdateTaskRequest
) -> schemas.Task:
    """Change the task in the caller's transaction, after the checks of TSK-001 to TSK-005."""
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    for name in present:
        if getattr(body, name) is None:
            raise errors.invalid(f"/{name}", "null")
    state = await find_task(connection, task_id, lock=True)
    row = state.row
    zone = body.time_zone if body.time_zone is not None else row.time_zone
    _zone(zone)
    if body.model is not None:
        await _check_model(connection, body.model)
    grants = (
        await _check_grants(connection, identity, body.grants)
        if body.grants is not None
        else [(grant, None) for grant in state.grants]
    )
    uses_memory = body.uses_memory if body.uses_memory is not None else row.uses_memory
    memory = uses_memory and await memory_enabled(connection)
    found = check(
        [grant for grant, _ in grants],
        memory=memory,
        event_trigger=has_event_trigger([t.kind for t in state.triggers]),
    )
    # A change that would complete the trifecta is refused; a task that no longer passes for other
    # reasons keeps its other changes (TSK-005).
    if not found.passes and bool(present & {"grants", "uses_memory"}):
        raise trifecta(found)
    await connection.execute(
        text(
            "UPDATE tasks SET name = :name, instructions = :instructions, connection_id = :connection,"
            " model = :model, reasoning = :reasoning, disabled_tools = :disabled_tools,"
            " disabled_skills = :disabled_skills, disabled_servers = :disabled_servers,"
            " uses_memory = :uses_memory, time_zone = :time_zone,"
            " paused_at = CASE WHEN CAST(:paused AS boolean) IS NULL THEN paused_at"
            " WHEN CAST(:paused AS boolean) THEN coalesce(paused_at, now())"
            " ELSE NULL END, updated_at = now() WHERE id = :id"
        ),
        {
            "id": task_id,
            "name": body.name or row.name,
            "instructions": body.instructions or row.instructions,
            "connection": body.model.connection_id if body.model is not None else row.connection_id,
            "model": body.model.model if body.model is not None else row.model,
            "reasoning": body.reasoning or row.reasoning,
            "disabled_tools": list(body.disabled_tools if body.disabled_tools is not None else row.disabled_tools),
            "disabled_skills": list(body.disabled_skills if body.disabled_skills is not None else row.disabled_skills),
            "disabled_servers": list(
                body.disabled_servers if body.disabled_servers is not None else row.disabled_servers
            ),
            "uses_memory": uses_memory,
            "time_zone": zone,
            "paused": body.paused,
        },
    )
    if body.grants is not None:
        await _insert_grants(connection, identity, task_id, grants)
    resumed = body.paused is False and row.paused_at is not None
    if resumed or (body.time_zone is not None and body.time_zone != row.time_zone):
        await _restart_triggers(connection, state, zone)
    return await task_response(connection, await find_task(connection, task_id))


@router.patch("/tasks/{task_id}", response_model=schemas.Task)
async def update_task(
    task_id: uuid.UUID, body: schemas.UpdateTaskRequest, identity: Authenticated, engine: Engine
) -> schemas.Task:
    try:
        async with transaction(engine, identity) as connection:
            return await change(connection, identity, task_id, body)
    except DBAPIError as error:
        if _unique_violation(error):
            raise errors.conflict() from None
        raise


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_task(task_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await find_task(connection, task_id, lock=True)
        # Its grants, triggers and firings go with it; its conversations stay, with its name (ADR-0106).
        await connection.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/conversations", response_model=schemas.TaskConversationPage)
async def list_task_conversations(
    task_id: uuid.UUID, identity: Authenticated, engine: Engine, cursor: str | None = None, limit: int = 50
) -> schemas.TaskConversationPage:
    if not 1 <= limit <= 100:
        raise errors.invalid("limit", "out_of_range")
    after: tuple[datetime.datetime, uuid.UUID] | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        try:
            after = (datetime.datetime.fromisoformat(decoded[0]), uuid.UUID(decoded[1]))
        except (TypeError, ValueError, IndexError):
            raise errors.invalid("cursor", "invalid") from None
    async with transaction(engine, identity) as connection:
        await find_task(connection, task_id)
        rows = (
            await connection.execute(
                text(
                    "SELECT f.id, f.conversation_id, c.title, f.trigger_kind, f.without_grants, f.started_at,"
                    " (SELECT r.status FROM runs r WHERE r.conversation_id = c.id AND r.parent_run_id IS NULL"
                    "  LIMIT 1) AS outcome"
                    " FROM task_firings f JOIN conversations c ON c.id = f.conversation_id"
                    " WHERE f.task_id = :task AND f.started_at IS NOT NULL"
                    " AND (CAST(:after_time AS timestamptz) IS NULL"
                    " OR (f.started_at, f.id) < (CAST(:after_time AS timestamptz), CAST(:after_id AS uuid)))"
                    " ORDER BY f.started_at DESC, f.id DESC LIMIT :limit"
                ),
                {
                    "task": task_id,
                    "after_time": None if after is None else after[0],
                    "after_id": None if after is None else after[1],
                    "limit": limit + 1,
                },
            )
        ).all()
    items = [
        schemas.TaskConversation(
            conversation_id=row.conversation_id,
            title=row.title,
            trigger_kind=row.trigger_kind,
            outcome=row.outcome,
            without_grants=row.without_grants,
            started_at=row.started_at,
        )
        for row in rows[:limit]
    ]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor([last.started_at.isoformat(), str(last.id)])
    return schemas.TaskConversationPage(items=items, next_cursor=next_cursor)


@router.post("/tasks/{task_id}/fire", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def fire_task(task_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    """Fire the task at once, also while it is paused; it waits its turn as any firing (TSK-011, ADR-0107)."""
    async with transaction(engine, identity) as connection:
        await find_task(connection, task_id)
        fired = await record_firing(
            connection,
            identity,
            task_id=task_id,
            trigger_id=None,
            kind="manual",
            fire_key=f"manual:{uuid.uuid4()}",
            event=None,
            manual=True,
        )
    if not fired:
        raise errors.ApiError(409, "task.limit_reached", "Limit reached")
    return Response(status_code=status.HTTP_202_ACCEPTED)


# --- Triggers ---

type TriggerBody = Annotated[
    schemas.ScheduleTriggerInput | schemas.WebhookTriggerInput | schemas.EventTriggerInput,
    Body(discriminator="kind"),
]


@router.post("/tasks/{task_id}/triggers", status_code=status.HTTP_201_CREATED, response_model=schemas.TaskTrigger)
async def add_task_trigger(
    task_id: uuid.UUID, body: TriggerBody, request: Request, identity: Authenticated, engine: Engine
) -> schemas.TaskTrigger:
    async with transaction(engine, identity) as connection:
        state = await find_task(connection, task_id, lock=True)
        if len(state.triggers) >= MAX_TRIGGERS:
            raise errors.invalid("/", "too_many_triggers")
        trigger = await _check_trigger(connection, identity, body, "", _public_origin(request))
        memory = bool(state.row.uses_memory) and await memory_enabled(connection)
        found = check(
            state.grants,
            memory=memory,
            event_trigger=has_event_trigger([t.kind for t in state.triggers] + [trigger.kind]),
        )
        if not found.passes:
            raise trifecta(found)
        trigger_id, path = await _insert_trigger(connection, identity, task_id, state.row.time_zone, trigger)
        added = (
            await connection.execute(
                text(f"SELECT {TRIGGER_COLUMNS} FROM task_triggers WHERE id = :id"),  # noqa: S608
                {"id": trigger_id},
            )
        ).one()
        return _trigger(added, {} if path is None else {trigger_id: path})


@router.delete(
    "/tasks/{task_id}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def remove_task_trigger(
    task_id: uuid.UUID, trigger_id: uuid.UUID, identity: Authenticated, engine: Engine
) -> Response:
    async with transaction(engine, identity) as connection:
        state = await find_task(connection, task_id, lock=True)
        if trigger_id not in {t.id for t in state.triggers}:
            raise errors.not_found()
        # A task keeps at least one trigger (TSK-001).
        if len(state.triggers) == 1:
            raise errors.conflict()
        await connection.execute(text("DELETE FROM task_triggers WHERE id = :id"), {"id": trigger_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tasks/{task_id}/triggers/{trigger_id}/webhook-address", response_model=schemas.TaskTrigger)
async def replace_webhook_address(
    task_id: uuid.UUID, trigger_id: uuid.UUID, identity: Authenticated, engine: Engine
) -> schemas.TaskTrigger:
    async with transaction(engine, identity) as connection:
        state = await find_task(connection, task_id, lock=True)
        trigger = next((t for t in state.triggers if t.id == trigger_id), None)
        if trigger is None:
            raise errors.not_found()
        if trigger.kind != "webhook":
            raise errors.conflict()
        token, token_hash = _new_token()
        await connection.execute(
            text("UPDATE task_triggers SET token_hash = :hash WHERE id = :id"), {"id": trigger_id, "hash": token_hash}
        )
        row = (
            await connection.execute(
                text(f"SELECT {TRIGGER_COLUMNS} FROM task_triggers WHERE id = :id"),  # noqa: S608
                {"id": trigger_id},
            )
        ).one()
        return _trigger(row, {trigger_id: f"{HOOK_PREFIX}{token}"})


# --- Firings (TSK-002, TSK-009) ---


def bounded_event(event: dict[str, Any]) -> dict[str, Any]:
    """The event as a firing keeps it, its data cut to a bounded size (AGT-014)."""
    encoded = json.dumps(event)
    if len(encoded.encode()) <= EVENT_BYTES:
        return event
    data = json.dumps(event.get("data", event.get("body")))
    kept = data.encode()[: EVENT_BYTES // 2].decode(errors="ignore")
    return {key: value for key, value in event.items() if key not in ("data", "body")} | {
        "data": f"{kept} [cut: the event was longer than {EVENT_BYTES} bytes]"
    }


async def record_firing(
    connection: AsyncConnection,
    identity: Identity,
    *,
    task_id: uuid.UUID,
    trigger_id: uuid.UUID | None,
    kind: str,
    fire_key: str,
    event: dict[str, Any] | None,
    manual: bool = False,
) -> bool:
    """Record that the trigger fired, once for what it stands for: whether a firing now waits to run.

    A paused task, unless its user fires it at once, or one that started 10 conversations in the last hour,
    only counts it (TSK-009, TSK-011).
    """
    task = (
        await connection.execute(text("SELECT paused_at FROM tasks WHERE id = :id FOR UPDATE"), {"id": task_id})
    ).one_or_none()
    if task is None:
        return False
    known = (
        await connection.execute(
            text("SELECT 1 FROM task_firings WHERE task_id = :task AND fire_key = :key"),
            {"task": task_id, "key": fire_key},
        )
    ).one_or_none()
    if known is not None:
        return False
    recent = (
        await connection.execute(
            text("SELECT count(*) FROM task_firings WHERE task_id = :task AND created_at > now() - interval '1 hour'"),
            {"task": task_id},
        )
    ).scalar_one()
    if (task.paused_at is not None and not manual) or recent >= FIRINGS_PER_HOUR:
        await connection.execute(
            text("UPDATE tasks SET skipped_count = skipped_count + 1, last_skipped_at = now() WHERE id = :id"),
            {"id": task_id},
        )
        return False
    result = await connection.execute(
        text(
            "INSERT INTO task_firings (id, tenant_id, owner_id, task_id, trigger_id, trigger_kind, fire_key, event,"
            " status, created_at) VALUES (:id, :tenant, :owner, :task, :trigger, :kind, :key, CAST(:event AS jsonb),"
            " 'waiting', now()) ON CONFLICT (task_id, fire_key) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "task": task_id,
            "trigger": trigger_id,
            "kind": kind,
            "key": fire_key,
            "event": None if event is None else json.dumps(bounded_event(event)),
        },
    )
    if result.rowcount == 1:
        # The user's clients learn at once that the task fired (API-008, ADR-0108).
        await announce(connection, identity, change_event("task_fired", task_id=task_id))
    return result.rowcount == 1


def owner(tenant_id: uuid.UUID, owner_id: uuid.UUID) -> Identity:
    """The request context of a task's owner, for work done for them without a session."""
    return Identity(
        session_id=uuid.UUID(int=0), user_id=owner_id, tenant_id=tenant_id, role="member", instance_admin=False
    )


async def finish_firing(engine: AsyncEngine, identity: Identity, conversation_id: uuid.UUID) -> None:
    """The firing that started the conversation is done once its first run has ended (TSK-009)."""
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text(
                "UPDATE task_firings SET status = 'done', finished_at = now(), event = NULL"
                " WHERE conversation_id = :id AND status = 'running'"
            ),
            {"id": conversation_id},
        )


# --- Requests without a session (TSK-007, TSK-008) ---


async def _limited_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise _too_large()
    return bytes(body)


def _too_large() -> errors.ApiError:
    return errors.ApiError(413, "request.too_large", "Too large")


def _accepted() -> Response:
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/hooks/{token}", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def fire_webhook_trigger(token: str, request: Request, engine: Engine) -> Response:
    source = request_source(request)
    _BY_SOURCE.take(str(source))
    _BY_ADDRESS.take(token)
    body = await _limited_body(request, WEBHOOK_BODY_BYTES)
    async with transaction(engine, None) as connection:
        found = (
            await connection.execute(
                text("SELECT trigger_id, task_id, tenant_id, owner_id, paused FROM find_webhook_trigger(:hash)"),
                {"hash": hashlib.sha256(token.encode()).digest()},
            )
        ).one_or_none()
    if found is None:
        return _accepted()
    identity = owner(found.tenant_id, found.owner_id)
    event = {
        "content_type": request.headers.get("content-type", "")[:200],
        "body": body.decode("utf-8", errors="replace"),
    }
    async with transaction(engine, identity) as connection:
        await record_firing(
            connection,
            identity,
            task_id=found.task_id,
            trigger_id=found.trigger_id,
            kind="webhook",
            fire_key=f"{found.trigger_id}:{uuid.uuid4()}",
            event=event,
        )
    return _accepted()


def _rejected() -> errors.ApiError:
    return errors.ApiError(401, "webhook.rejected", "Rejected")


@router.post("/mcp-events/{trigger_id}", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def receive_mcp_events(trigger_id: str, request: Request, engine: Engine, key: SecretKey) -> Response:
    _DELIVERIES.take(str(request_source(request)))
    body = await _limited_body(request, DELIVERY_BODY_BYTES)
    delivery = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signatures = request.headers.get("webhook-signature", "")
    try:
        trigger = uuid.UUID(trigger_id)
    except ValueError:
        raise _rejected() from None
    if not delivery or not fresh(timestamp, time.time()):
        raise _rejected()
    async with transaction(engine, None) as connection:
        found = (
            await connection.execute(
                text(
                    "SELECT task_id, tenant_id, owner_id, paused, secret_ciphertext FROM find_event_subscription(:id)"
                ),
                {"id": trigger},
            )
        ).one_or_none()
    if found is None or found.secret_ciphertext is None:
        raise _rejected()
    secret = decrypt_labelled(key, trigger, SECRET_LABEL, bytes(found.secret_ciphertext))
    if not signature_valid(secret, delivery, timestamp, body, signatures):
        raise _rejected()
    if _seen_before(f"{trigger}:{delivery}"):
        raise _rejected()
    try:
        payload: Any = json.loads(body)
    except ValueError:
        raise _rejected() from None
    if not isinstance(payload, dict):
        raise _rejected()
    message = cast(dict[str, Any], payload)
    identity = owner(found.tenant_id, found.owner_id)
    async with transaction(engine, identity) as connection:
        if message.get("type") == "terminated":
            # The server ended the subscription: it is not renewed (ADR-0106).
            await connection.execute(
                text("UPDATE task_triggers SET problem = 'terminated', refresh_before = 'infinity' WHERE id = :id"),
                {"id": trigger},
            )
            return _accepted()
        event_id = message.get("eventId")
        if not isinstance(event_id, str) or not event_id:
            # A gap, or anything else that is no event, fires nothing.
            return _accepted()
        await record_firing(
            connection,
            identity,
            task_id=found.task_id,
            trigger_id=trigger,
            kind="mcp_event",
            fire_key=f"{trigger}:{event_id}",
            event={"name": str(message.get("name", ""))[:64], "data": message.get("data")},
        )
    return _accepted()
