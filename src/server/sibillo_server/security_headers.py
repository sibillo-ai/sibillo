"""Headers every answer carries, so that it stays out of caches, frames and other origins (AUTH-005, ADR-0131).

Every answer: no referrer, a browsing context and resources of its own origin,
and powerful features only where the app uses them, the microphone for voice
(UX-005). The API's answers also: no sniffing and no store. With an `https`
public origin, browsers keep to `https` for a year.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

COMMON = (
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(self), geolocation=(), payment=(), usb=(), serial=()"),
)
API = ((b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store"))
HSTS = (b"strict-transport-security", b"max-age=31536000")


class SecurityHeaders:
    """Adds the headers an answer lacks; one a route set itself, such as a file's own cache policy, is kept."""

    def __init__(self, app: ASGIApp, *, prefix: str, https: bool) -> None:
        self.app, self.prefix, self.https = app, prefix, https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        wanted = [
            *COMMON,
            *(API if path == self.prefix or path.startswith(f"{self.prefix}/") else ()),
            *((HSTS,) if self.https else ()),
        ]

        async def sending(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [(name, value) for name, value in wanted if name not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, sending)
