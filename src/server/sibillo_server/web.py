"""The web app, served at `/` next to the API (UX-001, ADR-0067).

The app is a static single-page app: its files are served as they are, and
any other path outside the API loads the app, which routes it itself. A share
from another app that reaches the API rather than the app's service worker
opens the app, which says that nothing arrived (UX-006, ADR-0102). Every
response carries a Content Security Policy that allows only the app's own
scripts (UX-002).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from sibillo_server import errors

API_SEGMENT = "v1"
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        # Rendered math sets inline styles; no inline scripts are allowed.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        # Answers read aloud play from audio the app fetched (UX-005).
        "media-src 'self' blob:",
        "connect-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "form-action 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    )
)
HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def router(root: Path) -> APIRouter:
    """Routes serving the built app in `root`; the API's own routes come first."""
    root = root.resolve()
    index = root / "index.html"
    routes = APIRouter(include_in_schema=False)

    @routes.post("/share")
    async def share() -> Response:  # pyright: ignore[reportUnusedFunction]
        # What was shared is not read: the service worker keeps shares on the device, never the server.
        return Response(status_code=303, headers=HEADERS | {"Location": "/?shared=1", "Cache-Control": "no-store"})

    @routes.get("/{path:path}")
    async def serve(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == API_SEGMENT or path.startswith(f"{API_SEGMENT}/"):
            raise errors.not_found()
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            return Response(status_code=404, headers=HEADERS)
        if candidate.is_file():
            # Only the files under assets/ have a hash of their content in their names, so a new version has
            # new names; every other file, the page and the service worker first, is asked for again (UX-040,
            # ADR-0112).
            hashed = candidate.is_relative_to(root / "assets")
            cache = "public, max-age=31536000, immutable" if hashed else "no-cache"
            return FileResponse(candidate, headers=HEADERS | {"Cache-Control": cache})
        if Path(path).suffix:
            # A missing file, not a route of the app.
            return Response(status_code=404, headers=HEADERS)
        return FileResponse(index, headers=HEADERS | {"Cache-Control": "no-cache"})

    return routes
