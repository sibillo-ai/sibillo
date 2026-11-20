"""The stream of the user's changes (API-008, ADR-0108).

The API and the worker announce each change with `pg_notify` on the channel
`sibillo_changes`, in the transaction that makes it, so that it is announced
exactly when it is committed. Each API process listens on one connection and
forwards an event to the open streams of its tenant and user only. Events
carry identifiers, never content, and nothing is kept: a client that
reconnects reloads what it shows.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server.auth import Authenticated
from sibillo_server.database import Identity

logger = logging.getLogger(__name__)
# The driver has no type stubs; this module uses only `connect` and three methods of its connections.
_DRIVER: Any = asyncpg
router = APIRouter()

CHANNEL = "sibillo_changes"
HEARTBEAT_SECONDS = 15
RECONNECT_SECONDS = 2
# Events a slow client may fall behind by before its stream ends, and it reconnects.
QUEUE_EVENTS = 1000


async def announce(connection: AsyncConnection, identity: Identity, event: dict[str, Any]) -> None:
    """Announce a change of the user, when the caller's transaction commits (ADR-0108)."""
    payload = {"tenant_id": str(identity.tenant_id), "user_id": str(identity.user_id), "event": event}
    await connection.execute(
        text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": json.dumps(payload)}
    )


def event(kind: str, **ids: uuid.UUID | str | None) -> dict[str, Any]:
    return {"type": kind, **{name: str(value) for name, value in ids.items() if value is not None}}


class Listener:
    """One process's listening connection, and the streams open on it, by tenant and user."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._streams: dict[tuple[str, str], set[asyncio.Queue[dict[str, Any] | None]]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _listen(self) -> None:
        while True:
            connection: Any = None
            try:
                connection = await _DRIVER.connect(self._url, server_settings={"application_name": "sibillo-changes"})
                await connection.add_listener(CHANNEL, self._received)
                self._ready.set()
                while True:
                    await asyncio.sleep(HEARTBEAT_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("the stream of changes lost its database connection; reconnecting")
                self._ready.clear()
                # Streams that may have missed events end, and their clients reload (ADR-0108).
                for queues in self._streams.values():
                    for queue in queues:
                        queue.put_nowait(None)
                await asyncio.sleep(RECONNECT_SECONDS)
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()

    def _received(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            message = json.loads(payload)
            key = (str(message["tenant_id"]), str(message["user_id"]))
            change = dict(message["event"])
        except (ValueError, KeyError, TypeError):
            return
        for queue in list(self._streams.get(key, ())):
            if queue.qsize() >= QUEUE_EVENTS:
                queue.put_nowait(None)
            else:
                queue.put_nowait(change)

    async def follow(self, identity: Identity) -> AsyncIterator[str]:
        key = (str(identity.tenant_id), str(identity.user_id))
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._streams[key].add(queue)
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._ready.wait(), 10)
            yield ": open\n\n"
            while True:
                try:
                    change = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if change is None:
                    return
                yield f"event: {change['type']}\ndata: {json.dumps(change, separators=(',', ':'))}\n\n"
        finally:
            self._streams[key].discard(queue)
            if not self._streams[key]:
                del self._streams[key]


def listener_of(request: Request) -> Listener:
    found = request.app.state.changes
    if not isinstance(found, Listener):
        raise RuntimeError("the stream of changes is not started")
    return found


@router.get("/me/events")
async def stream_my_changes(identity: Authenticated, request: Request) -> StreamingResponse:
    return StreamingResponse(
        listener_of(request).follow(identity),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
