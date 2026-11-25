"""The fake sandbox driver of the agent tier behaves as the real one (ADR-0139, ADR-0141).

The same scenarios run against the real driver, on the session's engine, and against the fake, in the
test process; a fake that answers differently fails here, never silently. SBX-014, SBX-019 and SBX-020.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Protocol

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.fake_sandboxes import start_fake_driver
from tests.support.sandbox import Driver


class DriverUnderTest(Protocol):
    def client(self, token: str | None = None) -> httpx.Client: ...


@pytest.fixture(scope="module")
def fake() -> Iterator[DriverUnderTest]:
    driver = start_fake_driver()
    yield driver
    driver.close()


@pytest.fixture(params=["real", "fake"])
def driver(request: pytest.FixtureRequest) -> DriverUnderTest:
    if request.param == "fake":
        return request.getfixturevalue("fake")
    real: Driver = request.getfixturevalue("sandboxes")
    return real


@pytest.fixture
def sandbox() -> str:
    return f"/sandboxes/{uuid7()}/{uuid7()}/{uuid7()}"


def _run(client: httpx.Client, sandbox: str, command: str) -> tuple[str, str, dict[str, Any]]:
    """The output and the exit of a shell command, from the driver's lines of JSON."""
    out, err = "", ""
    exit_object: dict[str, Any] = {}
    with client.stream("POST", f"{sandbox}/exec", json={"shell_command": command}, timeout=60) as response:
        assert response.status_code == 200, response.read()
        for line in response.iter_lines():
            if not line:
                continue
            item = json.loads(line)
            if item["kind"] == "output":
                out, err = (out + item["data"], err) if item["stream"] == "stdout" else (out, err + item["data"])
            else:
                exit_object = item
    return out, err, exit_object


def _put(client: httpx.Client, sandbox: str, path: str, content: bytes) -> httpx.Response:
    return client.put(f"{sandbox}/files", params={"path": path}, content=content)


@pytest.mark.spec("SBX-001")
def test_the_driver_answers_only_to_its_token(driver: DriverUnderTest, sandbox: str) -> None:
    with driver.client("wrong") as client:
        assert client.post(f"{sandbox}/ensure", json={"internet_access": False}).status_code == 401


@pytest.mark.spec("SBX-001")
def test_a_sandbox_is_ensured_and_runs_commands(driver: DriverUnderTest, sandbox: str) -> None:
    with driver.client() as client:
        ensured = client.post(f"{sandbox}/ensure", json={"internet_access": False})
        assert ensured.status_code == 200
        assert ensured.json()["state"] == "running"
        assert ensured.json()["internet_access"] is False
        out, _, exit_object = _run(client, sandbox, "echo hello")
        assert out == "hello\n"
        assert exit_object["exit_code"] == 0
        assert exit_object["timed_out"] is False
        assert exit_object["workspace_quota_bytes"] > 0
        assert _run(client, sandbox, "exit 3")[2]["exit_code"] == 3


@pytest.mark.spec("SBX-014")
def test_files_are_written_listed_read_and_never_replaced(driver: DriverUnderTest, sandbox: str) -> None:
    with driver.client() as client:
        written = _put(client, sandbox, "notes/a.txt", b"alpha")
        assert written.status_code == 201
        assert (written.json()["path"], written.json()["type"], written.json()["size"]) == ("notes/a.txt", "file", 5)
        assert _put(client, sandbox, "notes/a.txt", b"beta").status_code == 409
        listed = client.get(f"{sandbox}/entries", params={"path": "notes"}).json()["entries"]
        assert [(entry["name"], entry["type"]) for entry in listed] == [("a.txt", "file")]
        assert client.get(f"{sandbox}/files", params={"path": "notes/a.txt"}).content == b"alpha"
        assert client.get(f"{sandbox}/files", params={"path": "notes"}).status_code == 422
        assert client.get(f"{sandbox}/files", params={"path": "missing"}).status_code == 404
        assert client.get(f"{sandbox}/size").json()["bytes"] >= 5


@pytest.mark.spec("SBX-014")
def test_folders_are_created_moved_and_deleted(driver: DriverUnderTest, sandbox: str) -> None:
    with driver.client() as client:
        assert client.post(f"{sandbox}/folders", json={"path": "one"}).status_code == 201
        assert client.post(f"{sandbox}/folders", json={"path": "one"}).status_code == 409
        _put(client, sandbox, "one/f.txt", b"x")
        moved = client.post(f"{sandbox}/move", json={"from": "one", "to": "two"})
        assert moved.status_code == 200
        assert client.get(f"{sandbox}/files", params={"path": "two/f.txt"}).content == b"x"
        assert client.delete(f"{sandbox}/entries", params={"path": "two"}).status_code == 204
        assert client.get(f"{sandbox}/entries", params={"path": "two"}).status_code == 404


@pytest.mark.spec("SBX-014")
@pytest.mark.parametrize("path", ["../escaped", "a/../../escaped", "/absolute"])
def test_paths_that_leave_the_workspace_are_refused(driver: DriverUnderTest, sandbox: str, path: str) -> None:
    with driver.client() as client:
        assert _put(client, sandbox, path, b"x").status_code == 422


@pytest.mark.spec("SBX-020")
def test_a_workspace_is_exported_and_imported(driver: DriverUnderTest, sandbox: str) -> None:
    other = f"/sandboxes/{uuid7()}/{uuid7()}/{uuid7()}"
    with driver.client() as client:
        _put(client, sandbox, "kept/a.txt", b"kept")
        archive = client.get(f"{sandbox}/workspace")
        assert archive.status_code == 200
        imported = client.put(
            f"{other}/workspace", content=archive.content, headers={"Content-Type": "application/x-tar"}
        )
        assert imported.status_code == 204
        assert client.get(f"{other}/files", params={"path": "kept/a.txt"}).content == b"kept"
        assert client.delete(f"{other}/workspace").status_code == 204
        assert client.get(f"{other}/files", params={"path": "kept/a.txt"}).status_code == 404


@pytest.mark.spec("SBX-019")
def test_a_write_over_the_quota_is_refused_whole(driver: DriverUnderTest, sandbox: str) -> None:
    with driver.client() as client:
        size = client.get(f"{sandbox}/size").json()["quota_bytes"] + 1
        assert _put(client, sandbox, "big", b"x" * size).status_code == 413
        assert client.get(f"{sandbox}/files", params={"path": "big"}).status_code == 404
