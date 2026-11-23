"""Sibillo as an MCP client of remote servers: listing their tools and calling them (AGT-019, ADR-0099).

Through Pydantic AI's `MCPToolset`, over Streamable HTTP, with the HTTP client
of `mcp_http`: tools only, never the server's instructions, and no task
execution. The toolset is used as a client and never given to the agent, so
that a run offers only the tools a tenant admin accepted, under their
prefixed names (`mcp_runs`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

import httpx2
from pydantic_ai.exceptions import ModelRetry, ToolFailed
from pydantic_ai.mcp import MCPToolset

from sibillo_server.mcp_http import mcp_http_client

# A server must list its tools in this time, or be left out (ADR-0099, point 11).
LIST_SECONDS = 10
# What a tool may be to be accepted (ADR-0099, point 6).
MAX_DESCRIPTION_CHARS = 4000
MAX_SCHEMA_BYTES = 16 * 1024
MAX_TOOLS = 100
MODEL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Characters an admin reviewing a tool cannot see, or that reorder what they read: format characters, such as
# zero-width spaces and joiners, and bidirectional controls (T-29, ADR-0128).
HIDDEN = re.compile(r"[\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\U000e0000-\U000e007f]")
DETAIL_CHARS = 300


@dataclass(frozen=True)
class Target:
    """Where a server is, and whether its address may be private (ADR-0099, point 4)."""

    url: str
    private_network: bool

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or self.url


@dataclass(frozen=True)
class ListedTool:
    """A tool as its server listed it."""

    name: str
    title: str | None
    description: str | None
    input_schema: dict[str, Any]
    annotations: dict[str, Any] | None
    requires_tasks: bool

    def listed(self) -> dict[str, Any]:
        """What the database keeps of it (`mcp_server_tools.listed`)."""
        return {
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
        }


@dataclass(frozen=True)
class Listing:
    server_name: str | None
    server_version: str | None
    tools: list[ListedTool]


@dataclass
class ServerError(Exception):
    """A server could not be reached, or refused: at which step, and why, without what it answered."""

    step: str
    detail: str
    # The server answered 401: its credential is missing, wrong or expired.
    unauthorized: bool = False

    def __str__(self) -> str:
        return f"{self.step}: {self.detail}"


@dataclass
class _Watch:
    """The statuses a server answered, which the MCP SDK does not report."""

    statuses: list[int] = field(default_factory=list[int])

    async def __call__(self, response: httpx2.Response) -> None:
        self.statuses.append(response.status_code)

    @property
    def unauthorized(self) -> bool:
        return 401 in self.statuses


def reviewed(listed: dict[str, Any]) -> dict[str, Any]:
    """The fields of a listed tool that a tenant admin accepts: what the model reads (ADR-0099, point 6)."""
    return {
        "title": listed.get("title"),
        "description": listed.get("description"),
        "inputSchema": listed.get("inputSchema"),
    }


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(listed: dict[str, Any]) -> str:
    """The SHA-256 of the canonical JSON of the reviewed fields, which an acceptance names."""
    return hashlib.sha256(canonical(reviewed(listed)).encode()).hexdigest()


def problems(prefix: str, tools: list[ListedTool]) -> dict[str, str | None]:
    """Why each listed tool cannot be accepted, if it cannot (ADR-0099, point 6)."""
    if len(tools) > MAX_TOOLS:
        return {listed.name: "too_many_tools" for listed in tools}
    found: dict[str, str | None] = {}
    for listed in tools:
        problem: str | None = None
        if not MODEL_NAME.match(f"{prefix}__{listed.name}"):
            problem = "name"
        elif len(listed.description or "") > MAX_DESCRIPTION_CHARS:
            problem = "description_too_long"
        elif len(canonical(listed.input_schema).encode()) > MAX_SCHEMA_BYTES:
            problem = "schema_too_large"
        elif listed.requires_tasks:
            problem = "requires_tasks"
        elif any(HIDDEN.search(text or "") for text in (listed.name, listed.title, listed.description)):
            problem = "hidden_characters"
        found[listed.name] = problem
    return found


def _toolset(target: Target, token: str | None, timeout: float) -> tuple[MCPToolset[Any], _Watch]:
    watch = _Watch()
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    client = mcp_http_client(
        private_network=target.private_network, server_url=target.url, headers=headers, timeout=timeout
    )
    client.event_hooks["response"].append(watch)
    toolset = MCPToolset[Any](
        target.url,
        http_client=client,
        # The server's instructions never reach the model (ADR-0099, point 1).
        include_instructions=False,
        prefer_tasks=False,
        cache_tools=False,
        init_timeout=timeout,
        read_timeout=timeout,
        tool_error_behavior="failed",
    )
    return toolset, watch


def _inner(error: BaseException) -> BaseException | None:
    """The first exception of a group, which task groups wrap failures in."""
    exceptions: Any = getattr(error, "exceptions", None)
    if not isinstance(exceptions, tuple) or not exceptions:
        return None
    first: object = cast(tuple[object, ...], exceptions)[0]
    return first if isinstance(first, BaseException) else None


def _detail(error: BaseException) -> str:
    """The innermost cause of a failure, briefly: never a response body (T-31)."""
    cause = error
    for _ in range(10):
        nested = _inner(cause) or cause.__cause__ or cause.__context__
        if nested is None or isinstance(nested, asyncio.CancelledError):
            break
        cause = nested
    return (str(cause) or type(cause).__name__)[:DETAIL_CHARS]


def _listed(tool: Any) -> ListedTool:
    execution: Any = getattr(tool, "execution", None)
    support = getattr(execution, "task_support", None) or getattr(execution, "taskSupport", None)
    annotations: Any = getattr(tool, "annotations", None)
    schema = cast(dict[str, Any], getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {})
    return ListedTool(
        name=str(tool.name),
        title=getattr(tool, "title", None),
        description=getattr(tool, "description", None),
        input_schema=dict(schema),
        annotations=None if annotations is None else annotations.model_dump(by_alias=True, exclude_none=True),
        requires_tasks=support == "required",
    )


async def list_tools(target: Target, token: str | None, seconds: float = LIST_SECONDS) -> Listing:
    """Connect to the server and list its tools, within `seconds`."""
    toolset, watch = _toolset(target, token, seconds)

    async def listing() -> Listing:
        async with toolset:
            tools = await toolset.list_tools()
            info = toolset.server_info
        return Listing(
            server_name=str(info.name)[:200],
            server_version=str(info.version)[:100],
            tools=[_listed(tool) for tool in tools],
        )

    try:
        return await asyncio.wait_for(listing(), seconds)
    except TimeoutError:
        raise ServerError("list_tools", f"no answer within {seconds:g} seconds") from None
    except Exception as error:
        if watch.unauthorized:
            raise ServerError("authenticate", "the server refused the credential", unauthorized=True) from None
        step = "list_tools" if watch.statuses else "connect"
        raise ServerError(step, _detail(error)) from None


async def call_tool(target: Target, token: str | None, name: str, arguments: dict[str, Any], seconds: float) -> Any:
    """Call a tool, within `seconds`: its result as the model receives it.

    A result the server marks as an error, or a call that fails or times out,
    raises `ToolFailed`, which the model sees; a refused credential raises
    `ServerError` with `unauthorized`, so that the caller may renew it.
    """
    toolset, watch = _toolset(target, token, seconds)

    async def call() -> Any:
        async with toolset:
            return await toolset.direct_call_tool(name, arguments)

    try:
        return await asyncio.wait_for(call(), seconds)
    except TimeoutError:
        raise ToolFailed(f"The server did not answer within {seconds:g} seconds, so the call was stopped.") from None
    except ToolFailed:
        raise
    except ModelRetry as error:
        raise ToolFailed(str(error)[:DETAIL_CHARS]) from None
    except Exception as error:
        if watch.unauthorized:
            raise ServerError("authenticate", "the server refused the credential", unauthorized=True) from None
        raise ToolFailed(f"The call failed: {_detail(error)}") from None
