"""The network guard, as the driver reaches it: over the Unix socket only the two share (ADR-0113, ADR-0114).

The guard owns the egress table. The driver asks it for its health, and
gives it the whole list of the sandbox bridges that have network (SBX-024).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

GUARD_TIMEOUT_SECONDS = 5.0


class GuardUnavailableError(Exception):
    """The guard did not answer, or did not do what it was asked: the egress table counts as missing (SBX-015)."""


async def ask_guard(path: str, request: dict[str, Any]) -> dict[str, Any]:
    """One request to the network guard: a JSON object on a line, answered the same way."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), GUARD_TIMEOUT_SECONDS)
        try:
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), GUARD_TIMEOUT_SECONDS)
        finally:
            writer.close()
        answer = json.loads(line)
    except (OSError, TimeoutError, ValueError) as error:
        raise GuardUnavailableError(f"the network guard does not answer: {error or type(error).__name__}") from error
    if not isinstance(answer, dict):
        raise GuardUnavailableError("the network guard's answer is not an object")
    return cast(dict[str, Any], answer)


async def give_online(path: str, bridges: set[str]) -> None:
    """Make the guard's set of bridges with network exactly `bridges`, and check that it is (SBX-024)."""
    expected = sorted(bridges)
    answer = await ask_guard(path, {"op": "online", "bridges": expected})
    if answer.get("online") != expected:
        raise GuardUnavailableError(f"the network guard did not take the bridges with network: {answer}")
