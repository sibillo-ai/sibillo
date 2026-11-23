"""Internet access as it is now, read again during a run (AGT-034, ADR-0115).

Its user turns a conversation's internet access on or off at any time; a run
reads it again before each call that needs it, and before each command, so
that a change is felt by the calls that follow it.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import text

from sibillo_server.database import transaction
from sibillo_server.gateway import RunDeps
from sibillo_server.tool_policy import Allowances


async def current_allowances(deps: RunDeps) -> Allowances:
    """The run's allowances, with internet access for the conversation and the turn as they are now."""
    async with transaction(deps.engine, deps.identity) as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.allowed_internet_access, r.turn_allows_internet_access FROM conversations c"
                    " JOIN runs r ON r.conversation_id = c.id WHERE c.id = :conversation AND r.id = :run"
                ),
                {"conversation": deps.conversation_id, "run": deps.run_id},
            )
        ).one_or_none()
    if row is None:
        return deps.allowances
    # A task's grant of internet access is the run's own, not the database's (TSK-004, ADR-0113).
    task_grant = deps.unattended and deps.allowances.turn_internet_access
    return replace(
        deps.allowances,
        internet_access=bool(row.allowed_internet_access),
        turn_internet_access=bool(row.turn_allows_internet_access) or task_grant,
    )
