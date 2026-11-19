"""The agent acts only through mediated tools, and nothing runs on the host for users (AGT-001, AGT-013, OPS-004)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic_ai.native_tools import AbstractNativeTool

from sibillo_server import worker
from tests.support.database import ROOT

# Every capability of the agent: the gateway, the user's sandbox and the
# tools that work in it, durability, and what Pydantic AI adds by itself.
# None of them acts on the outside world except through the sandbox driver.
ALLOWED_CAPABILITIES = {
    "pydantic_ai.capabilities._tool_search.ToolSearch",
    "pydantic_ai.capabilities._pending_messages.PendingMessageDrainCapability",
    "pydantic_ai.durable_exec._workspace.WorkspaceEnsurer",
    "sibillo_server.gateway.Gateway",
    "sibillo_server.sandbox.SandboxWorkspace",
    # Sandbox commands say what they are for; it changes their definitions and arguments only (ADR-0085).
    "sibillo_server.sandbox.CommandPurposes",
    "pydantic_ai_harness.shell._capability.Shell",
    "pydantic_ai_harness.filesystem._capability.FileSystem",
    "pydantic_ai_harness.tool_output_limits._capability.ToolOutputLimits",
    # Questions to the user and the task list, which only end the run or change the conversation's
    # own state (AGT-015, UX-009, ADR-0083).
    "pydantic_ai_harness.ask_user._capability.AskUser",
    "pydantic_ai_harness.planning._capability.Planning",
    # Skills, read from the control plane by the harness's `Skills`: their catalog, and their bodies when
    # loaded (AGT-017, ADR-0096).
    "sibillo_server.skills.RunSkills",
    "pydantic_ai.durable_exec.dbos._durability.DBOSDurability",
    # Tool permissions, approvals and audit events: it takes tools away, ends the run to ask, and records
    # each call (AGT-002, AGT-004, AGT-006, AGT-008, ADR-0090).
    "sibillo_server.approvals.Approvals",
    # The accepted tools of the household's remote MCP servers, each call approved: the one exception of
    # AGT-013, a client of remote servers at checked addresses, never a program (AGT-018, AGT-019, ADR-0099).
    "sibillo_server.mcp_runs.McpServers",
}
# Tools the provider runs: only the search over the agent's own tools.
ALLOWED_NATIVE_TOOLS = {"tool_search"}
# The agent's own tools: web search through the instance's search service,
# page reading in the sandbox, offering a file to download, keeping the user's memory, and saving a skill,
# which change only rows of the database (AGT-020, AGT-021, AGT-023, AGT-026, MEM-007, ADR-0075, ADR-0079,
# ADR-0095, ADR-0096).
ALLOWED_OWN_TOOLS = {
    "web_search",
    "read_page",
    "offer_download",
    "remember",
    "update_memory",
    "forget",
    "save_skill",
    # Proposes a task, which only the user's approval saves (TSK-006, ADR-0106).
    "propose_task",
    # Changes a task, and reads the user's tasks and conversations (TSK-012, TSK-013, AGT-032, AGT-033, ADR-0107).
    "update_task",
    "list_tasks",
    "search_conversations",
    "read_conversation",
}
# The only places a component runs a command on the host, by file and
# enclosing function. None runs anything a user or the agent chose.
ALLOWED_HOST_COMMANDS = {
    ("src/netguard/sibillo_netguard/guard.py", "_nft"),
    ("src/sandboxd/sibillo_sandboxd/isolation.py", "_runtime_release"),
    # The operator's backups: pg_dump, pg_restore and age, on files of their own (ADR-0077).
    ("src/server/sibillo_server/backup.py", "_tool"),
}
HOST_COMMANDS = {
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("asyncio", "create_subprocess_exec"),
    ("asyncio", "create_subprocess_shell"),
    ("os", "system"),
    ("os", "popen"),
    ("os", "execv"),
    ("os", "execvp"),
    ("os", "spawnv"),
}


@pytest.mark.spec("AGT-001")
def test_the_agent_has_only_mediated_capabilities() -> None:
    capabilities = {f"{type(c).__module__}.{type(c).__name__}" for c in worker.agent.root_capability.capabilities}
    assert capabilities == ALLOWED_CAPABILITIES


@pytest.mark.spec("AGT-001", "AGT-013")
def test_the_agent_has_only_its_web_tools_and_no_provider_tools_that_act() -> None:
    tools = [tool for capability in worker.agent.root_capability.capabilities for tool in capability.get_native_tools()]
    # A native tool chosen at run time could be any tool: none is allowed.
    assert all(isinstance(tool, AbstractNativeTool) for tool in tools)
    assert {tool.kind for tool in tools if isinstance(tool, AbstractNativeTool)} <= ALLOWED_NATIVE_TOOLS
    assert set(worker.agent._function_toolset.tools) == ALLOWED_OWN_TOOLS  # pyright: ignore[reportPrivateUsage]
    assert worker.agent._user_toolsets == []  # pyright: ignore[reportPrivateUsage]


def _host_commands(path: Path) -> set[str]:
    """The enclosing function of every call that runs a command on the host."""
    found: set[str] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and (child.value.id, child.attr) in HOST_COMMANDS
            ):
                found.add(function)
            visit(child, name)

    visit(ast.parse(path.read_text(), filename=str(path)), "<module>")
    return found


@pytest.mark.spec("OPS-004")
def test_components_run_no_host_commands_for_users() -> None:
    found = {
        (str(path.relative_to(ROOT)), function)
        for path in sorted((ROOT / "src").rglob("*.py"))
        # The web app's dependencies are not components, and never run.
        if "node_modules" not in path.parts
        for function in _host_commands(path)
    }
    assert found <= ALLOWED_HOST_COMMANDS, "new host commands: they must run in sandboxes instead"
