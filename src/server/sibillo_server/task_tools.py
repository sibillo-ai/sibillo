"""The assistant proposes a task (TSK-006, ADR-0106).

`propose_task` takes the fields of a request to create a task. Every call is
asked, once, with the whole task in its approval request; only once the user
approves it does the tool run, and it saves the task after the same checks as
the API. A task's own runs can never use it: it cannot be granted.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from pydantic_ai import RunContext, Tool

from sibillo_server import errors, schemas
from sibillo_server.database import transaction
from sibillo_server.gateway import RunDeps
from sibillo_server.tasks import change, create


async def propose_task(
    ctx: RunContext[RunDeps],
    name: str,
    instructions: str,
    time_zone: str,
    triggers: list[dict[str, Any]],
    grants: list[dict[str, Any]] | None = None,
    uses_memory: bool = False,
    internet_access: bool = False,
    reasoning: str | None = None,
    disabled_tools: list[str] | None = None,
) -> str:
    """Propose a task the user wants done on its own, such as a press review every morning; the user approves it.

    Each time a trigger fires, the task starts a new conversation with its instructions, without the user.

    Args:
        name: A short name of the task.
        instructions: What to do each time, as the user would write it.
        time_zone: The user's IANA time zone, such as `Europe/Rome`.
        triggers: When it runs: `{"kind": "schedule", "start": "<YYYY-MM-DDTHH:MM:SS in time_zone>", "recurrence":
            ["RRULE:..."]}`, with lines of iCalendar recurrence (RFC 5545) such as
            `RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=2`, `EXDATE:...` or `RDATE:...`, at most every 15 minutes; no
            recurrence for once, at the start. Or `{"kind": "webhook"}`.
        grants: The calls it may make without asking, nobody being there to approve: `{"tool": "<tool>",
            "arguments": null}` for any arguments, or with the exact arguments. Grant only what it needs.
            The web tools take no grants: they follow `internet_access`.
        uses_memory: Whether it uses what you remember about the user.
        internet_access: Whether its runs have internet access, for the web tools and the sandbox's network.
        reasoning: `off`, `on` or `deep`.
        disabled_tools: Tools it does without.
    """
    fields: dict[str, Any] = {
        "name": name,
        "instructions": instructions,
        "time_zone": time_zone,
        "triggers": triggers,
        "grants": grants or [],
        "uses_memory": uses_memory,
        "internet_access": internet_access,
    }
    if reasoning is not None:
        fields["reasoning"] = reasoning
    if disabled_tools is not None:
        fields["disabled_tools"] = disabled_tools
    try:
        request = schemas.CreateTaskRequest.model_validate(fields)
    except ValidationError as error:
        return f"The task was not saved: {error.error_count()} of its fields are not valid."
    deps = ctx.deps
    try:
        async with transaction(deps.engine, deps.identity) as connection:
            task = await create(connection, deps.identity, request, deps.public_origin)
    except errors.ApiError as error:
        detail = error.extra.get("detail")
        return f"The task was not saved ({error.code}){f': {detail}' if detail else ''}."
    except Exception:
        return "The task was not saved: it could not be stored now."
    webhook = (
        " Its webhook address is shown in the task's settings, where the user can replace it."
        if any(trigger.kind == "webhook" for trigger in task.triggers)
        else ""
    )
    return f"Saved the task {task.name!r}; the user can change, pause or delete it in their settings.{webhook}"


async def update_task(
    ctx: RunContext[RunDeps],
    task_id: str,
    name: str | None = None,
    instructions: str | None = None,
    time_zone: str | None = None,
    paused: bool | None = None,
    grants: list[dict[str, Any]] | None = None,
    uses_memory: bool | None = None,
    internet_access: bool | None = None,
    reasoning: str | None = None,
    disabled_tools: list[str] | None = None,
) -> str:
    """Change one of the user's tasks, such as its instructions or grants, or pause or resume it; the user approves it.

    Only the fields given change; `grants` replaces every grant. `list_tasks` gives each task's ID.

    Args:
        task_id: The task's ID.
        name: Its new name.
        instructions: Its new instructions.
        time_zone: Its new IANA time zone.
        paused: Whether it stops firing, or fires again.
        grants: Its grants, all of them, as `propose_task` takes them.
        uses_memory: Whether it uses what you remember about the user.
        internet_access: Whether its runs have internet access.
        reasoning: `off`, `on` or `deep`.
        disabled_tools: Tools it does without.
    """
    given = {
        "name": name,
        "instructions": instructions,
        "time_zone": time_zone,
        "paused": paused,
        "grants": grants,
        "uses_memory": uses_memory,
        "internet_access": internet_access,
        "reasoning": reasoning,
        "disabled_tools": disabled_tools,
    }
    try:
        task = uuid.UUID(task_id)
        request = schemas.UpdateTaskRequest.model_validate(
            {key: value for key, value in given.items() if value is not None}
        )
    except (ValueError, ValidationError):
        return "The task was not changed: the change is not valid."
    deps = ctx.deps
    try:
        async with transaction(deps.engine, deps.identity) as connection:
            changed = await change(connection, deps.identity, task, request)
    except errors.ApiError as error:
        detail = error.extra.get("detail")
        return f"The task was not changed ({error.code}){f': {detail}' if detail else ''}."
    except Exception:
        return "The task was not changed: it could not be stored now."
    return f"Changed the task {changed.name!r}."


TOOLS = (Tool(propose_task), Tool(update_task))
