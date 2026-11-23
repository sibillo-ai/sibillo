"""Nightly backups, and the health of an instance whose backups fail (OPS-010, OPS-011, ADR-0077).

Making and restoring archives needs the deployment's containers, and is
tested end to end (tests/e2e/test_deployment.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from sibillo_server.backup import (
    BackupError,
    active_conversations,
    check_plain_archive,
    manifest_mac,
    new_backup_key,
    next_backup,
    prune_archives,
    remove_leftovers,
    staging_parent,
)
from sibillo_server.database import create_engine
from sibillo_server.durable import APPLICATION_VERSION
from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run, start_run, wait_for_run
from tests.support.server import Server, fresh_source

NOW = datetime(2026, 11, 5, 21, 30, tzinfo=UTC)


@pytest.mark.spec("OPS-010")
@pytest.mark.parametrize(
    ("now", "at", "expected"),
    [
        (NOW, "03:00", datetime(2026, 11, 6, 3, 0, tzinfo=UTC)),
        (NOW, "23:15", datetime(2026, 11, 5, 23, 15, tzinfo=UTC)),
        (datetime(2026, 11, 6, 3, 0, tzinfo=UTC), "03:00", datetime(2026, 11, 7, 3, 0, tzinfo=UTC)),
    ],
    ids=["tomorrow", "tonight", "just-made"],
)
def test_backups_run_every_day_at_the_chosen_time(now: datetime, at: str, expected: datetime) -> None:
    assert next_backup(now, at) == expected


@pytest.mark.spec("OPS-010")
def test_only_the_newest_archives_are_kept(tmp_path: Path) -> None:
    names = [f"sibillo-2026110{day}T030000Z.tar.age" for day in range(1, 8)]
    for name in names:
        (tmp_path / name).write_bytes(b"archive")
    (tmp_path / "status.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("the household's own file")
    prune_archives(tmp_path, keep=3)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([*names[-3:], "notes.txt", "status.json"])


@pytest.fixture
def instance_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


@pytest.fixture
def some_default(database: Database, default_model: HarnessModel) -> None:
    default_model.connect(create_tenant(database))


def _status(
    started: timedelta | None, attempt: timedelta | None, success: timedelta | None, outcome: str | None
) -> Any:
    now = datetime.now(UTC)

    def at(ago: timedelta | None) -> str | None:
        return None if ago is None else (now - ago).isoformat()

    return {
        "started": at(started),
        "last_attempt": at(attempt),
        "last_success": at(success),
        "outcome": outcome,
        "archive": None,
        "error": "pg_dump failed" if outcome == "failed" else None,
    }


@pytest.mark.spec("OPS-011")
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "degraded"),
        (_status(timedelta(hours=1), None, None, None), "ok"),
        (_status(timedelta(days=5), timedelta(hours=2), timedelta(hours=2), "succeeded"), "ok"),
        (_status(timedelta(days=5), timedelta(hours=2), timedelta(days=1), "failed"), "degraded"),
        (_status(timedelta(days=5), timedelta(days=3), timedelta(days=3), "succeeded"), "degraded"),
        (_status(timedelta(days=3), None, None, None), "degraded"),
    ],
    ids=["missing", "just-started", "recent-success", "last-failed", "stale-success", "never-ran"],
)
def test_backups_that_fail_or_stop_make_the_instance_degraded(
    tmp_path: Path,
    server: Server,
    instance_admin: Account,
    some_default: None,
    status: dict[str, Any] | None,
    expected: str,
) -> None:
    path = tmp_path / "status.json"
    if status is not None:
        path.write_text(json.dumps(status))
    token = login(server, instance_admin)
    api, origin = server.start_twin_api(SIBILLO_BACKUP_STATUS=str(path))
    try:
        headers = {"Authorization": f"Bearer {token}", "X-Forwarded-For": fresh_source()}
        health = httpx.get(f"{origin}/v1/health", headers=headers, timeout=30).json()
        anonymous = httpx.get(f"{origin}/v1/health", headers={"X-Forwarded-For": fresh_source()}, timeout=30).json()
    finally:
        api.close()
    assert health["checks"]["backups"] == expected
    assert health["status"] == expected
    assert anonymous == {"status": expected}


# --- What a backup keeps and a restore trusts (OPS-006, ADR-0130) ---

KEY = new_backup_key()


def _plain_archive(
    folder: Path, files: dict[str, bytes], *, listed: dict[str, bytes] | None = None, key: str = KEY
) -> Path:
    """A decrypted archive as a backup makes one: its files, a manifest of `listed`, and the manifest's MAC."""
    manifest = {
        "version": APPLICATION_VERSION,
        "entries": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in (files if listed is None else listed).items()
        },
    }
    document = (json.dumps(manifest, indent=2) + "\n").encode()
    entries = {"manifest.json": document, "manifest.mac": manifest_mac(document, key).encode(), **files}
    plain = folder / "archive.tar"
    with tarfile.open(plain, "w") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return plain


def _workspace() -> str:
    return f"workspaces/{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}.tar"


@pytest.mark.spec("OPS-006")
def test_an_archive_with_its_manifests_mac_is_unpacked(tmp_path: Path) -> None:
    workspace = _workspace()
    plain = _plain_archive(tmp_path, {"database.dump": b"dump", "secret-key": b"key", workspace: b"tar"})
    contents = check_plain_archive(plain, KEY, tmp_path / "contents")
    assert (contents / workspace).read_bytes() == b"tar"


@pytest.mark.spec("OPS-006")
def test_an_archive_anyone_could_have_made_is_refused(tmp_path: Path) -> None:
    # Made with another key: whoever knows the public recipient could encrypt it, but not compute its MAC.
    plain = _plain_archive(tmp_path, {"database.dump": b"dump"}, key=new_backup_key())
    with pytest.raises(BackupError, match="authenticate"):
        check_plain_archive(plain, KEY, tmp_path / "contents")
    assert not (tmp_path / "contents" / "database.dump").exists()


@pytest.mark.spec("OPS-006")
@pytest.mark.parametrize(
    "extra",
    ["workspaces/x/y/z.tar", "workspaces/../../etc.tar", "notes.txt"],
    ids=["not-uuids", "outside", "not-in-manifest"],
)
def test_an_archive_with_entries_it_should_not_hold_is_refused(tmp_path: Path, extra: str) -> None:
    files = {"database.dump": b"dump", extra: b"x"}
    listed = files if extra != "notes.txt" else {"database.dump": b"dump"}
    plain = _plain_archive(tmp_path, files, listed=listed)
    with pytest.raises(BackupError):
        check_plain_archive(plain, KEY, tmp_path / "contents")


@pytest.mark.spec("OPS-006")
def test_what_an_interrupted_backup_left_is_removed(tmp_path: Path) -> None:
    for name in (".backup-abc", ".restore-def"):
        (tmp_path / name / "contents").mkdir(parents=True)
        (tmp_path / name / "contents" / "database.dump").write_bytes(b"plain")
    (tmp_path / "sibillo-20261101T030000Z.tar.age").write_bytes(b"archive")
    remove_leftovers(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["sibillo-20261101T030000Z.tar.age"]
    # Staged outside the backup folder from now on.
    assert staging_parent() != tmp_path


@pytest.mark.spec("OPS-006", "OPS-010")
def test_a_backup_goes_on_past_runs_still_answering(
    database: Database, server: Server, instance_admin: Account, some_default: None, default_model: HarnessModel
) -> None:
    default_model.connect(instance_admin.tenant_id)
    token = login(server, instance_admin)
    conversation_id = create_conversation(server, token)["id"]
    start_run(server, token, conversation_id, "slow:8", stop_after=1)

    async def wait() -> list[str]:
        engine = create_engine(database.superuser_url)
        try:
            return await active_conversations(engine, seconds=1)
        finally:
            await engine.dispose()

    assert asyncio.run(wait()) == [conversation_id]


@pytest.mark.spec("OPS-006")
def test_a_run_abandoned_for_two_days_is_failed(
    database: Database, server: Server, instance_admin: Account, default_model: HarnessModel
) -> None:
    default_model.connect(instance_admin.tenant_id)
    token = login(server, instance_admin)
    conversation_id = create_conversation(server, token)["id"]
    run_id, _ = start_run(server, token, conversation_id, "left behind")
    wait_for_run(server, token, run_id)
    # As a crash leaves one: running, three days ago (ADR-0130).
    with database.superuser() as conn:
        conn.execute(
            "UPDATE runs SET status = 'running', finished_at = NULL, created_at = now() - interval '3 days'"
            " WHERE id = %s",
            (run_id,),
        )
    deadline = time.monotonic() + 30
    while get_run(server, token, run_id)["status"] == "running":
        assert time.monotonic() < deadline, "the abandoned run stayed running"
        time.sleep(1)
    assert get_run(server, token, run_id)["status"] == "failed"
