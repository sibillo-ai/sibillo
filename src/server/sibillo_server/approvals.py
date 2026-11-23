"""Tool permissions, approvals and audit events in a run (AGT-002, AGT-004, AGT-006, AGT-008, ADR-0033, ADR-0090).

The capability takes away the tools a user's permissions deny, ends the run
with an approval request for each call that needs one, and records an audit
event for every call. A call needing approval raises `ApprovalRequired`
before the tool runs: the run ends with `DeferredToolRequests`, whose
metadata says why and with which scopes, and the answer starts a new run in
which the call is approved, its scope and reason in its metadata.

Tool calls are not durable steps: a run replayed after a crash calls its
tools again, and records the attempt again (ADR-0034).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server.credentials import uuid7
from sibillo_server.database import Identity, transaction
from sibillo_server.gateway import RunDeps
from sibillo_server.internet import current_allowances
from sibillo_server.mcp_runs import offered_names, shown
from sibillo_server.skills import save_preview
from sibillo_server.task_policy import NOT_GRANTED, Grant, covering, refusal
from sibillo_server.tool_policy import (
    DECLARATIONS,
    DENIED_INTERNET_ACCESS,
    INTERNET_TOOLS,
    TASK_PROPOSALS,
    decide,
    denied,
    has_external_effects,
    has_untrusted_content,
)

# The memory tools that change or delete an item (ADR-0127).
MEMORY_CHANGES = frozenset({"update_memory", "forget"})


async def _users_item(deps: RunDeps, item_id: Any) -> str | None:
    """The text of a trusted memory item the call names, which the user wrote or saved; None otherwise."""
    try:
        parsed = uuid.UUID(str(item_id))
    except ValueError:
        return None
    async with transaction(deps.engine, deps.identity) as connection:
        found = (
            await connection.execute(
                text("SELECT text FROM memory_items WHERE id = :id AND NOT untrusted"), {"id": parsed}
            )
        ).scalar_one_or_none()
    return None if found is None else str(found)


# Saves a folder as a skill: its approval shows the skill (AGT-026, ADR-0124).
SAVE_SKILL = "save_skill"

logger = logging.getLogger(__name__)


async def record(
    connection: AsyncConnection,
    identity: Identity,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    tool_call_id: str,
    tool: str,
    outcome: str,
    scope: str | None = None,
    reason: str | None = None,
    attempt: bool = False,
) -> None:
    """Write the audit event of a call, or complete it: a call is recorded once, its attempts counted (AGT-008)."""
    await connection.execute(
        text(
            "INSERT INTO audit_events (id, tenant_id, owner_id, conversation_id, run_id, tool_call_id, tool, outcome,"
            " scope, reason, attempts, created_at) VALUES (:id, :tenant, :owner, :conversation, :run, :call, :tool,"
            " :outcome, :scope, :reason, :attempts, now())"
            " ON CONFLICT (run_id, tool_call_id) DO UPDATE SET outcome = EXCLUDED.outcome,"
            " scope = EXCLUDED.scope, reason = EXCLUDED.reason,"
            " attempts = audit_events.attempts + EXCLUDED.attempts"
        ),
        {
            "id": uuid7(),
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "conversation": conversation_id,
            "run": run_id,
            "call": tool_call_id,
            "tool": tool,
            "outcome": outcome,
            "scope": scope,
            "reason": reason,
            "attempts": 1 if attempt else 0,
        },
    )


def _granted(deps: RunDeps, tool: str, arguments: dict[str, Any]) -> Grant | None:
    """The task's grant that covers the call, if one does and may still be used (TSK-004, ADR-0106)."""
    grants = [grant for grant in deps.grants if isinstance(grant, Grant)]
    found = covering(grants, tool, arguments)
    if found is None or refusal(found, deps.permissions, offered_names(deps)) is not None:
        return None
    return found


class Approvals(AbstractCapability[RunDeps]):
    """Takes denied tools away, asks before the calls that need approval, and audits every call."""

    async def prepare_tools(self, ctx: RunContext[RunDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
        away = denied(ctx.deps.permissions)
        return [tool for tool in tool_defs if tool.name not in away]

    async def after_model_request(
        self, ctx: RunContext[RunDeps], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        # A call to a tool the user's permissions deny is refused, and recorded as such; so is a call to a tool that
        # is off, for the user or the conversation, or that no one offered (AGT-008, ADR-0132).
        deps = ctx.deps
        away = denied(deps.permissions)
        offered = offered_names(deps)
        refused: list[tuple[ToolCallPart, str | None]] = []
        for part in response.parts:
            if not isinstance(part, ToolCallPart):
                continue
            if part.tool_name in away:
                refused.append((part, "permission"))
            elif part.tool_name in deps.disabled_tools or (
                part.tool_name not in DECLARATIONS and part.tool_name not in offered
            ):
                refused.append((part, None))
        if refused:
            async with transaction(deps.engine, deps.identity) as connection:
                for part, reason in refused:
                    await record(
                        connection,
                        deps.identity,
                        conversation_id=deps.conversation_id,
                        run_id=deps.run_id,
                        tool_call_id=part.tool_call_id,
                        tool=part.tool_name[:64],
                        outcome="refused",
                        reason=reason,
                    )
        return response

    async def wrap_tool_execute(
        self,
        ctx: RunContext[RunDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: Any,
    ) -> Any:
        deps = ctx.deps
        run_id = deps.run_id
        # Internet access is read again before each call that needs it: its user may have changed it (ADR-0115).
        allowances = await current_allowances(deps) if call.tool_name in INTERNET_TOOLS else deps.allowances
        if ctx.tool_call_approved:
            # Approved by the user: the call was made by the run the answer continues.
            metadata = cast(dict[str, Any], ctx.tool_call_metadata or {})
            outcome, scope, reason = "approved", metadata.get("scope"), metadata.get("reason")
            run_id = deps.parent_run_id or run_id
            if reason == "internet_access":
                # Internet access covers the call's way out, not what else its tool needs, such as the
                # approval its permission asks for (AGT-002, AGT-034).
                again = decide(call.tool_name, deps.permissions, False, allowances)
                if again.request is not None:
                    raise ApprovalRequired(
                        metadata={"reason": again.request.reason, "scopes": list(again.request.scopes)}
                    )
        else:
            untrusted = deps.untrusted or has_untrusted_content(ctx.messages)
            # What the user wrote in memory is changed or deleted in an untrusted run only if they say so (ADR-0127).
            if untrusted and call.tool_name in MEMORY_CHANGES:
                guarded = await _users_item(deps, args.get("id"))
                if guarded is not None:
                    if deps.unattended:
                        async with transaction(deps.engine, deps.identity) as connection:
                            await record(
                                connection,
                                deps.identity,
                                conversation_id=deps.conversation_id,
                                run_id=run_id,
                                tool_call_id=call.tool_call_id,
                                tool=call.tool_name,
                                outcome="not_granted",
                                reason="untrusted_content",
                            )
                        return NOT_GRANTED
                    verb = "Forget" if call.tool_name == "forget" else "Replace"
                    raise ApprovalRequired(
                        metadata={
                            "reason": "untrusted_content",
                            "scopes": ["once"],
                            "approval": {
                                "action": f'{verb} the memory item you wrote: "{guarded}"',
                                "destination": "Your memory, which your later conversations are given",
                            },
                        }
                    )
            decision = decide(call.tool_name, deps.permissions, untrusted, allowances)
            if decision.denied:
                # The user denied internet access in this turn: denied again, without asking (AGT-034).
                async with transaction(deps.engine, deps.identity) as connection:
                    await record(
                        connection,
                        deps.identity,
                        conversation_id=deps.conversation_id,
                        run_id=run_id,
                        tool_call_id=call.tool_call_id,
                        tool=call.tool_name,
                        outcome="denied",
                        reason="internet_access",
                    )
                return DENIED_INTERNET_ACCESS
            if decision.request is not None and deps.unattended:
                # Nobody watches a task's run: a grant covers the call, or it is denied without asking (TSK-004).
                if _granted(deps, call.tool_name, args) is None:
                    async with transaction(deps.engine, deps.identity) as connection:
                        await record(
                            connection,
                            deps.identity,
                            conversation_id=deps.conversation_id,
                            run_id=run_id,
                            tool_call_id=call.tool_call_id,
                            tool=call.tool_name,
                            outcome="not_granted",
                            reason=decision.request.reason,
                        )
                    return NOT_GRANTED
                outcome, scope, reason = "granted", None, decision.request.reason
            elif decision.request is not None:
                metadata: dict[str, Any] = {"reason": decision.request.reason, "scopes": list(decision.request.scopes)}
                if decision.request.reason == "internet_access":
                    # One request of the run for all its calls that need internet access (AGT-034, ADR-0113).
                    metadata["run_id"] = str(deps.run_id)
                    metadata["untrusted_content"] = untrusted
                # A remote MCP server's tool says what it is and where the call goes (AGT-018, ADR-0099).
                if (described := shown(deps, call.tool_name)) is not None:
                    metadata["approval"] = described
                # A save shows the skill its folder holds now, and saves only that (AGT-026, ADR-0124).
                if call.tool_name == SAVE_SKILL:
                    preview = await save_preview(deps, str(args.get("path", "")))
                    if isinstance(preview, str):
                        return f"The skill was not saved: {preview}"
                    skill = cast(dict[str, Any], preview["skill"])
                    metadata["skill_digest"] = preview["digest"]
                    metadata["approval"] = {
                        "action": f"Save the skill {skill['name']}",
                        "destination": "Your skills, given to your later conversations"
                        + (", replacing your skill of that name" if skill["replaces"] else ""),
                        "data": skill["description"],
                        "skill": skill,
                    }
                # A proposed task says whether the run holds untrusted content (TSK-006, ADR-0106).
                if call.tool_name in TASK_PROPOSALS:
                    metadata["untrusted_content"] = untrusted
                raise ApprovalRequired(metadata=metadata)
            else:
                outcome = "not_needed" if decision.allowed is None else "allowed"
                scope, reason = decision.allowed, None
        async with transaction(deps.engine, deps.identity) as connection:
            await record(
                connection,
                deps.identity,
                conversation_id=deps.conversation_id,
                run_id=run_id,
                tool_call_id=call.tool_call_id,
                tool=call.tool_name,
                outcome=outcome,
                scope=scope,
                reason=reason,
                attempt=has_external_effects(call.tool_name),
            )
        return await handler(args)
