"""Sibillo as a client of the MCP Events extension of remote servers (TSK-008, ADR-0106).

The extension (`io.modelcontextprotocol/events`, SEP-3415) is new, and the MCP
SDK that `mcp_client` uses for tools does not speak it yet, so this module
sends its few JSON-RPC requests itself, over Streamable HTTP, with the same
HTTP client and address rules as the server's tools (`mcp_http`): listing
event types, polling, and subscribing for webhook deliveries.

Event data is untrusted content, and bounded before any run reads it.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, cast

import httpx2

from sibillo_server.mcp_client import (
    MAX_DESCRIPTION_CHARS,
    MAX_SCHEMA_BYTES,
    ServerError,
    Target,
    canonical,
)
from sibillo_server.mcp_http import mcp_http_client

PROTOCOL_VERSION = "2025-06-18"
EXTENSION = "io.modelcontextprotocol/events"
REQUEST_SECONDS = 15
MAX_EVENT_TYPES = 100
# The names of event types, as the review keeps them.
EVENT_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# The delivery modes Sibillo receives events by; streams wait until they are needed (ADR-0106, point 6).
SUPPORTED_DELIVERY = frozenset({"poll", "webhook"})
# The most events one poll asks for.
MAX_EVENTS = 20
# A webhook's timestamp must be this fresh (ADR-0106, point 6).
WEBHOOK_TOLERANCE_SECONDS = 300
METHOD_NOT_FOUND = -32601


@dataclass(frozen=True)
class EventType:
    """An event type as its server listed it."""

    name: str
    description: str | None
    input_schema: dict[str, Any]
    payload_schema: dict[str, Any] | None
    delivery: list[str]

    def listed(self) -> dict[str, Any]:
        """What the database keeps of it (`mcp_server_events.listed`)."""
        return {
            "description": self.description,
            "inputSchema": self.input_schema,
            "payloadSchema": self.payload_schema,
            "delivery": self.delivery,
        }


def reviewed(listed: dict[str, Any]) -> dict[str, Any]:
    """The fields of a listed event type that a tenant admin accepts."""
    return {
        "description": listed.get("description"),
        "inputSchema": listed.get("inputSchema"),
        "payloadSchema": listed.get("payloadSchema"),
    }


def digest(listed: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(reviewed(listed)).encode()).hexdigest()


def problems(types: list[EventType]) -> dict[str, str | None]:
    """Why each listed event type cannot be accepted, if it cannot."""
    if len(types) > MAX_EVENT_TYPES:
        return {item.name: "too_many_events" for item in types}
    found: dict[str, str | None] = {}
    for item in types:
        problem: str | None = None
        if not EVENT_NAME.match(item.name):
            problem = "name"
        elif len(item.description or "") > MAX_DESCRIPTION_CHARS:
            problem = "description_too_long"
        elif any(
            len(canonical(schema).encode()) > MAX_SCHEMA_BYTES for schema in (item.input_schema, item.payload_schema)
        ):
            problem = "schema_too_large"
        elif not SUPPORTED_DELIVERY & set(item.delivery):
            problem = "no_supported_delivery"
        found[item.name] = problem
    return found


class _NotSupportedError(Exception):
    """The server does not offer the extension."""


class _Session:
    """One short MCP session: initialized, then a request or two."""

    def __init__(self, target: Target, token: str | None) -> None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        self._client = mcp_http_client(
            private_network=target.private_network, server_url=target.url, headers=headers, timeout=REQUEST_SECONDS
        )
        self._url = target.url
        self._session: str | None = None
        self._next = 0

    async def __aenter__(self) -> _Session:
        await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"extensions": {EXTENSION: {}}},
                "clientInfo": {"name": "sibillo", "version": "1"},
            },
        )
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    async def __aexit__(self, *_: object) -> None:
        try:
            if self._session is not None:
                await self._client.delete(self._url, headers={"Mcp-Session-Id": self._session})
        except httpx2.HTTPError:
            pass
        await self._client.aclose()

    async def _post(self, message: dict[str, Any]) -> httpx2.Response:
        headers: dict[str, str] = {}
        if self._session is not None:
            headers["Mcp-Session-Id"] = self._session
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        response = await self._client.post(self._url, content=json.dumps(message).encode(), headers=headers)
        if response.status_code == 401:
            raise ServerError("authenticate", "the server refused the credential", unauthorized=True)
        if response.status_code >= 400:
            raise ServerError("request", f"the server answered {response.status_code}")
        self._session = response.headers.get("mcp-session-id") or self._session
        return response

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next += 1
        request_id = self._next
        response = await self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        message = _answer(response, request_id)
        error = message.get("error")
        if isinstance(error, dict):
            if cast(dict[str, Any], error).get("code") == METHOD_NOT_FOUND:
                raise _NotSupportedError(method)
            raise ServerError(method, str(cast(dict[str, Any], error).get("message", "error"))[:300])
        result = message.get("result")
        if not isinstance(result, dict):
            raise ServerError(method, "the answer has no result")
        return cast(dict[str, Any], result)


def _answer(response: httpx2.Response, request_id: int) -> dict[str, Any]:
    """The JSON-RPC answer to the request, in a JSON body or in an event stream."""
    kind = response.headers.get("content-type", "")
    if kind.startswith("text/event-stream"):
        for block in response.text.split("\n\n"):
            data = "".join(
                line.removeprefix("data:").strip() for line in block.splitlines() if line.startswith("data:")
            )
            if not data:
                continue
            try:
                message = json.loads(data)
            except ValueError:
                continue
            if isinstance(message, dict) and cast(dict[str, Any], message).get("id") == request_id:
                return cast(dict[str, Any], message)
        raise ServerError("request", "the stream held no answer")
    try:
        message = response.json()
    except ValueError:
        raise ServerError("request", "the answer is not JSON") from None
    if not isinstance(message, dict):
        raise ServerError("request", "the answer is not a JSON-RPC message")
    return cast(dict[str, Any], message)


async def _call(target: Target, token: str | None, method: str, params: dict[str, Any]) -> dict[str, Any]:
    async def call() -> dict[str, Any]:
        async with _Session(target, token) as session:
            return await session.request(method, params)

    try:
        return await asyncio.wait_for(call(), REQUEST_SECONDS * 2)
    except TimeoutError:
        raise ServerError(method, "no answer in time") from None
    except (ServerError, _NotSupportedError):
        raise
    except httpx2.HTTPError as error:
        raise ServerError("connect", str(error)[:300] or type(error).__name__) from None


async def list_event_types(target: Target, token: str | None) -> list[EventType]:
    """The server's event types; none when it does not offer the extension."""
    try:
        result = await _call(target, token, "events/list", {})
    except _NotSupportedError:
        return []
    found: list[EventType] = []
    for raw in cast(list[Any], result.get("events") or []):
        if not isinstance(raw, dict):
            continue
        item = cast(dict[str, Any], raw)
        delivery = [str(mode) for mode in cast(list[Any], item.get("delivery") or []) if isinstance(mode, str)]
        payload = item.get("payloadSchema")
        found.append(
            EventType(
                name=str(item.get("name", "")),
                description=item.get("description") if isinstance(item.get("description"), str) else None,
                input_schema=cast(dict[str, Any], item.get("inputSchema") or {}),
                payload_schema=cast(dict[str, Any], payload) if isinstance(payload, dict) else None,
                delivery=delivery,
            )
        )
    return found


@dataclass(frozen=True)
class Poll:
    events: list[dict[str, Any]]
    cursor: str | None
    next_poll_ms: int | None


async def poll(target: Target, token: str | None, name: str, arguments: dict[str, Any], cursor: str | None) -> Poll:
    try:
        result = await _call(
            target,
            token,
            "events/poll",
            {"name": name, "arguments": arguments, "cursor": cursor, "maxEvents": MAX_EVENTS},
        )
    except _NotSupportedError:
        raise ServerError("events/poll", "the server does not offer events") from None
    events = [
        cast(dict[str, Any], item) for item in cast(list[Any], result.get("events") or []) if isinstance(item, dict)
    ]
    next_ms = result.get("nextPollMs")
    found_cursor = result.get("cursor")
    return Poll(
        events=events,
        cursor=str(found_cursor) if found_cursor is not None else cursor,
        next_poll_ms=next_ms if isinstance(next_ms, int) else None,
    )


@dataclass(frozen=True)
class Subscribed:
    refresh_before: datetime.datetime
    cursor: str | None


def new_secret() -> str:
    """A subscription's secret, in the form Standard Webhooks and the extension ask for."""
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()


async def subscribe(
    target: Target,
    token: str | None,
    name: str,
    arguments: dict[str, Any],
    url: str,
    secret: str,
    cursor: str | None,
) -> Subscribed:
    try:
        result = await _call(
            target,
            token,
            "events/subscribe",
            {
                "name": name,
                "arguments": arguments,
                "delivery": {"mode": "webhook", "url": url, "secret": secret},
                "cursor": cursor,
                "ttlMs": 24 * 3600 * 1000,
            },
        )
    except _NotSupportedError:
        raise ServerError("events/subscribe", "the server does not offer events") from None
    refresh = result.get("refreshBefore")
    try:
        refresh_before = datetime.datetime.fromisoformat(str(refresh).replace("Z", "+00:00"))
    except ValueError:
        refresh_before = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    if refresh_before.tzinfo is None:
        refresh_before = refresh_before.replace(tzinfo=datetime.UTC)
    found_cursor = result.get("cursor")
    return Subscribed(refresh_before, str(found_cursor) if found_cursor is not None else cursor)


def signature_valid(secret: str, webhook_id: str, timestamp: str, body: bytes, signatures: str) -> bool:
    """Whether a `v1` signature of a delivery is the HMAC of its ID, timestamp and body (Standard Webhooks)."""
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError:
        return False
    expected = base64.b64encode(
        hmac.new(key, f"{webhook_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    for item in signatures.split():
        version, _, value = item.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False


def fresh(timestamp: str, now: float) -> bool:
    return timestamp.isdigit() and abs(now - int(timestamp)) <= WEBHOOK_TOLERANCE_SECONDS
