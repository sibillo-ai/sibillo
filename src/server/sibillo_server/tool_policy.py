"""What each tool may do, and when a call needs the user's approval (AGT-002 to AGT-006, ADR-0012, ADR-0090).

Every tool declares its capability classes and its approval default. A
tenant admin's tool permissions change the default, or take the tool away.
A call needs approval for its classes, its permission or its default, or,
once the conversation has untrusted content, because it communicates
externally; allowances the user gave in the conversation, or for the turn,
cover some of these. The web tools need internet access instead, one
permission of the conversation (AGT-034, ADR-0113).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart

type CapabilityClass = Literal[
    "reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"
]
type Setting = Literal["allow", "ask", "deny"]
type ApprovalReason = Literal[
    "untrusted_content", "tool_default", "permission", "consequential", "device", "task_proposal", "internet_access"
]
type Scope = Literal["once", "turn", "conversation"]

CLASSES: tuple[CapabilityClass, ...] = (
    "reads_private_data",
    "ingests_untrusted",
    "external_communication",
    "irreversible",
    "physical",
)
SETTINGS: tuple[Setting, ...] = ("allow", "ask", "deny")
STRICTNESS: dict[Setting, int] = {"allow": 0, "ask": 1, "deny": 2}
# The classes whose every call is approved, one by one (AGT-006).
CONSEQUENTIAL: frozenset[CapabilityClass] = frozenset({"irreversible", "physical"})
# The classes whose calls have effects outside Sibillo, and record an idempotency key (AGT-008).
EXTERNAL_EFFECTS: frozenset[CapabilityClass] = frozenset({"external_communication", "irreversible", "physical"})
# The tool that asks for internet access, and the tools that need it (AGT-034, ADR-0113).
REQUEST_INTERNET_ACCESS = "request_internet_access"
INTERNET_TOOLS = frozenset({"web_search", "read_page", REQUEST_INTERNET_ACCESS})
# The classes of every tool of a remote MCP server (AGT-005, ADR-0099).
SERVER_CLASSES: frozenset[CapabilityClass] = frozenset(
    {"reads_private_data", "ingests_untrusted", "external_communication"}
)
# Separates a server's prefix from its tool's name; no tool of Sibillo has it (ADR-0099).
SERVER_SEPARATOR = "__"
# Labels the part of a user's message that lists its attachments (CNV-017).
ATTACHMENTS_ORIGIN = "sibillo.attachments"
# Labels the part of a task's first message that holds the event that fired it, untrusted content (ADR-0106).
EVENT_ORIGIN = "sibillo.event"
# The tools that propose or change a task: every call asked, once (TSK-006, TSK-012, ADR-0106, ADR-0107).
PROPOSE_TASK = "propose_task"
UPDATE_TASK = "update_task"
TASK_PROPOSALS = frozenset({PROPOSE_TASK, UPDATE_TASK})
# Labels the result of reading the user's conversations with whether what it shows is untrusted (ADR-0107).
PROVENANCE_ORIGIN = "sibillo.provenance"
# Labels the result of loading a skill with the skill's name and whether it is untrusted (AGT-025, ADR-0096).
SKILL_ORIGIN = "sibillo.skill"
# What the model is told of a call the user did not approve.
DENIED = "The user denied this call, so it did not run. Do not try it again unless the user asks."
EXPIRED = "Nobody approved this call within a day, so it was denied and did not run."
# What the model is told of a call that needs internet access after the user denied it in the turn (AGT-034).
DENIED_INTERNET_ACCESS = (
    "The user denied internet access in this turn, so this call did not run. Do not ask for it again in this"
    " turn; work without the internet, or tell the user what you would need it for."
)
# What `request_internet_access` answers once the conversation has internet access (AGT-034).
INTERNET_ACCESS_GIVEN = (
    "The conversation has internet access: the web tools run, and the sandbox reaches public addresses."
)


@dataclass(frozen=True)
class Declaration:
    """A tool's capability classes and its approval default (AGT-005)."""

    classes: frozenset[CapabilityClass]
    approval_default: Literal["allow", "ask"] = "allow"


def _declare(*classes: CapabilityClass) -> Declaration:
    return Declaration(frozenset(classes))


_READS = _declare("reads_private_data", "ingests_untrusted")
_WRITES = _declare("reads_private_data")
_OWN = _declare()

# Every tool of the assistant, in the order of the API contract's `ToolName` (ADR-0090). Web tools are
# allowed by default: internet access guards them (AGT-034, ADR-0113).
DECLARATIONS: Mapping[str, Declaration] = {
    "web_search": _declare("ingests_untrusted", "external_communication"),
    "read_page": _declare("ingests_untrusted", "external_communication"),
    # Asks for internet access, and does nothing else.
    REQUEST_INTERNET_ACCESS: _OWN,
    # A command's only way out is the sandbox's network, which internet access governs (ADR-0113).
    "run_command": _READS,
    "start_command": _READS,
    "check_command": _READS,
    "stop_command": _WRITES,
    "read_file": _READS,
    "write_file": _WRITES,
    "edit_file": _WRITES,
    "create_directory": _WRITES,
    "list_directory": _READS,
    "find_files": _READS,
    "search_files": _READS,
    "file_info": _READS,
    "view_image": _READS,
    "offer_download": _WRITES,
    "ask_user_question": _OWN,
    "write_plan": _OWN,
    "read_plan": _OWN,
    "add_task": _OWN,
    "update_task_status": _OWN,
    "update_task_statuses": _OWN,
    "remove_task": _OWN,
    # They change only the user's own memory, which the user sees and corrects; provenance guards what they
    # write (MEM-008, ADR-0095).
    "remember": _OWN,
    "update_memory": _OWN,
    "forget": _OWN,
    # Saves a skill that later conversations are given: the user sees it before it does (AGT-026, ADR-0096).
    "save_skill": Declaration(frozenset(), "ask"),
    # Saves a task that runs later with standing grants: the user sees all of it first (TSK-006, ADR-0106).
    PROPOSE_TASK: Declaration(frozenset(), "ask"),
    # Changes a task: the user sees the whole change first (TSK-012, ADR-0107).
    UPDATE_TASK: Declaration(frozenset(), "ask"),
    # They read the user's tasks and conversations: private data, untrusted only by what they read (ADR-0107).
    "list_tasks": _WRITES,
    "search_conversations": _WRITES,
    "read_conversation": _WRITES,
    # Loads a skill: what it brings in is untrusted when the skill is, by provenance (AGT-025, ADR-0096).
    "load_capability": _OWN,
    # The output limits' own tool, which reads back a large result set aside (AGT-014): no switch (ADR-0087).
    "read_tool_result": _READS,
}


def is_server_tool(tool: str) -> bool:
    """Whether the name is of a remote MCP server's tool, `<prefix>__<tool>` (ADR-0099)."""
    return SERVER_SEPARATOR in tool


def ingests_untrusted(tool: str) -> bool:
    declaration = DECLARATIONS.get(tool)
    # A tool without a declaration is treated as the most cautious one would be.
    return declaration is None or "ingests_untrusted" in declaration.classes


# Commands reach the internet once the conversation has internet access: a call that may have run twice after a
# crash is shown as such, as for the tools that communicate externally (AGT-008, ADR-0113).
COMMANDS = frozenset({"run_command", "start_command"})


def has_external_effects(tool: str) -> bool:
    declaration = DECLARATIONS.get(tool)
    return declaration is None or tool in COMMANDS or bool(EXTERNAL_EFFECTS & declaration.classes)


def _untrusted_skill(part: ToolReturnPart) -> bool:
    """Whether the part loaded an untrusted skill (AGT-025)."""
    metadata: Any = part.metadata
    if part.tool_name != "load_capability" or not isinstance(metadata, dict):
        return False
    skill: Any = cast(dict[str, Any], metadata).get(SKILL_ORIGIN)
    return isinstance(skill, dict) and cast(dict[str, Any], skill).get("untrusted") is True


def _untrusted_reading(part: ToolReturnPart) -> bool:
    """Whether the part read another conversation that holds untrusted content (AGT-033, ADR-0107)."""
    metadata: Any = part.metadata
    if not isinstance(metadata, dict):
        return False
    provenance: Any = cast(dict[str, Any], metadata).get(PROVENANCE_ORIGIN)
    return isinstance(provenance, dict) and cast(dict[str, Any], provenance).get("untrusted") is True


def has_untrusted_content(messages: Sequence[ModelMessage]) -> bool:
    """Whether the messages hold untrusted content: results of tools that ingest it, or attachments (AGT-003)."""
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and (
                ingests_untrusted(part.tool_name) or _untrusted_skill(part) or _untrusted_reading(part)
            ):
                return True
            if isinstance(part, UserPromptPart) and not isinstance(part.content, str):
                for item in part.content:
                    metadata: Any = getattr(item, "metadata", None)
                    if isinstance(metadata, dict) and cast(dict[str, Any], metadata).get("origin") in (
                        ATTACHMENTS_ORIGIN,
                        EVENT_ORIGIN,
                    ):
                        return True
    return False


@dataclass(frozen=True)
class Permissions:
    """A user's tool permissions: settings by tool and by capability class (AGT-002)."""

    tools: Mapping[str, Setting] = field(default_factory=dict[str, Setting])
    classes: Mapping[str, Setting] = field(default_factory=dict[str, Setting])
    # The IDs of the remote MCP servers denied to the user (AGT-029, ADR-0099).
    servers: frozenset[str] = frozenset()

    def to_json(self) -> dict[str, Any]:
        return {"tools": dict(self.tools), "classes": dict(self.classes), "servers": sorted(self.servers)}

    @classmethod
    def from_json(cls, value: Any) -> Permissions:
        data = cast(dict[str, Any], value or {})
        return cls(
            tools=dict(data.get("tools") or {}),
            classes=dict(data.get("classes") or {}),
            servers=frozenset(data.get("servers") or ()),
        )

    def denies_server(self, server_id: str) -> bool:
        """Whether the server is denied, or a class of every server's tools is (AGT-029, ADR-0099)."""
        return server_id in self.servers or any(self.classes.get(name) == "deny" for name in SERVER_CLASSES)


def denies_internet_access(permissions: Permissions) -> bool:
    """Whether the user's permissions deny internet access: never asked, never given (AGT-034, ADR-0113)."""
    return permissions.classes.get("external_communication") == "deny"


@dataclass(frozen=True)
class Effective:
    """What applies to a tool for a user, and where it comes from: a permission's subject, or the default."""

    setting: Setting
    subject: str | None = None


def effective(tool: str, permissions: Permissions) -> Effective:
    """A tool's setting wins over its classes'; among its classes the strictest wins (AGT-002). A user denied
    the `external_communication` class has no internet access, whatever the web tools' settings (AGT-034)."""
    if tool in INTERNET_TOOLS and denies_internet_access(permissions):
        return Effective("deny", "external_communication")
    if tool in permissions.tools:
        return Effective(permissions.tools[tool], tool)
    declaration = DECLARATIONS[tool]
    found: list[tuple[Setting, str]] = [
        (permissions.classes[name], name)
        for name in CLASSES
        if name in declaration.classes and name in permissions.classes
    ]
    if found:
        setting, subject = max(found, key=lambda item: STRICTNESS[item[0]])
        return Effective(setting, subject)
    return Effective(declaration.approval_default)


def denied(permissions: Permissions) -> frozenset[str]:
    """The tools a user's permissions take away."""
    return frozenset(name for name in DECLARATIONS if effective(name, permissions).setting == "deny")


@dataclass(frozen=True)
class Allowances:
    """What the user allowed: internet access for the turn or the conversation, and tools in it (AGT-006, AGT-034).

    `turn_denied_internet_access` says that the user denied internet access in the turn, or let its request
    expire: later calls that need it are denied without asking.
    """

    turn_internet_access: bool = False
    internet_access: bool = False
    tools: frozenset[str] = frozenset()
    turn_denied_internet_access: bool = False

    @property
    def has_internet_access(self) -> bool:
        return self.turn_internet_access or self.internet_access


@dataclass(frozen=True)
class Request:
    """Why a call needs approval, and which scopes the user may approve it with (ADR-0090)."""

    reason: ApprovalReason
    scopes: tuple[Scope, ...]


@dataclass(frozen=True)
class Decision:
    """A call runs (`allowed` when an allowance let it), needs approval (`request`), or is denied without asking."""

    request: Request | None = None
    allowed: Scope | None = None
    denied: bool = False


def decide(tool: str, permissions: Permissions, untrusted: bool, allowances: Allowances) -> Decision:
    """Whether a call of `tool`, in a run with or without untrusted content, needs approval."""
    if is_server_tool(tool):
        # Every call to a server is approved, once, and nothing lifts it (AGT-018, ADR-0099).
        return Decision(Request("device", ("once",)))
    if tool in TASK_PROPOSALS:
        return Decision(Request("task_proposal", ("once",)))
    declaration = DECLARATIONS.get(tool)
    if declaration is None:
        return Decision(Request("consequential", ("once",)))
    if CONSEQUENTIAL & declaration.classes:
        return Decision(Request("consequential", ("once",)))
    allowed: Scope | None = None
    if tool in INTERNET_TOOLS:
        # Internet access first, whether or not the run has untrusted content (AGT-034, ADR-0113).
        if allowances.turn_internet_access:
            allowed = "turn"
        elif allowances.internet_access:
            allowed = "conversation"
        elif allowances.turn_denied_internet_access:
            return Decision(denied=True)
        else:
            return Decision(Request("internet_access", ("turn", "conversation")))
        if tool == REQUEST_INTERNET_ACCESS:
            return Decision(allowed=allowed)
    setting = effective(tool, permissions)
    if setting.setting == "ask":
        if tool not in allowances.tools:
            reason: ApprovalReason = "tool_default" if setting.subject is None else "permission"
            return Decision(Request(reason, ("once", "conversation")))
        allowed = "conversation"
    if untrusted and "external_communication" in declaration.classes and tool not in INTERNET_TOOLS:
        return Decision(Request("untrusted_content", ("once",)))
    return Decision(allowed=allowed)


def describe(tool: str, arguments: Mapping[str, Any]) -> tuple[str, str, str]:
    """What a call does, the data it sends, and where it goes, for the user to approve (AGT-007)."""
    if tool == "web_search":
        return (
            "Search the web",
            str(arguments.get("query", "")),
            "The household's search service, which asks public search engines",
        )
    if tool == "read_page":
        address = str(arguments.get("url", ""))
        host = urlsplit(address).hostname or address
        return "Read a web page", address, f"{host}, from the conversation's sandbox"
    if tool in ("run_command", "start_command"):
        command = str(arguments.get("command", ""))
        purpose = str(arguments.get("description", "") or arguments.get("purpose", ""))
        action = "Run a command in the sandbox" if tool == "run_command" else "Start a command in the sandbox"
        return (f"{action}: {purpose}" if purpose else action), command, "The conversation's sandbox"
    if tool == UPDATE_TASK:
        return (
            "Change one of your tasks, with what the change lists",
            str(arguments.get("task_id", "")),
            "Your tasks, which run without asking for what they grant",
        )
    if tool == PROPOSE_TASK:
        return (
            "Save a task that runs on its own, with the grants it lists",
            str(arguments.get("name", "")),
            "Your tasks, which run without asking for what they grant",
        )
    rendered = ", ".join(f"{key}: {value}" for key, value in arguments.items())
    return f"Use {tool}", rendered, "Wherever the tool sends it"
