"""Request bodies are bounded before any operation runs (API-009, ADR-0119).

Every body is limited to 1 MiB, except for the operations that take files,
which state larger limits. A declared length over the limit is refused before
anything is read; a body without one, or longer than it said, is counted as
it arrives and refused once it passes the limit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sibillo_server.errors import PROBLEM_MEDIA_TYPE

MIB = 1024 * 1024
DEFAULT_LIMIT = MIB


@dataclass(frozen=True)
class _Limit:
    method: str
    path: re.Pattern[str]
    bytes: int | None  # None: the route bounds it by the instance's upload limit


def _limits(prefix: str) -> tuple[_Limit, ...]:
    return (
        # A 25 MiB recording and its form (API-006).
        _Limit("POST", re.compile(rf"^{prefix}/speech/transcriptions$"), 26 * MIB),
        # A skill's archive and its form, as the route reads it (ADR-0096).
        _Limit("POST", re.compile(rf"^{prefix}/me/skills$"), 21 * MIB),
        # 1 MiB of text, escaped in JSON.
        _Limit("PUT", re.compile(rf"^{prefix}/me/skills/[^/]+/file$"), 7 * MIB),
        # Files of a workspace: the route requires a declared length and refuses one over the instance's upload
        # limit with `file.too_large`, then streams the body to the driver without holding it (SBX-019, ADR-0079).
        _Limit("PUT", re.compile(rf"^{prefix}/conversations/[^/]+/workspace/file$"), None),
        _Limit("POST", re.compile(rf"^{prefix}/conversations/[^/]+/workspace/uploads$"), None),
    )


class BodyTooLargeError(Exception):
    """Raised to the route that reads a body past its limit."""


class BodyLimits:
    """ASGI middleware that refuses a request body over its operation's limit with `413 request.too_large`."""

    def __init__(self, app: ASGIApp, *, prefix: str) -> None:
        self.app = app
        self.limits = _limits(prefix)

    def limit_of(self, method: str, path: str) -> int | None:
        """The operation's limit; None for the uploads that bound themselves."""
        for limit in self.limits:
            if limit.method == method and limit.path.match(path):
                return limit.bytes
        return DEFAULT_LIMIT

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_of(scope["method"], scope["path"])
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _refuse(send)
            return
        received = 0
        exceeded = False
        started = False

        async def counted() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise BodyTooLargeError
            return message

        async def sending(message: Message) -> None:
            nonlocal started
            # Whatever the route answers to a body it could not finish reading, the answer is 413.
            if exceeded:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, sending)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await _refuse(send)


async def _refuse(send: Send) -> None:
    content = json.dumps(
        {"type": "about:blank", "title": "Too large", "status": 413, "code": "request.too_large"}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", PROBLEM_MEDIA_TYPE.encode()),
                (b"content-length", str(len(content)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": content})
