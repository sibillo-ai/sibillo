"""The assistant reads the user's tasks and earlier conversations (TSK-013, AGT-032, AGT-033, ADR-0107).

Everything they read is the user's own, under row-level security. What they
show of another conversation is untrusted content only when that
conversation holds untrusted content on its active path: the result says
so in its metadata, and the run counts it as provenance (AGT-003). They
never reach a temporary conversation, what a rewind removed, or the
conversation the run is in.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic_ai import RunContext, Tool, ToolReturn
from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server.conversations import path_runs, stored_messages
from sibillo_server.database import transaction
from sibillo_server.folders import search_rows
from sibillo_server.gateway import RunDeps
from sibillo_server.tool_policy import PROVENANCE_ORIGIN, has_untrusted_content

SEARCH_RESULTS = 10
EXCERPT_CHARS = 300
# What a conversation read gives the model at most; the output limits keep the rest aside (AGT-014).
READ_CHARS = 40_000
LATEST_FIRINGS = 5


def _provenance(untrusted: bool) -> dict[str, Any]:
    return {PROVENANCE_ORIGIN: {"untrusted": untrusted}}


async def _path_messages(connection: AsyncConnection, conversation_id: uuid.UUID, last: uuid.UUID | None) -> list[Any]:
    """The stored messages of the conversation's active path, in order (ADR-0068)."""
    if last is None:
        return []
    path = await path_runs(connection, conversation_id, last)
    stored = await stored_messages(connection, [run.id for run in path])
    return [message for run in path for message in ModelMessagesTypeAdapter.validate_python(stored[run.id])]


async def _readable(connection: AsyncConnection, deps: RunDeps, conversation_id: uuid.UUID) -> Any:
    """The conversation, if the run may read it: the user's, not temporary, and not the run's own."""
    if conversation_id == deps.conversation_id:
        return None
    return (
        await connection.execute(
            text(
                "SELECT id, title, active_run_id, last_message_at FROM conversations WHERE id = :id AND NOT temporary"
            ),
            {"id": conversation_id},
        )
    ).one_or_none()


async def search_conversations(ctx: RunContext[RunDeps], query: str) -> ToolReturn:
    """Search the user's earlier conversations by words of their titles and messages.

    Args:
        query: The words to look for.
    """
    deps = ctx.deps
    async with transaction(deps.engine, deps.identity) as connection:
        rows = [
            row
            for row in await search_rows(connection, query[:200], SEARCH_RESULTS + 1)
            if row.id != deps.conversation_id
        ]
        found: list[dict[str, Any]] = []
        untrusted = False
        for row in rows[:SEARCH_RESULTS]:
            conversation = await _readable(connection, deps, row.id)
            if conversation is None:
                continue
            untrusted = untrusted or has_untrusted_content(
                await _path_messages(connection, row.id, conversation.active_run_id)
            )
            found.append(
                {
                    "conversation_id": str(row.id),
                    "title": row.title,
                    "last_message_at": row.last_message_at.isoformat(),
                    "excerpt": (row.content or "")[:EXCERPT_CHARS],
                }
            )
    result = json.dumps({"conversations": found}, ensure_ascii=False) if found else "No conversation matches."
    return ToolReturn(return_value=result, metadata=_provenance(untrusted))


def _rendered(messages: list[Any]) -> str:
    """What the user and the assistant wrote, and the tools called by name, without their results."""
    lines: list[str] = []
    for message in messages:
        for part in message.parts:
            kind = part.part_kind
            if kind == "user-prompt":
                content: Any = part.content
                said = (
                    content
                    if isinstance(content, str)
                    else " ".join(str(item) for item in content if isinstance(item, str))
                )
                lines.append(f"User: {said}")
            elif kind == "text":
                lines.append(f"Assistant: {part.content}")
            elif kind == "tool-call":
                lines.append(f"(The assistant used {part.tool_name}.)")
    return "\n\n".join(lines)


async def read_conversation(ctx: RunContext[RunDeps], conversation_id: str) -> ToolReturn:
    """Read one of the user's earlier conversations: what they and you wrote, and which tools were used.

    Args:
        conversation_id: The conversation's ID, as `search_conversations` or `list_tasks` give it.
    """
    deps = ctx.deps
    try:
        wanted = uuid.UUID(conversation_id)
    except ValueError:
        return ToolReturn(return_value="No such conversation.", metadata=_provenance(False))
    async with transaction(deps.engine, deps.identity) as connection:
        conversation = await _readable(connection, deps, wanted)
        if conversation is None:
            return ToolReturn(return_value="No such conversation.", metadata=_provenance(False))
        messages = await _path_messages(connection, wanted, conversation.active_run_id)
    rendered = _rendered(messages)
    if len(rendered) > READ_CHARS:
        rendered = rendered[:READ_CHARS] + "\n\n[The rest of the conversation is cut.]"
    heading = (
        f"Conversation {conversation.title or '(untitled)'}, last message {conversation.last_message_at.isoformat()}:"
    )
    return ToolReturn(return_value=f"{heading}\n\n{rendered}", metadata=_provenance(has_untrusted_content(messages)))


async def list_tasks(ctx: RunContext[RunDeps]) -> str:
    """List the user's tasks, with their triggers and grants, and how their latest firings went."""
    deps = ctx.deps
    async with transaction(deps.engine, deps.identity) as connection:
        tasks = (
            await connection.execute(
                text("SELECT id, name, instructions, time_zone, paused_at FROM tasks ORDER BY name, id")
            )
        ).all()
        listed: list[dict[str, Any]] = []
        for task in tasks:
            triggers = (
                await connection.execute(
                    text(
                        "SELECT kind, schedule_start, recurrence, next_fire_at, event_name FROM task_triggers"
                        " WHERE task_id = :id ORDER BY created_at, id"
                    ),
                    {"id": task.id},
                )
            ).all()
            grants = (
                await connection.execute(
                    text("SELECT tool, arguments FROM task_grants WHERE task_id = :id ORDER BY created_at, id"),
                    {"id": task.id},
                )
            ).all()
            firings = (
                await connection.execute(
                    text(
                        "SELECT f.trigger_kind, f.status, f.started_at, f.conversation_id, c.title,"
                        " (SELECT r.status FROM runs r WHERE r.conversation_id = c.id AND r.parent_run_id IS NULL"
                        "  LIMIT 1) AS outcome"
                        " FROM task_firings f LEFT JOIN conversations c ON c.id = f.conversation_id"
                        " WHERE f.task_id = :id ORDER BY f.created_at DESC LIMIT :limit"
                    ),
                    {"id": task.id, "limit": LATEST_FIRINGS},
                )
            ).all()
            listed.append(
                {
                    "task_id": str(task.id),
                    "name": task.name,
                    "instructions": task.instructions,
                    "time_zone": task.time_zone,
                    "paused": task.paused_at is not None,
                    "triggers": [
                        {
                            "kind": trigger.kind,
                            "start": None
                            if trigger.schedule_start is None
                            else trigger.schedule_start.isoformat(timespec="seconds"),
                            "recurrence": trigger.recurrence,
                            "next_firing": None if trigger.next_fire_at is None else trigger.next_fire_at.isoformat(),
                            "event": trigger.event_name,
                        }
                        for trigger in triggers
                    ],
                    "grants": [{"tool": grant.tool, "arguments": grant.arguments} for grant in grants],
                    "latest_firings": [
                        {
                            "fired_by": firing.trigger_kind,
                            "started_at": None if firing.started_at is None else firing.started_at.isoformat(),
                            "outcome": firing.outcome or firing.status,
                            "conversation_id": None if firing.conversation_id is None else str(firing.conversation_id),
                            "conversation_title": firing.title,
                        }
                        for firing in firings
                    ],
                }
            )
    return json.dumps({"tasks": listed}, ensure_ascii=False) if listed else "The user has no tasks."


TOOLS = (Tool(list_tasks), Tool(search_conversations), Tool(read_conversation))
