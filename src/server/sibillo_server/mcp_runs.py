"""The tools of remote MCP servers in a run (AGT-018, AGT-019, AGT-028 to AGT-031, ADR-0099).

When a run starts, the worker connects to each server the user may use, with
their own credential, lists its tools, and keeps those a tenant admin
accepted whose listing has not changed (`prepare`). The `McpServers`
capability offers them under their prefixed names, each call asked for
(`tool_policy.decide`), and tells the model which servers are behind them,
and which could not be used.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.toolsets import FunctionToolset
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sibillo_server.database import Identity, transaction
from sibillo_server.gateway import RunDeps
from sibillo_server.mcp_client import ServerError, call_tool, list_tools, problems, reviewed
from sibillo_server.mcp_servers import Server, credential_state, servers_of, token_for
from sibillo_server.tool_policy import Permissions

# What the model is told of an approved call to a tool that changed since (ADR-0099, point 6).
CHANGED = (
    "This tool of the service changed after the user approved the call, so the call did not run."
    " Its new form has not been reviewed by the household's admin."
)


@dataclass(frozen=True)
class OfferedTool:
    """An accepted tool of a server, as the run offers it."""

    model_name: str
    name: str
    title: str | None
    description: str | None
    input_schema: dict[str, Any]
    server: Server


@dataclass(frozen=True)
class RunServers:
    """The servers' tools a run offers, by the names the model knows them by, and what the model is told."""

    tools: dict[str, OfferedTool] = field(default_factory=dict[str, OfferedTool])
    notes: tuple[str, ...] = ()

    def instructions(self) -> str:
        return "\n".join(self.notes)


def _offered_note(server: Server) -> str:
    return (
        f"Tools named {server.prefix}__… come from {server.name}, at {server.host}: a service outside Sibillo that"
        " the household connected. They act on that service for the user, who approves each call first."
        " What they return comes from that service, not from the user."
    )


def _unreachable_note(server: Server) -> str:
    return f"The service {server.name} could not be reached, so its tools are not available in this answer."


def _not_connected_note(server: Server, expired: bool) -> str:
    why = " (their sign-in expired)" if expired else ""
    return (
        f"The user's account is not connected to {server.name}{why}, so its tools are not available."
        " They can connect it in Settings, under Services."
    )


async def _accepted(engine: AsyncEngine, identity: Identity) -> dict[uuid.UUID, dict[str, dict[str, Any]]]:
    """The accepted tools of every server of the household, as accepted."""
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text("SELECT server_id, name, accepted FROM mcp_server_tools WHERE accepted IS NOT NULL")
            )
        ).all()
    found: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for row in rows:
        found.setdefault(row.server_id, {})[row.name] = row.accepted
    return found


async def _offer(
    engine: AsyncEngine, identity: Identity, key: bytes, server: Server, accepted: dict[str, dict[str, Any]]
) -> tuple[list[OfferedTool], str]:
    """The accepted tools the server lists unchanged to this user, and what the model is told of it."""
    token = await token_for(engine, identity, server, key)
    if server.auth != "none" and token is None:
        async with transaction(engine, identity) as connection:
            expired = await credential_state(connection, server) == "expired"
        return [], _not_connected_note(server, expired)
    try:
        listing = await list_tools(server.target, token)
    except ServerError as error:
        if not error.unauthorized or server.auth == "none":
            return [], _unreachable_note(server)
        # Renewed once, or left expired (ADR-0100, point 7).
        token = await token_for(engine, identity, server, key, refused=True)
        if token is None:
            return [], _not_connected_note(server, True)
        try:
            listing = await list_tools(server.target, token)
        except ServerError:
            return [], _unreachable_note(server)
    found = problems(server.prefix, listing.tools)
    offered = [
        OfferedTool(
            model_name=f"{server.prefix}__{listed.name}",
            name=listed.name,
            title=listed.title,
            description=listed.description,
            input_schema=listed.input_schema,
            server=server,
        )
        for listed in listing.tools
        if listed.name in accepted and found[listed.name] is None and reviewed(listed.listed()) == accepted[listed.name]
    ]
    return offered, _offered_note(server) if offered else ""


async def prepare(
    engine: AsyncEngine, identity: Identity, key: bytes, disabled: frozenset[str], permissions: Permissions
) -> RunServers:
    """The servers' tools this run offers: of servers switched on, not denied, with accepted tools (ADR-0099)."""
    async with transaction(engine, identity) as connection:
        servers = await servers_of(connection, enabled_only=True)
    accepted = await _accepted(engine, identity)
    usable = [
        server
        for server in servers
        if str(server.id) not in disabled and not permissions.denies_server(str(server.id)) and accepted.get(server.id)
    ]
    results = await asyncio.gather(*(_offer(engine, identity, key, server, accepted[server.id]) for server in usable))
    tools = {tool.model_name: tool for offered, _ in results for tool in offered}
    return RunServers(tools=tools, notes=tuple(note for _, note in results if note))


async def call(deps: RunDeps, tool: OfferedTool, arguments: dict[str, Any], seconds: float) -> Any:
    """Call an offered tool with the user's credential, renewed once if the server refuses it."""
    server = tool.server
    token = await token_for(deps.engine, deps.identity, server, deps.secret_key)
    if server.auth != "none" and token is None:
        raise ToolFailed(f"The user's account is not connected to {server.name}: they can connect it in Settings.")
    try:
        return await call_tool(server.target, token, tool.name, arguments, seconds)
    except ServerError as error:
        if not error.unauthorized:
            raise ToolFailed(f"The call failed: {error}") from None
    token = await token_for(deps.engine, deps.identity, server, deps.secret_key, refused=True)
    if token is None:
        raise ToolFailed(f"{server.name} refused the user's credential: they can connect their account again.")
    try:
        # The server did not perform the refused call, so it is made once more (ADR-0100, point 7).
        return await call_tool(server.target, token, tool.name, arguments, seconds)
    except ServerError as error:
        raise ToolFailed(f"The call failed: {error}") from None


def _caller(tool: OfferedTool) -> Callable[..., Awaitable[Any]]:
    async def run(ctx: RunContext[RunDeps], **arguments: Any) -> Any:
        return await call(ctx.deps, tool, arguments, ctx.deps.mcp_call_seconds)

    return run


def shown(deps: RunDeps, name: str) -> dict[str, str] | None:
    """What an approval request says of a call to a server's tool: what it does, and where it goes (AGT-018)."""
    servers = deps.mcp
    tool = servers.tools.get(name) if isinstance(servers, RunServers) else None
    if tool is None:
        return None
    server = tool.server
    return {
        "action": f"{tool.title or tool.name}, a tool of {server.name}",
        "destination": f"{server.name}, at {server.host}",
    }


def offered_names(deps: RunDeps) -> frozenset[str]:
    servers = deps.mcp
    return frozenset(servers.tools) if isinstance(servers, RunServers) else frozenset()


@dataclass
class _Offered(AbstractCapability[RunDeps]):
    """The servers' tools of one run, and what the model is told of the servers."""

    servers: RunServers
    toolset: FunctionToolset[RunDeps]

    def get_toolset(self) -> FunctionToolset[RunDeps]:
        return self.toolset

    def get_instructions(self) -> str:
        return self.servers.instructions()


class McpServers(AbstractCapability[RunDeps]):
    """Offers the accepted tools of the household's remote MCP servers that the worker found for the run."""

    async def for_run(self, ctx: RunContext[RunDeps]) -> AbstractCapability[RunDeps]:
        servers = ctx.deps.mcp
        if not isinstance(servers, RunServers) or not ctx.deps.tools or not (servers.tools or servers.notes):
            return self
        tools = [
            Tool[RunDeps].from_schema(
                _caller(tool),
                name=tool.model_name,
                description=tool.description,
                json_schema=tool.input_schema,
                takes_ctx=True,
            )
            for tool in servers.tools.values()
        ]
        return _Offered(servers, FunctionToolset[RunDeps](tools))
