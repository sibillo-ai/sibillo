"""A sandbox cannot fill the host's disk, nor reach its workspace's raw disk (SBX-016, ADR-0098).

The session's limits are small (tests/support/sandbox.py): 64 MiB outside the
workspace, and an 8 MiB quota, whose disk is the quota plus 10% and 32 MiB.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from tests.support.database import uuid7
from tests.support.sandbox import SANDBOX_DISK_BYTES, WORKSPACE_DISK_BYTES, Driver, docker

MIB = 1024 * 1024


def _sandbox() -> tuple[str, str, str]:
    """A tenant, a user and a conversation of theirs: one sandbox (SBX-001)."""
    return str(uuid7()), str(uuid7()), str(uuid7())


def _size(driver: Driver, sandbox: tuple[str, str, str], path: str) -> int:
    result = driver.sh(*sandbox, f"stat -c %s {path}")
    assert result.exit_code == 0, result
    return int(result.stdout.strip())


@pytest.mark.spec("SBX-016")
def test_the_disk_outside_the_workspace_is_limited(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    total = sandboxes.sh(*sandbox, "df -B1 --output=size / | tail -1")
    assert int(total.stdout.strip()) <= SANDBOX_DISK_BYTES
    written = sandboxes.sh(
        *sandbox, f"head -c {SANDBOX_DISK_BYTES + 32 * MIB} /dev/zero > /scratch/big", timeout_seconds=8
    )
    assert written.exit_code not in (0, None), written
    assert "No space left on device" in written.stderr
    assert _size(sandboxes, sandbox, "/scratch/big") <= SANDBOX_DISK_BYTES


@pytest.mark.spec("SBX-016", "SBX-010")
def test_a_workspace_cannot_grow_past_its_disk_and_keeps_its_files(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    assert sandboxes.sh(*sandbox, "echo kept > /workspace/kept.txt").exit_code == 0
    total = sandboxes.sh(*sandbox, "df -B1 --output=size /workspace | tail -1")
    assert int(total.stdout.strip()) <= WORKSPACE_DISK_BYTES
    written = sandboxes.sh(
        *sandbox, f"head -c {WORKSPACE_DISK_BYTES + 32 * MIB} /dev/zero > /workspace/big", timeout_seconds=8
    )
    assert written.exit_code not in (0, None), written
    assert "No space left on device" in written.stderr
    assert _size(sandboxes, sandbox, "/workspace/big") <= WORKSPACE_DISK_BYTES
    # Full, it still holds what it held, in the next sandbox too.
    sandboxes.stop(*sandbox)
    assert sandboxes.sh(*sandbox, "cat /workspace/kept.txt").stdout == "kept\n"
    # And it is usable again once tidied up.
    assert sandboxes.sh(*sandbox, "rm /workspace/big && echo again > /workspace/again.txt").exit_code == 0


@pytest.mark.spec("SBX-016", "SBX-019")
def test_a_workspace_holds_a_quota_of_files(sandboxes: Driver) -> None:
    """The disk is larger than the quota, so that the agent can be told it exceeds it (SBX-019)."""
    sandbox = _sandbox()
    result = sandboxes.sh(*sandbox, "head -c 9000000 /dev/zero > /workspace/over-quota")
    assert result.exit_code == 0, result
    assert result.workspace_bytes is not None
    assert result.workspace_quota_bytes is not None
    assert result.workspace_bytes > result.workspace_quota_bytes


@pytest.mark.spec("SBX-016", "SBX-012")
def test_sandboxes_cannot_reach_the_raw_disk_of_their_workspace(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    devices = sandboxes.sh(*sandbox, "find /dev -type b; ls /dev | grep -c '^loop' || true")
    assert devices.stdout.strip() == "0", devices.stdout
    (container,) = sandboxes.running(sandbox[2])
    mounts = {mount["Destination"]: mount for mount in container["Mounts"]}
    assert set(mounts) == {"/workspace", "/skills"}
    workspace = cast(list[dict[str, Any]], json.loads(docker("volume", "inspect", mounts["/workspace"]["Name"])))[0]
    # The workspace is the filesystem the host's kernel mounted from the disk, not a folder holding it.
    options = cast(dict[str, str], workspace.get("Options") or {})
    assert options.get("type") == "ext4"
    assert str(options.get("device", "")).startswith("/dev/loop")
    for flag in ("nodev", "nosuid"):
        assert flag in str(options.get("o", "")).split(",")


@pytest.mark.spec("SBX-016", "SBX-003")
def test_the_driver_reports_that_disks_can_be_attached(sandboxes: Driver) -> None:
    with sandboxes.client() as client:
        health = client.get("/health").json()
    assert health["checks"]["disks"]["ok"] is True
    assert health["checks"]["canary"]["ok"] is True


@pytest.mark.spec("SBX-016", "SBX-012")
def test_only_the_disk_helper_is_privileged(sandboxes: Driver) -> None:
    """Every container of the sandbox image that runs user content stays under gVisor, unprivileged."""
    sandbox = _sandbox()
    sandboxes.sh(*sandbox, "true")
    for container in sandboxes.sandbox_containers():
        host: dict[str, Any] = container["HostConfig"]
        if host["Privileged"]:
            assert host["Runtime"] == "runc"
            assert host["NetworkMode"] == "none"
            assert all(mount["Type"] == "volume" for mount in container["Mounts"])
        else:
            assert host["Runtime"] == "runsc"
