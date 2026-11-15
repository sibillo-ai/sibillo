"""Workspace disks: made, attached and detached by the driver, and old workspaces converted (SBX-016, ADR-0098).

The driver's tests use its API directly. A workspace from before ADR-0098 is
arranged as the driver made it then: a plain Docker volume named after the
conversation, holding the files themselves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.database import uuid7
from tests.support.sandbox import SANDBOX_LABEL, Driver, docker

MIB = 1024 * 1024


def _sandbox() -> tuple[str, str, str]:
    """A tenant, a user and a conversation of theirs: one sandbox (SBX-001)."""
    return str(uuid7()), str(uuid7()), str(uuid7())


def _backing_files() -> list[str]:
    """The files behind the host's loop devices, as the host's kernel reports them."""
    files: list[str] = []
    for path in Path("/sys/block").glob("loop*/loop/backing_file"):
        try:
            files.append(path.read_text().strip())
        except OSError:
            continue
    return files


def _attached(conversation_id: str) -> bool:
    return any(conversation_id in file for file in _backing_files())


def _volumes(conversation_id: str) -> list[str]:
    return docker("volume", "ls", "-q", "--filter", f"label={SANDBOX_LABEL}.conversation={conversation_id}").split()


@pytest.mark.spec("SBX-016", "SBX-010")
def test_deleting_a_workspace_detaches_and_deletes_its_disk(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "echo x > /workspace/x").exit_code == 0
    assert _attached(conversation_id), _backing_files()
    with sandboxes.client() as client:
        response = client.delete(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/workspace")
    assert response.status_code == 204, response.text
    assert not _attached(conversation_id), _backing_files()
    assert _volumes(conversation_id) == []


@pytest.mark.spec("SBX-016", "SBX-014")
def test_file_operations_see_the_disk_a_run_wrote(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    assert (
        sandboxes.sh(
            tenant_id, user_id, conversation_id, "mkdir -p /workspace/a && echo hi > /workspace/a/b.txt"
        ).exit_code
        == 0
    )
    with sandboxes.client() as client:
        listed = client.get(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/entries", params={"path": "a"})
        sized = client.get(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/size")
    assert listed.status_code == 200, listed.text
    assert [entry["name"] for entry in listed.json()["entries"]] == ["b.txt"]
    assert sized.status_code == 200, sized.text
    assert sized.json()["bytes"] > 0


@pytest.mark.spec("SBX-016", "SBX-010")
def test_an_old_workspace_is_converted_keeping_its_files(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    volume = f"sibillo-workspace-{tenant_id}-{user_id}-{conversation_id}"
    labels = {
        SANDBOX_LABEL: "workspace",
        f"{SANDBOX_LABEL}.tenant": tenant_id,
        f"{SANDBOX_LABEL}.user": user_id,
        f"{SANDBOX_LABEL}.conversation": conversation_id,
        f"{SANDBOX_LABEL}.image": sandboxes.image,
    }
    docker("volume", "create", *(f"--label={key}={value}" for key, value in labels.items()), volume)
    # More than the quota: the converted disk must still hold it.
    big = 12 * MIB
    docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        f"{volume}:/w",
        "--entrypoint",
        "sh",
        sandboxes.image,
        "-c",
        "mkdir -p /w/notes && echo kept > /w/notes/a.txt && ln -s notes/a.txt /w/link"
        f" && head -c {big} /dev/zero > /w/big.bin && mkfifo /w/fifo",
    )
    result = sandboxes.sh(
        tenant_id,
        user_id,
        conversation_id,
        "cat /workspace/notes/a.txt; readlink /workspace/link; stat -c %s /workspace/big.bin;"
        " test -e /workspace/fifo && echo fifo || echo no-fifo; df -B1 --output=size /workspace | tail -1",
    )
    assert result.exit_code == 0, result
    kept, link, size, fifo, disk = result.stdout.split()
    assert (kept, link, int(size)) == ("kept", "notes/a.txt", big)
    # Only files, folders and links are copied, as workspace archives hold them (SBX-020).
    assert fifo == "no-fifo"
    # A disk of its own, large enough for the files and limited.
    assert big < int(disk) <= big * 11 // 10 + 32 * MIB
    assert _attached(conversation_id)
    # Still there in the next sandbox: the conversion happens once.
    sandboxes.stop(tenant_id, user_id, conversation_id)
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "cat /workspace/notes/a.txt").stdout == "kept\n"
