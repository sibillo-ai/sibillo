"""Images the model sees: attached to a message, or looked at with a tool (CNV-020, ADR-0110).

The history keeps where an image is, its path in the workspace and the
SHA-256 of its bytes, never the image. Before each request the image is read
again from the workspace, through the sandbox driver, and put in the place of
its reference; an image that is gone or changed becomes a line that says so.
An image is told by its first bytes and is never decoded here.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from typing import Any, cast

import httpx
from pydantic_ai import BinaryContent, RunContext, Tool, ToolReturn
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)

from sibillo_server.gateway import RunDeps
from sibillo_server.tool_policy import ATTACHMENTS_ORIGIN

logger = logging.getLogger(__name__)

# The largest image that reaches the model.
IMAGE_MAX_BYTES = 5 * 1024 * 1024
DRIVER_TIMEOUT_SECONDS = 60
CHUNK_BYTES = 64 * 1024
# Labels the result of `view_image` with the image it shows.
IMAGE_ORIGIN = "sibillo.image"
VIEW_IMAGE = "view_image"
# What a model that does not accept images is told with the listing of attachments.
CANNOT_SEE = (
    "You cannot see images with this model. If any of these files is an image, tell the user that this model"
    " cannot see images, rather than trying to read it some other way."
)


def media_type(head: bytes) -> str | None:
    """The type of an image, from its first bytes; None for anything else."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def workspace_path(path: str) -> str:
    """A path of the workspace as the driver names it, from `/workspace/a.png` or `a.png`."""
    return path.strip().removeprefix("/workspace").strip("/")


async def _read(deps: RunDeps, path: str) -> bytes | str:
    """The bytes of a file of the workspace, or why they are not an image to send."""
    sandbox = f"{deps.sandboxd_url}/sandboxes/{deps.identity.tenant_id}/{deps.identity.user_id}/{deps.conversation_id}"
    try:
        async with (
            httpx.AsyncClient(
                headers={"Authorization": f"Bearer {deps.sandboxd_token}"}, timeout=DRIVER_TIMEOUT_SECONDS
            ) as client,
            client.stream("GET", f"{sandbox}/files", params={"path": path}) as response,
        ):
            if response.status_code != 200:
                return "there is no such file"
            data = bytearray()
            async for chunk in response.aiter_bytes(CHUNK_BYTES):
                data += chunk
                if len(data) > IMAGE_MAX_BYTES:
                    return "it is larger than 5 MiB; make a smaller copy with a command and look at that"
    except httpx.HTTPError:
        logger.warning("run %s: an image could not be read from the workspace", deps.run_id)
        return "the workspace could not be reached now"
    if media_type(bytes(data[:16])) is None:
        return "it is not a PNG, JPEG, WebP or GIF image; convert it with a command and look at the result"
    return bytes(data)


def _reference(path: str, data: bytes) -> dict[str, str]:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest()}


async def references(deps: RunDeps, attachments: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Where the images among a message's attachments are: each `{path, sha256}` (ADR-0110)."""
    found: list[dict[str, str]] = []
    for item in attachments:
        if int(item.get("size", 0)) > IMAGE_MAX_BYTES:
            continue
        data = await _read(deps, str(item["path"]))
        if isinstance(data, bytes):
            found.append(_reference(str(item["path"]), data))
    return found


async def _shown(deps: RunDeps, reference: dict[str, Any]) -> UserContent:
    """The image a reference names, or a line saying that it is no longer there."""
    path = str(reference.get("path", ""))
    data = await _read(deps, path)
    if isinstance(data, bytes) and hashlib.sha256(data).hexdigest() == reference.get("sha256"):
        return BinaryContent(data=data, media_type=media_type(data[:16]) or "image/png")
    return f"The image /workspace/{path} is no longer in the workspace as it was: the file changed or is gone."


async def _prompt(deps: RunDeps, part: UserPromptPart) -> UserPromptPart:
    if isinstance(part.content, str):
        return part
    content: list[UserContent] = []
    for item in part.content:
        content.append(item)
        metadata: Any = getattr(item, "metadata", None)
        if isinstance(metadata, dict) and cast(dict[str, Any], metadata).get("origin") == ATTACHMENTS_ORIGIN:
            listed = cast(list[dict[str, Any]], cast(dict[str, Any], metadata).get("images") or [])
            content.extend([await _shown(deps, reference) for reference in listed])
    return part if len(content) == len(part.content) else replace(part, content=content)


async def with_images(deps: RunDeps, messages: list[ModelMessage]) -> list[ModelMessage]:
    """The messages as the model receives them: each reference to an image replaced by the image.

    Only for a model that accepts images; the run's own history keeps the
    references, so nothing stored holds an image.
    """
    if not deps.images:
        return messages
    shown: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            shown.append(message)
            continue
        parts: list[ModelRequestPart] = []
        looked: list[UserContent] = []
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                parts.append(await _prompt(deps, part))
                continue
            parts.append(part)
            metadata: Any = part.metadata if isinstance(part, ToolReturnPart) else None
            reference: Any = cast(dict[str, Any], metadata).get(IMAGE_ORIGIN) if isinstance(metadata, dict) else None
            if isinstance(reference, dict):
                looked.append(await _shown(deps, cast(dict[str, Any], reference)))
        if looked:
            # After the results of the tools, as a message of its own: a tool's result is text.
            parts.append(UserPromptPart(content=looked))
        changed = len(parts) != len(message.parts) or any(a is not b for a, b in zip(parts, message.parts, strict=True))
        shown.append(replace(message, parts=parts) if changed else message)
    return shown


async def view_image(ctx: RunContext[RunDeps], path: str) -> ToolReturn:
    """Look at an image file of the workspace: a PNG, JPEG, WebP or GIF image of at most 5 MiB.

    The image itself follows the result. Use it for images you made or found, and for images the user
    attached that were too large or in another format, once converted.

    Args:
        path: The image's path in /workspace, such as `/workspace/uploads/photo.jpg` or `charts/plot.png`.
    """
    relative = workspace_path(path)
    data = await _read(ctx.deps, relative) if relative else "there is no such file"
    if isinstance(data, str):
        return ToolReturn(return_value=f"No image is shown for /workspace/{relative}: {data}.")
    return ToolReturn(
        return_value=f"The image /workspace/{relative} ({len(data)} bytes) follows.",
        metadata={IMAGE_ORIGIN: _reference(relative, data)},
    )


TOOLS = (Tool(view_image),)
