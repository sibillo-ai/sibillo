"""Delegating work to delegated runs (AGT-035 to AGT-038, ADR-0136).

The `delegate` tool records a delegation with its run, queues the delegated
run's durable workflow, and waits for its report. The workflow's ID is
derived from the delegating run and the call, so that a run started again
after a crash, which calls its tools again (ADR-0034), waits for the same
delegated run. The worker executes the workflow on the agent itself, with a
fresh context and the tools this module leaves it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from dbos import DBOSClient
from pydantic_ai import RunContext, Tool, ToolReturn
from pydantic_ai.messages import ModelResponse, ToolCallPart
from sqlalchemy import text

from sibillo_server.database import transaction
from sibillo_server.durable import APPLICATION_VERSION, DELEGATION_QUEUE, DELEGATION_WORKFLOW
from sibillo_server.gateway import RunDeps, storable
from sibillo_server.tool_policy import (
    PROVENANCE_ORIGIN,
    REQUEST_INTERNET_ACCESS,
    TASK_PROPOSALS,
    decide,
    has_untrusted_content,
)

DELEGATE = "delegate"
# Delegated runs of one run at once, and delegations of one run (AGT-035).
AT_ONCE = 4
PER_RUN = 10
POLL_SECONDS = 0.3
# What a delegated run is not offered: what speaks to the user or outlasts the work (AGT-036, ADR-0136).
WITHHELD = frozenset(
    {
        DELEGATE,
        "ask_user_question",
        "write_plan",
        "read_plan",
        "add_task",
        "update_task_status",
        "update_task_statuses",
        "remove_task",
        "offer_download",
        "remember",
        "update_memory",
        "forget",
        "save_skill",
        REQUEST_INTERNET_ACCESS,
        *TASK_PROPOSALS,
    }
)
FINAL = frozenset({"completed", "failed", "cancelled"})

# What a delegated run is told of its place (ADR-0136).
DELEGATED_INSTRUCTIONS = (
    "The assistant of a conversation delegated a piece of work to you, and its brief is your only message: you"
    " do not see the conversation. Nobody can answer you: you cannot ask the user anything, and calls that need"
    " the user's approval are denied without asking. Do the work with what you have. Other delegated work may"
    " use the same sandbox at the same time, so keep the files you make in a folder of your own, named for the"
    " work. End with a complete report for the assistant that delegated it: what you found or did, where your"
    " files are, and what you could not do and why."
)
TOO_MANY = (
    f"Not delegated: this answer has delegated {PER_RUN} pieces of work already, the most one answer may. Do this"
    " piece yourself, or say what is left, so that it can be delegated after the user's next message."
)


@dataclass(frozen=True)
class DelegationInput:
    """The input of a delegated run's durable workflow: identifiers and settings, never the brief or secrets.

    Workflow inputs are stored without row-level security (TEN-009); the brief is read from the delegation.
    """

    tenant_id: str
    user_id: str
    conversation_id: str
    run_id: str
    delegation_id: str
    connection_id: str
    model: str
    provider: str = ""
    model_name: str = ""
    reasoning: str = "on"
    disabled_tools: list[str] = field(default_factory=list[str])
    base_instructions: str | None = None
    language: str | None = None
    skills: list[str] = field(default_factory=list[str])
    temporary: bool = False
    # The delegating run's allowances, and whether it is a task's run that nobody watches, with its grants.
    turn_internet_access: bool = False
    internet_access: bool = False
    allowed_tools: list[str] = field(default_factory=list[str])
    turn_denied_internet_access: bool = False
    unattended: bool = False
    grants: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> DelegationInput:
        known = {item.name for item in fields(cls)}
        return cls(**{name: item for name, item in json.loads(value).items() if name in known})


class _Durable:
    client: DBOSClient | None = None


_DURABLE = _Durable()


def configure(client: DBOSClient) -> None:
    """The client that queues delegated runs; set by the worker before it launches."""
    _DURABLE.client = client


def delegation_id(run_id: uuid.UUID, tool_call_id: str) -> uuid.UUID:
    """The same delegation, and workflow, for the same call of the same run (ADR-0136)."""
    return uuid.uuid5(run_id, f"delegation:{tool_call_id}")


def _input(deps: RunDeps, delegation: uuid.UUID) -> DelegationInput:
    grants: list[dict[str, Any]] = [
        {"tool": grant.tool, "arguments": None if grant.arguments is None else dict(grant.arguments)}
        for grant in deps.grants
    ]
    return DelegationInput(
        tenant_id=str(deps.identity.tenant_id),
        user_id=str(deps.identity.user_id),
        conversation_id=str(deps.conversation_id),
        run_id=str(deps.run_id),
        delegation_id=str(delegation),
        connection_id=str(deps.connection_id),
        model=deps.connection_model,
        provider=deps.provider,
        model_name=deps.model,
        reasoning=deps.reasoning,
        disabled_tools=sorted(deps.disabled_tools | WITHHELD),
        base_instructions=deps.base_instructions,
        language=deps.language,
        skills=[skill.name for skill in deps.skills or ()],
        temporary=deps.temporary,
        turn_internet_access=deps.allowances.turn_internet_access,
        internet_access=deps.allowances.internet_access,
        allowed_tools=sorted(deps.allowances.tools),
        turn_denied_internet_access=deps.allowances.turn_denied_internet_access,
        unattended=deps.unattended,
        grants=grants,
    )


async def _record(deps: RunDeps, delegation: uuid.UUID, tool_call_id: str, brief: str, untrusted: bool) -> bool:
    """Record the delegation, unless the run already did for this call; False when the run has made its limit."""
    async with transaction(deps.engine, deps.identity) as connection:
        # One call at a time counts the run's delegations.
        await connection.execute(text("SELECT 1 FROM runs WHERE id = :id FOR UPDATE"), {"id": deps.run_id})
        found = (
            await connection.execute(text("SELECT 1 FROM delegations WHERE id = :id"), {"id": delegation})
        ).one_or_none()
        if found is not None:
            return True
        made = (
            await connection.execute(text("SELECT count(*) FROM delegations WHERE run_id = :id"), {"id": deps.run_id})
        ).scalar_one()
        if made >= PER_RUN:
            return False
        await connection.execute(
            text(
                "INSERT INTO delegations (id, tenant_id, owner_id, conversation_id, run_id, tool_call_id, brief,"
                " status, untrusted, created_at) VALUES (:id, :tenant, :owner, :conversation, :run, :call, :brief,"
                " 'queued', :untrusted, now())"
            ),
            {
                "id": delegation,
                "tenant": deps.identity.tenant_id,
                "owner": deps.identity.user_id,
                "conversation": deps.conversation_id,
                "run": deps.run_id,
                "call": tool_call_id,
                "brief": storable(brief),
                "untrusted": untrusted,
            },
        )
    return True


async def _wait(deps: RunDeps, delegation: uuid.UUID) -> Any:
    """The delegation once it has ended; a delegating run that was stopped stops waiting (CNV-003)."""
    while True:
        async with transaction(deps.engine, deps.identity) as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT d.status, d.report, d.untrusted, r.status AS run_status FROM delegations d"
                        " JOIN runs r ON r.id = d.run_id WHERE d.id = :id"
                    ),
                    {"id": delegation},
                )
            ).one_or_none()
        if row is None or row.run_status == "cancelled":
            raise asyncio.CancelledError
        if row.status in FINAL:
            return row
        await asyncio.sleep(POLL_SECONDS)


def _calls(ctx: RunContext[RunDeps], own: str, brief: str, untrusted: bool) -> list[tuple[str, str]]:
    """The calls of `delegate` to start now, in the order the model made them: this one, and the others of the
    same answer that need no approval.

    A durable run with a sandbox runs its tool calls one after another, so that a replay gives each its own
    results; the first call of an answer therefore starts them all, and each waits for its own (ADR-0136). A
    call that needs approval, or answers one, starts only by itself, once it may run.
    """
    if ctx.tool_call_approved or decide(DELEGATE, ctx.deps.permissions, untrusted, ctx.deps.allowances).request:
        return [(own, brief)]
    response = next((message for message in reversed(ctx.messages) if isinstance(message, ModelResponse)), None)
    found: list[tuple[str, str]] = []
    for part in response.parts if response is not None else ():
        if not isinstance(part, ToolCallPart) or part.tool_name != DELEGATE:
            continue
        if part.tool_call_id == own:
            found.append((own, brief))
            continue
        try:
            other = part.args_as_dict().get("brief")
        except ValueError:
            continue
        if isinstance(other, str):
            found.append((part.tool_call_id, other))
    return found if any(call == own for call, _ in found) else [(own, brief)]


async def _start(deps: RunDeps, client: DBOSClient, tool_call_id: str, brief: str, untrusted: bool) -> bool:
    """Record a delegation and queue its delegated run, both once; False when the run has made its limit."""
    delegation = delegation_id(deps.run_id, tool_call_id)
    if not await _record(deps, delegation, tool_call_id, brief, untrusted):
        return False
    await client.enqueue_async(
        {
            "queue_name": DELEGATION_QUEUE,
            "workflow_name": DELEGATION_WORKFLOW,
            "workflow_id": str(delegation),
            "queue_partition_key": str(deps.run_id),
            "app_version": APPLICATION_VERSION,
        },
        _input(deps, delegation).to_json(),
    )
    return True


async def delegate(ctx: RunContext[RunDeps], brief: str) -> ToolReturn | str:
    """Hand a self-contained piece of work to a delegated run, and get back its report.

    The delegated run is the assistant again, with a fresh context: the brief is all it knows, so write
    everything it needs into it, and say what its report must hold. It works in this conversation's sandbox,
    with your tools except those that speak to the user, keep anything, or delegate again. It cannot ask the
    user anything, and calls that need the user's approval are denied to it, so do such calls yourself.
    Several calls in one answer run at the same time: use them for independent parts of a piece of work, for
    long work whose details you do not need, or for a second opinion formed from the brief alone. What a
    delegated run read counts as read by you.

    Args:
        brief: The work, written to stand on its own: the goal, what is known, where files are, and what to
            report.
    """
    deps = ctx.deps
    client = _DURABLE.client
    if client is None or deps.delegated_by is not None or deps.connection_id is None:
        return "Delegation is not available here."
    tool_call_id = ctx.tool_call_id or ""
    untrusted = deps.untrusted or has_untrusted_content(ctx.messages)
    started = True
    for call, said in _calls(ctx, tool_call_id, brief, untrusted):
        made = await _start(deps, client, call, said, untrusted)
        if call == tool_call_id:
            started = made
    if not started:
        return TOO_MANY
    ended = await _wait(deps, delegation_id(deps.run_id, tool_call_id))
    return ToolReturn(
        return_value=str(ended.report or ""), metadata={PROVENANCE_ORIGIN: {"untrusted": bool(ended.untrusted)}}
    )


TOOLS = (Tool(delegate),)
