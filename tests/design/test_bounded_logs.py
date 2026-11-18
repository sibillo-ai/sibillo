"""The logs of every service stay within a bounded size, in Docker (OBS-005, ADR-0104)."""

from __future__ import annotations

import re
from typing import Any, cast

import pytest
import yaml

from tests.support.deployment import COMPOSE_FILE

# Drivers that keep logs on the host's disk, where `docker compose logs`
# reads them, and need no change to the host.
KEPT_IN_DOCKER = {"json-file", "local"}
# At most this much per service (ADR-0104: 3 files of 10 MB).
LIMIT_BYTES = 30 * 1000 * 1000
UNITS = {"": 1, "b": 1, "k": 1000, "m": 1000 * 1000, "g": 1000 * 1000 * 1000}


def _services() -> dict[str, dict[str, Any]]:
    compose = cast("dict[str, Any]", yaml.safe_load(COMPOSE_FILE.read_text()))
    return cast("dict[str, dict[str, Any]]", compose["services"])


def _bytes(size: str) -> int:
    match = re.fullmatch(r"(\d+)([bkmg]?)", size.strip().lower())
    assert match, f"unreadable max-size {size!r}"
    return int(match.group(1)) * UNITS[match.group(2)]


def test_the_compose_file_has_services() -> None:
    assert {"api", "worker", "postgres", "sandboxd"} <= set(_services())


@pytest.mark.spec("OBS-005")
@pytest.mark.parametrize("name", sorted(_services()))
def test_every_service_keeps_its_logs_in_docker_within_a_bounded_size(name: str) -> None:
    logging = _services()[name].get("logging")
    assert logging, f"{name} keeps its logs with Docker's default, which never deletes them"
    driver = logging.get("driver")
    if driver == "none":
        return
    assert driver in KEPT_IN_DOCKER, f"{name} logs through {driver!r}, which docker compose logs cannot read"
    options = cast("dict[str, str]", logging.get("options") or {})
    assert "max-size" in options, f"{name} has no max-size"
    assert "max-file" in options, f"{name} has no max-file"
    assert _bytes(str(options["max-size"])) * int(options["max-file"]) <= LIMIT_BYTES
