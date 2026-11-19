"""What a task may do unattended: its grants, and the check that they never complete the lethal trifecta.

TSK-004, TSK-005, ADR-0106. A fixed grant covers one tool with all of its
arguments; an open grant covers the tool with any arguments. A grant never
covers a consequential tool, a tool a tool permission asks or denies, the
tool that proposes a task, or an open call to a remote MCP server's tool.
Together, a task's grants, its memory and its event triggers never reach
private data, untrusted content and an open way out at once.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sibillo_server.tool_policy import (
    CONSEQUENTIAL,
    DECLARATIONS,
    PROPOSE_TASK,
    SERVER_CLASSES,
    CapabilityClass,
    Permissions,
    effective,
    is_server_tool,
)

# Tools of the agent that a user has no switch for, and that a grant never names.
# The assistant's tool that proposes a task is never granted, so that a task never creates tasks (TSK-006).
UNGRANTABLE = frozenset({PROPOSE_TASK, "read_tool_result", "load_capability"})
# The names `GrantCheck` gives the sources that are not tools.
MEMORY = "memory"
EVENT_TRIGGER = "event_trigger"
# What the model is told of a call that needed approval in a task's run, with no grant covering it.
NOT_GRANTED = (
    "This call needs the user's approval, and this task's grants do not cover it, so it was denied without asking:"
    " nobody is watching this task's run. Say in your answer what you could not do, so the user can do it later."
)


@dataclass(frozen=True)
class Grant:
    """A grant of a task: a fixed one with its `arguments`, an open one without."""

    tool: str
    arguments: Mapping[str, Any] | None

    @property
    def fixed(self) -> bool:
        return self.arguments is not None

    def covers(self, tool: str, arguments: Mapping[str, Any]) -> bool:
        return self.tool == tool and (self.arguments is None or dict(self.arguments) == dict(arguments))


def classes_of(tool: str) -> frozenset[CapabilityClass]:
    if is_server_tool(tool):
        return SERVER_CLASSES
    declaration = DECLARATIONS.get(tool)
    return frozenset() if declaration is None else declaration.classes


def refusal(grant: Grant, permissions: Permissions, server_tools: Iterable[str] = ()) -> str | None:
    """Why the grant cannot be given or used, or `None` when it can (TSK-004).

    `server_tools` are the names of the remote MCP servers' tools the user may
    be offered, as `<prefix>__<tool>`.
    """
    if grant.tool in UNGRANTABLE:
        return "not_grantable"
    if is_server_tool(grant.tool):
        if grant.tool not in set(server_tools):
            return "not_offered"
        if not grant.fixed:
            return "open_server_tool"
        if any(permissions.classes.get(name) in ("ask", "deny") for name in SERVER_CLASSES):
            return "permission"
        return None
    declaration = DECLARATIONS.get(grant.tool)
    if declaration is None:
        return "unknown_tool"
    if CONSEQUENTIAL & declaration.classes:
        return "consequential"
    if effective(grant.tool, permissions).setting in ("ask", "deny"):
        return "permission"
    return None


@dataclass(frozen=True)
class Check:
    """The sources of each element of the lethal trifecta in a task (TSK-005)."""

    private_data: tuple[str, ...]
    untrusted_content: tuple[str, ...]
    external_communication: tuple[str, ...]

    @property
    def passes(self) -> bool:
        return not (self.private_data and self.untrusted_content and self.external_communication)


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def check(grants: Iterable[Grant], *, memory: bool, event_trigger: bool) -> Check:
    """The check of TSK-005: `memory` when the task uses it and it is on for the user; `event_trigger` when it has
    a webhook trigger or a trigger on an event."""
    grants = list(grants)
    private = [grant.tool for grant in grants if "reads_private_data" in classes_of(grant.tool)]
    untrusted = [grant.tool for grant in grants if "ingests_untrusted" in classes_of(grant.tool)]
    # A fixed call carries nothing the model chose: it is no way out.
    outward = [grant.tool for grant in grants if not grant.fixed and "external_communication" in classes_of(grant.tool)]
    if memory:
        private.append(MEMORY)
    if event_trigger:
        private.append(EVENT_TRIGGER)
        untrusted.append(EVENT_TRIGGER)
    return Check(_unique(private), _unique(untrusted), _unique(outward))


def covering(grants: Iterable[Grant], tool: str, arguments: Mapping[str, Any]) -> Grant | None:
    """The grant that covers the call, if one does."""
    return next((grant for grant in grants if grant.covers(tool, arguments)), None)
