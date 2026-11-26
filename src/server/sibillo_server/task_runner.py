"""The worker's side of tasks: firing schedules, following event subscriptions, starting firings (ADR-0106).

Every sweep, the worker asks the database, before any request context, for
the triggers with work due and the firings waiting their turn, and does each
piece of work under the task's owner's context. A schedule that fires, or an
event that arrives, records a firing (`tasks.record_firing`); each firing is
started by a durable workflow named after it, so that a crash never starts
it twice or loses it: one firing, one conversation (TSK-003).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any

from dbos import DBOS, DBOSClient, SetWorkflowID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server.changes import announce, event
from sibillo_server.conversations import find_conversation
from sibillo_server.credentials import uuid7
from sibillo_server.database import Identity, transaction
from sibillo_server.encryption import decrypt_labelled, encrypt_labelled
from sibillo_server.mcp_client import ServerError
from sibillo_server.mcp_events import new_secret, poll, reviewed, subscribe
from sibillo_server.mcp_servers import find_server, token_for
from sibillo_server.runs import create_run, enqueue, fail_unqueued
from sibillo_server.tasks import (
    EVENTS_PREFIX,
    MIN_POLL_SECONDS,
    SECRET_LABEL,
    find_task,
    grant_check,
    next_fire,
    owner,
    record_firing,
)
from sibillo_server.workflow_input import RunWorkflowInput

logger = logging.getLogger(__name__)

FIRING_WORKFLOW = "sibillo.task_firing"
# A failed subscription is tried again about a minute later: renewals are due 10 minutes before they expire.
RETRY_RENEWAL = datetime.timedelta(minutes=11)


@dataclass
class _Runner:
    engine: AsyncEngine | None = None
    secret_key: bytes = b""
    public_origin: str | None = None
    durable: DBOSClient | None = None


_RUNNER = _Runner()


def configure(engine: AsyncEngine, secret_key: bytes, public_origin: str | None, durable: DBOSClient) -> None:
    _RUNNER.engine = engine
    _RUNNER.secret_key = secret_key
    _RUNNER.public_origin = public_origin
    _RUNNER.durable = durable


def _engine() -> AsyncEngine:
    if _RUNNER.engine is None:
        raise RuntimeError("the task runner is not configured")
    return _RUNNER.engine


def _durable() -> DBOSClient:
    if _RUNNER.durable is None:
        raise RuntimeError("the task runner is not configured")
    return _RUNNER.durable


# --- The sweep ---


async def sweep() -> None:
    """Do the work of every due trigger, then start every firing whose turn has come."""
    async with transaction(_engine(), None) as connection:
        due = (await connection.execute(text("SELECT * FROM due_task_triggers()"))).all()
    for row in due:
        identity = owner(row.tenant_id, row.owner_id)
        try:
            if row.work == "fire":
                await _fire_schedule(identity, row.trigger_id)
            elif row.work == "poll":
                await _poll(identity, row.trigger_id)
            else:
                await _renew(identity, row.trigger_id)
        except Exception:
            # The next sweep tries again.
            logger.exception("a task trigger's %s failed", row.work)
    async with transaction(_engine(), None) as connection:
        waiting = (await connection.execute(text("SELECT * FROM waiting_task_firings()"))).all()
    for row in waiting:
        try:
            with SetWorkflowID(f"firing-{row.firing_id}"):
                await DBOS.start_workflow_async(
                    firing_workflow, str(row.firing_id), str(row.tenant_id), str(row.owner_id)
                )
        except Exception:
            logger.exception("a task's firing could not be started")


async def _trigger(connection: AsyncConnection, trigger_id: uuid.UUID) -> Any:
    return (
        await connection.execute(
            text(
                "SELECT g.*, t.time_zone, t.paused_at FROM task_triggers g JOIN tasks t ON t.id = g.task_id"
                " WHERE g.id = :id FOR UPDATE OF g"
            ),
            {"id": trigger_id},
        )
    ).one_or_none()


async def _fire_schedule(identity: Identity, trigger_id: uuid.UUID) -> None:
    """Fire once for the time that came, however many were missed, and move to the next one (TSK-003)."""
    async with transaction(_engine(), identity) as connection:
        trigger = await _trigger(connection, trigger_id)
        now = datetime.datetime.now(datetime.UTC)
        if trigger is None or trigger.next_fire_at is None or trigger.next_fire_at > now or trigger.paused_at:
            return
        await record_firing(
            connection,
            identity,
            task_id=trigger.task_id,
            trigger_id=trigger.id,
            kind="schedule",
            fire_key=f"{trigger.id}:{trigger.next_fire_at.isoformat()}",
            event=None,
        )
        await connection.execute(
            text("UPDATE task_triggers SET next_fire_at = :at WHERE id = :id"),
            {"id": trigger.id, "at": next_fire(trigger, trigger.time_zone, now)},
        )


async def _accepted_event(connection: AsyncConnection, trigger: Any) -> bool:
    row = (
        await connection.execute(
            text("SELECT listed, accepted FROM mcp_server_events WHERE server_id = :id AND name = :name"),
            {"id": trigger.server_id, "name": trigger.event_name},
        )
    ).one_or_none()
    return (
        row is not None and row.accepted is not None and row.listed is not None and reviewed(row.listed) == row.accepted
    )


async def _subscription(identity: Identity, trigger_id: uuid.UUID) -> tuple[Any, Any, str | None, str | None]:
    """The trigger, its server, the user's token for it, and why events cannot be received, if they cannot."""
    async with transaction(_engine(), identity) as connection:
        trigger = await _trigger(connection, trigger_id)
        if trigger is None:
            return None, None, None, "gone"
        server = await find_server(connection, trigger.server_id)
        accepted = await _accepted_event(connection, trigger)
    if not server.enabled or not accepted:
        return trigger, server, None, "not_accepted"
    token = await token_for(_engine(), identity, server, _RUNNER.secret_key)
    if server.auth != "none" and token is None:
        return trigger, server, None, "credential_missing"
    return trigger, server, token, None


async def _set_problem(identity: Identity, trigger_id: uuid.UUID, problem: str) -> None:
    """Why a subscription for webhooks failed; it is tried again in about a minute."""
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text("UPDATE task_triggers SET problem = :problem, refresh_before = :retry WHERE id = :id"),
            {"id": trigger_id, "problem": problem, "retry": datetime.datetime.now(datetime.UTC) + RETRY_RENEWAL},
        )


def _problem_of(error: ServerError) -> str:
    return "unauthorized" if error.unauthorized else "unreachable"


async def _claim_poll(identity: Identity, trigger_id: uuid.UUID) -> datetime.datetime | None:
    """Take the due poll, so that no other sweep makes it: the time it is put off to, or `None` when it is not due."""
    claimed = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=MIN_POLL_SECONDS)).replace(
        microsecond=0
    )
    async with transaction(_engine(), identity) as connection:
        taken = (
            await connection.execute(
                text(
                    "UPDATE task_triggers SET next_poll_at = :claimed WHERE id = :id AND next_poll_at <= now()"
                    " RETURNING id"
                ),
                {"id": trigger_id, "claimed": claimed},
            )
        ).one_or_none()
    return None if taken is None else claimed


# The next poll is moved only if nothing moved it since it was taken, such as a change of the task.
_NEXT_POLL = (
    "next_poll_at = CASE WHEN next_poll_at = :claimed THEN now() + make_interval(secs => :seconds)"
    " ELSE next_poll_at END"
)


async def _poll(identity: Identity, trigger_id: uuid.UUID) -> None:
    """Poll the subscription, and fire once for each new event, by its ID (TSK-008)."""
    claimed = await _claim_poll(identity, trigger_id)
    if claimed is None:
        return
    trigger, server, token, problem = await _subscription(identity, trigger_id)
    if problem == "gone":
        return
    found = None
    if problem is None:
        try:
            found = await poll(server.target, token, trigger.event_name, trigger.event_arguments or {}, trigger.cursor)
        except ServerError as error:
            problem = _problem_of(error)
    if found is None:
        async with transaction(_engine(), identity) as connection:
            await connection.execute(
                text(f"UPDATE task_triggers SET problem = :problem, {_NEXT_POLL} WHERE id = :id"),  # noqa: S608
                {"id": trigger_id, "problem": problem, "claimed": claimed, "seconds": MIN_POLL_SECONDS},
            )
        return
    seconds = max(MIN_POLL_SECONDS, (found.next_poll_ms or 0) / 1000)
    async with transaction(_engine(), identity) as connection:
        for event in found.events:
            event_id = event.get("eventId")
            if not isinstance(event_id, str) or not event_id:
                continue
            await record_firing(
                connection,
                identity,
                task_id=trigger.task_id,
                trigger_id=trigger.id,
                kind="mcp_event",
                fire_key=f"{trigger.id}:{event_id}",
                event={"name": str(event.get("name", trigger.event_name))[:64], "data": event.get("data")},
            )
        await connection.execute(
            text(f"UPDATE task_triggers SET cursor = :cursor, problem = NULL, {_NEXT_POLL} WHERE id = :id"),  # noqa: S608
            {"id": trigger.id, "cursor": found.cursor, "seconds": seconds, "claimed": claimed},
        )


async def _renew(identity: Identity, trigger_id: uuid.UUID) -> None:
    """Subscribe for deliveries by webhook, or renew the subscription before it expires (TSK-008)."""
    trigger, server, token, problem = await _subscription(identity, trigger_id)
    if problem == "gone":
        return
    if problem is not None or not _RUNNER.public_origin:
        await _set_problem(identity, trigger_id, problem or "unreachable")
        return
    key = _RUNNER.secret_key
    if trigger.secret_ciphertext is None:
        secret = new_secret()
        async with transaction(_engine(), identity) as connection:
            await connection.execute(
                text("UPDATE task_triggers SET secret_ciphertext = :secret WHERE id = :id"),
                {"id": trigger.id, "secret": encrypt_labelled(key, trigger.id, SECRET_LABEL, secret)},
            )
    else:
        secret = decrypt_labelled(key, trigger.id, SECRET_LABEL, bytes(trigger.secret_ciphertext))
    address = f"{_RUNNER.public_origin.rstrip('/')}{EVENTS_PREFIX}{trigger.id}"
    try:
        subscribed = await subscribe(
            server.target, token, trigger.event_name, trigger.event_arguments or {}, address, secret, trigger.cursor
        )
    except ServerError as error:
        await _set_problem(identity, trigger_id, _problem_of(error))
        return
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text(
                "UPDATE task_triggers SET refresh_before = :refresh, cursor = :cursor, problem = NULL"
                " WHERE id = :id AND problem IS DISTINCT FROM 'terminated'"
            ),
            {"id": trigger.id, "refresh": subscribed.refresh_before, "cursor": subscribed.cursor},
        )


# --- Starting a firing (TSK-002) ---


@DBOS.workflow(name=FIRING_WORKFLOW)
async def firing_workflow(firing_id: str, tenant_id: str, owner_id: str) -> None:
    serialized = await _start_firing(firing_id, tenant_id, owner_id)
    if serialized is not None:
        await _enqueue_first_run(serialized, tenant_id, owner_id)


@DBOS.step()
async def _start_firing(firing_id: str, tenant_id: str, owner_id: str) -> str | None:
    """Start the firing's conversation and its first run, once: the run's workflow input, if it should run."""
    identity = owner(uuid.UUID(tenant_id), uuid.UUID(owner_id))
    async with transaction(_engine(), identity) as connection:
        firing = (
            await connection.execute(
                text("SELECT * FROM task_firings WHERE id = :id FOR UPDATE"), {"id": uuid.UUID(firing_id)}
            )
        ).one_or_none()
        if firing is None:
            return None
        if firing.status == "running" and firing.conversation_id is not None:
            # Started before a crash: its run is queued again, by the same ID.
            return await _first_run_input(connection, identity, firing)
        if firing.status != "waiting":
            return None
        running = (
            await connection.execute(
                text("SELECT 1 FROM task_firings WHERE task_id = :task AND status = 'running'"),
                {"task": firing.task_id},
            )
        ).one_or_none()
        if running is not None:
            return None
        state = await find_task(connection, firing.task_id)
        task = state.row
        passes = (await grant_check(connection, state)).passes
        conversation_id = uuid7()
        await connection.execute(
            text(
                "INSERT INTO conversations (id, tenant_id, owner_id, title, task_id, task_name, connection_id, model,"
                " reasoning, disabled_tools, disabled_skills, disabled_servers, last_message_at, created_at,"
                " updated_at) VALUES (:id, :tenant, :owner, '', :task, :name, :connection, :model, :reasoning,"
                " :disabled_tools, :disabled_skills, :disabled_servers, now(), now(), now())"
            ),
            {
                "id": conversation_id,
                "tenant": identity.tenant_id,
                "owner": identity.user_id,
                "task": task.id,
                "name": task.name,
                "connection": task.connection_id,
                "model": task.model,
                "reasoning": task.reasoning,
                "disabled_tools": list(task.disabled_tools),
                "disabled_skills": list(task.disabled_skills),
                "disabled_servers": list(task.disabled_servers),
            },
        )
        conversation = await find_conversation(connection, conversation_id, lock=True)
        await announce(connection, identity, event("conversation_created", conversation_id=conversation_id))
        run_id = uuid7()
        try:
            # A run refused by its budget starts, and fails in its conversation, which says why (MOD-004).
            await create_run(
                connection,
                identity,
                conversation,
                run_id=run_id,
                answers=None,
                user_text=task.instructions,
                budget=False,
            )
        except Exception:
            # No model to answer with: the firing ends without a conversation's run (TSK-009).
            logger.exception("a task's firing could not start its run")
            await connection.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": conversation_id})
            await connection.execute(
                text("UPDATE task_firings SET status = 'done', finished_at = now(), event = NULL WHERE id = :id"),
                {"id": firing.id},
            )
            return None
        await connection.execute(
            text("UPDATE runs SET task_grants = :grants WHERE id = :id"), {"id": run_id, "grants": passes}
        )
        await connection.execute(
            text(
                "UPDATE task_firings SET status = 'running', conversation_id = :conversation, started_at = now(),"
                " without_grants = :without WHERE id = :id"
            ),
            {"id": firing.id, "conversation": conversation_id, "without": not passes},
        )
        refreshed = (
            await connection.execute(text("SELECT * FROM task_firings WHERE id = :id"), {"id": firing.id})
        ).one()
        return await _first_run_input(connection, identity, refreshed)


async def _first_run_input(connection: AsyncConnection, identity: Identity, firing: Any) -> str | None:
    """The workflow input of the first run of the firing's conversation, from what the database holds."""
    conversation = await find_conversation(connection, firing.conversation_id)
    run = (
        await connection.execute(
            text(
                "SELECT id, connection_id, model_name, status FROM runs WHERE conversation_id = :id"
                " AND parent_run_id IS NULL"
            ),
            {"id": conversation.id},
        )
    ).one_or_none()
    task = (
        await connection.execute(
            text("SELECT instructions, uses_memory FROM tasks WHERE id = :id"), {"id": firing.task_id}
        )
    ).one_or_none()
    if run is None or task is None or run.status != "queued":
        return None
    defaults = (
        await connection.execute(text("SELECT base_instructions, additional_instructions, language FROM user_settings"))
    ).one_or_none()
    workflow_input = RunWorkflowInput(
        tenant_id=str(identity.tenant_id),
        user_id=str(identity.user_id),
        conversation_id=str(conversation.id),
        run_id=str(run.id),
        parent_run_id=None,
        user_text=task.instructions,
        connection_id=str(run.connection_id),
        model=run.model_name,
        reasoning=conversation.reasoning,
        disabled_tools=list(conversation.disabled_tools),
        disabled_skills=list(conversation.disabled_skills),
        disabled_servers=[str(server) for server in conversation.disabled_servers],
        base_instructions=None if defaults is None else defaults.base_instructions,
        additional_instructions=None if defaults is None else defaults.additional_instructions,
        language=None if defaults is None else defaults.language,
    )
    return replace(workflow_input, event=firing.event, use_memory=bool(task.uses_memory)).to_json()


@DBOS.step()
async def _enqueue_first_run(serialized: str, tenant_id: str, owner_id: str) -> None:
    workflow_input = RunWorkflowInput.from_json(serialized)
    try:
        await enqueue(_durable(), workflow_input)
    except Exception:
        logger.exception("a task's first run could not be queued")
        await fail_unqueued(
            _engine(), owner(uuid.UUID(tenant_id), uuid.UUID(owner_id)), uuid.UUID(workflow_input.run_id)
        )
