"""A fake sandbox driver, in the test process, for the agent tier (ADR-0139, ADR-0141).

It is the real driver's HTTP application (authentication, validation, error answers) over sandboxes kept
in memory: a workspace of folders and files, and a small shell that knows `echo`, `printf`, `cat`, `ls`,
`mkdir`, `touch`, `pwd`, `sleep`, `true`, `false` and `exit`, redirections to a file and `&&` and `;`.
Nothing runs on the host. A command it does not know exits with 127, as a shell does, so that a test that
needs a real command is a test of the infrastructure tier. The contract suite
(`tests/integration/test_sandbox_fake_contract.py`) runs the same scenarios against it and against the
real driver, so that it cannot drift unseen.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import io
import secrets
import shlex
import tarfile
import threading
import time
import zipfile
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from sibillo_sandboxd.app import create_app
from sibillo_sandboxd.config import load_configuration
from sibillo_sandboxd.files import FileOperationError, relative
from sibillo_sandboxd.isolation import Check, IsolationState
from sibillo_sandboxd.policy import SandboxId
from sibillo_sandboxd.sandboxes import Exit, Output
from tests.support.server import free_port

QUOTA_BYTES = 8 * 1024 * 1024
SCRATCH = "/scratch"
WORKSPACE = "/workspace"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


@dataclass
class _Box:
    files: dict[str, bytes] = field(default_factory=dict[str, bytes])
    folders: set[str] = field(default_factory=set[str])
    scratch: dict[str, bytes] = field(default_factory=dict[str, bytes])
    internet_access: bool = False
    running: bool = False
    started_at: str = ""
    skills: bytes = b""


class FakeSandboxes:
    """What `sibillo_sandboxd.sandboxes.Sandboxes` offers the driver's routes, in memory."""

    def __init__(self) -> None:
        self.boxes: dict[SandboxId, _Box] = {}
        self.stopped: list[SandboxId] = []

    def _box(self, sandbox: SandboxId) -> _Box:
        return self.boxes.setdefault(sandbox, _Box())

    # --- Sandboxes ---

    async def ensure(self, sandbox: SandboxId, internet_access: bool | None = None) -> dict[str, Any]:
        box = self._box(sandbox)
        if not box.running:
            box.running, box.started_at = True, _now()
        if internet_access is not None:
            box.internet_access = internet_access
        return {
            "state": "running",
            "started_at": box.started_at,
            "working_dir": SCRATCH,
            "internet_access": box.internet_access,
        }

    async def withdraw_network(self, sandbox: SandboxId) -> None:
        self._box(sandbox).internet_access = False

    async def stop(self, sandbox: SandboxId) -> None:
        box = self._box(sandbox)
        box.running, box.scratch = False, {}
        self.stopped.append(sandbox)

    async def set_skills(self, sandbox: SandboxId, source: Path) -> None:
        self._box(sandbox).skills = await asyncio.to_thread(source.read_bytes)

    async def shutdown(self) -> None:
        return None

    # --- Commands ---

    async def execute(
        self,
        sandbox: SandboxId,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
        timeout_seconds: int | None = None,
        max_output_bytes: int | None = None,
    ) -> AsyncIterator[Output | Exit]:
        box = self._box(sandbox)
        if not box.running:
            await self.ensure(sandbox)
        started = time.monotonic()
        script = argv[2] if argv[:2] == ["sh", "-c"] and len(argv) == 3 else shlex.join(argv)
        code, out, err, timed_out = await _shell(box, script, timeout_seconds)
        if out:
            yield Output("stdout", out)
        if err:
            yield Output("stderr", err)
        used = sum(len(content) for content in box.files.values())
        yield Exit(
            exit_code=None if timed_out else code,
            timed_out=timed_out,
            truncated=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            workspace_bytes=used,
            workspace_quota_bytes=QUOTA_BYTES,
        )

    # --- The workspace as a whole ---

    async def export_workspace(self, sandbox: SandboxId, destination: Path) -> None:
        box = self._box(sandbox)
        with tarfile.open(destination, "w") as archive:
            for folder in sorted(box.folders):
                member = tarfile.TarInfo(folder)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            for path, content in sorted(box.files.items()):
                member = tarfile.TarInfo(path)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    async def import_workspace(self, sandbox: SandboxId, source: Path) -> None:
        box = self._box(sandbox)
        box.files, box.folders = {}, set()
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                name = relative(member.name.removeprefix("./"))
                if member.isdir():
                    box.folders.add(name)
                elif member.isfile() and (content := archive.extractfile(member)) is not None:
                    box.files[name] = content.read()

    async def delete_workspace(self, sandbox: SandboxId) -> None:
        self.boxes.pop(sandbox, None)

    async def copy_workspace(self, sandbox: SandboxId, source: SandboxId, folder: Path) -> None:
        original = self._box(source)
        copy = self._box(sandbox)
        copy.files, copy.folders = dict(original.files), set(original.folders)

    # --- The workspace's files ---

    async def workspace_size(self, sandbox: SandboxId) -> dict[str, int]:
        used = sum(len(content) for content in self._box(sandbox).files.values())
        return {"bytes": used, "quota_bytes": QUOTA_BYTES}

    def _entry(self, box: _Box, path: str) -> dict[str, Any]:
        is_folder = path in box.folders
        return {
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "type": "folder" if is_folder else "file",
            "size": 0 if is_folder else len(box.files[path]),
            "modified": _now(),
        }

    def _exists(self, box: _Box, path: str) -> bool:
        return path in box.files or path in box.folders

    def _make_folders(self, box: _Box, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            if prefix in box.files:
                raise FileOperationError(422, "through a link or a file")
            box.folders.add(prefix)

    async def list_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        box, folder = self._box(sandbox), relative(path)
        if folder and folder in box.files:
            raise FileOperationError(422, "not a folder")
        if folder and folder not in box.folders:
            raise FileOperationError(404, "not found")
        children = [
            child for child in (*box.folders, *box.files) if child != folder and child.rpartition("/")[0] == folder
        ]
        entries = [self._entry(box, child) for child in children]
        entries.sort(key=lambda entry: (entry["type"] != "folder", entry["name"].lower()))
        return {"entries": entries}

    async def delete_entry(self, sandbox: SandboxId, path: str) -> None:
        box, target = self._box(sandbox), relative(path)
        if not target:
            raise FileOperationError(422, "the workspace itself")
        if not self._exists(box, target):
            raise FileOperationError(404, "not found")
        for name in [name for name in (*box.files, *box.folders) if name == target or name.startswith(f"{target}/")]:
            box.files.pop(name, None)
            box.folders.discard(name)

    async def create_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        box, target = self._box(sandbox), relative(path)
        if self._exists(box, target):
            raise FileOperationError(409, "exists")
        self._make_folders(box, target)
        return self._entry(box, target)

    async def move_entry(self, sandbox: SandboxId, source: str, target: str) -> dict[str, Any]:
        box, origin, destination = self._box(sandbox), relative(source), relative(target)
        if not origin:
            raise FileOperationError(422, "the workspace itself")
        if not self._exists(box, origin):
            raise FileOperationError(404, "not found")
        if self._exists(box, destination):
            raise FileOperationError(409, "exists")
        self._make_folders(box, destination.rsplit("/", 1)[0] if "/" in destination else "")
        for name in [name for name in (*box.files, *box.folders) if name == origin or name.startswith(f"{origin}/")]:
            moved = destination + name.removeprefix(origin)
            if name in box.files:
                box.files[moved] = box.files.pop(name)
            else:
                box.folders.discard(name)
                box.folders.add(moved)
        return self._entry(box, destination)

    async def read_file(self, sandbox: SandboxId, path: str) -> tuple[dict[str, Any], AsyncIterator[bytes]]:
        box, target = self._box(sandbox), relative(path)
        if target in box.folders:
            raise FileOperationError(422, "not a regular file")
        if target not in box.files:
            raise FileOperationError(404, "not found")
        content = box.files[target]

        async def stream() -> AsyncIterator[bytes]:
            yield content

        return self._entry(box, target), stream()

    async def write_file(
        self, sandbox: SandboxId, path: str, length: int, body: AsyncIterator[bytes]
    ) -> dict[str, Any]:
        box, target = self._box(sandbox), relative(path)
        if not target:
            raise FileOperationError(422, "the workspace itself")
        if sum(len(content) for content in box.files.values()) + length > QUOTA_BYTES:
            raise FileOperationError(413, "workspace.quota_exceeded")
        if self._exists(box, target):
            raise FileOperationError(409, "exists")
        received = b""
        async for chunk in body:
            received += chunk
            if len(received) > length:
                raise FileOperationError(422, "more than Content-Length")
        if len(received) != length:
            raise FileOperationError(422, "less than Content-Length")
        self._make_folders(box, target.rsplit("/", 1)[0] if "/" in target else "")
        box.files[target] = received
        return self._entry(box, target)

    async def zip_folder(self, sandbox: SandboxId, path: str, destination: Path) -> None:
        box, folder = self._box(sandbox), relative(path)
        if folder and folder not in box.folders:
            raise FileOperationError(404, "not found")
        prefix = f"{folder}/" if folder else ""
        with zipfile.ZipFile(destination, "w") as archive:
            for name, content in sorted(box.files.items()):
                if name.startswith(prefix):
                    archive.writestr(name.removeprefix(prefix), content)


async def _shell(box: _Box, script: str, seconds: int | None) -> tuple[int, str, str, bool]:
    """Run `script` in the fake shell: the exit status, stdout, stderr, and whether it timed out."""
    out: list[str] = []
    err: list[str] = []
    code = 0
    for part in _split(script):
        if part == "&&" and code != 0:
            break
        if part in ("&&", ";"):
            continue
        try:
            words = shlex.split(part)
        except ValueError:
            err.append("sh: syntax error\n")
            return 2, "".join(out), "".join(err), False
        if not words:
            continue
        target = None
        for operator in (">>", ">"):
            if operator in words:
                at = words.index(operator)
                words, target = words[:at], (operator, words[at + 1] if at + 1 < len(words) else "")
                break
        text, problem, code = await _command(box, words, seconds)
        if problem == "timeout":
            return 124, "".join(out), "".join(err), True
        if code and problem:
            err.append(problem)
        if target is not None:
            operator, name = target
            path = relative(name.removeprefix(f"{WORKSPACE}/")) if name.startswith(f"{WORKSPACE}/") else None
            if path is None:
                (box.scratch)[name] = (box.scratch.get(name, b"") if operator == ">>" else b"") + text.encode()
            else:
                box.files[path] = (box.files.get(path, b"") if operator == ">>" else b"") + text.encode()
        else:
            out.append(text)
    return code, "".join(out), "".join(err), False


def _split(script: str) -> list[str]:
    parts: list[str] = []
    current = ""
    index = 0
    quote = ""
    while index < len(script):
        char = script[index]
        if quote:
            quote = "" if char == quote else quote
            current += char
        elif char in "'\"":
            quote = char
            current += char
        elif script.startswith("&&", index):
            parts += [current, "&&"]
            current, index = "", index + 1
        elif char in ";\n":
            parts += [current, ";"]
            current = ""
        else:
            current += char
        index += 1
    parts.append(current)
    return [part.strip() if part not in ("&&", ";") else part for part in parts]


async def _command(box: _Box, words: list[str], seconds: int | None) -> tuple[str, str, int]:
    name, args = words[0], words[1:]
    if name == "echo":
        if args[:1] == ["-n"]:
            return " ".join(args[1:]), "", 0
        return " ".join(args) + "\n", "", 0
    if name == "printf" and args:
        return (
            args[0].replace("\\n", "\n").replace("\\t", "\t") % tuple(args[1:])
            if "%" in args[0]
            else (args[0].replace("\\n", "\n").replace("\\t", "\t")),
            "",
            0,
        )
    if name == "cd":
        return "", "", 0
    if name == "true":
        return "", "", 0
    if name == "false":
        return "", "", 1
    if name == "exit":
        return "", "", int(args[0]) if args else 0
    if name == "pwd":
        return f"{SCRATCH}\n", "", 0
    if name == "sleep" and args:
        amount = float(args[0])
        if seconds is not None and amount > seconds:
            await asyncio.sleep(seconds)
            return "", "timeout", 124
        await asyncio.sleep(amount)
        return "", "", 0
    if name == "cat" and args:
        pieces: list[str] = []
        for argument in args:
            path = argument.removeprefix(f"{WORKSPACE}/") if argument.startswith(f"{WORKSPACE}/") else None
            content = box.files.get(path) if path is not None else box.scratch.get(argument)
            if content is None:
                return "".join(pieces), f"cat: {argument}: No such file or directory\n", 1
            pieces.append(content.decode(errors="replace"))
        return "".join(pieces), "", 0
    if name == "mkdir" and args:
        for argument in [a for a in args if a != "-p"]:
            if argument.startswith(f"{WORKSPACE}/"):
                parts = [part for part in argument.removeprefix(f"{WORKSPACE}/").split("/") if part]
                for index in range(1, len(parts) + 1):
                    box.folders.add("/".join(parts[:index]))
        return "", "", 0
    if name == "touch" and args:
        for argument in args:
            if argument.startswith(f"{WORKSPACE}/"):
                box.files.setdefault(argument.removeprefix(f"{WORKSPACE}/"), b"")
        return "", "", 0
    if name == "ls":
        names = sorted({child.split("/")[0] for child in (*box.files, *box.folders)})
        return "".join(f"{entry}\n" for entry in names), "", 0
    return "", f"sh: {name}: not found\n", 127


def _verified() -> IsolationState:
    """The state of an isolation whose every check passed, as the real driver reports it once they do."""
    state = IsolationState(runtime_version="fake")
    for name in ("platform", "isolation_runtime", "release", "egress_table", "canary", "disks"):
        setattr(state, name, Check(ok=True, detail="fake"))
    return state


class _Isolation:
    def __init__(self) -> None:
        self.state = _verified()


@dataclass(frozen=True)
class FakeDriver:
    """The fake sandbox driver, serving on a free port: its URL, its token and its sandboxes."""

    url: str
    token: str
    sandboxes: FakeSandboxes
    _server: uvicorn.Server = field(repr=False)
    _thread: threading.Thread = field(repr=False)

    def client(self, token: str | None = None) -> httpx.Client:
        """An HTTP client of the driver, authenticated unless `token` says otherwise."""
        headers = {"Authorization": f"Bearer {token or self.token}"}
        return httpx.Client(base_url=self.url, headers=headers, timeout=30, verify=False)  # noqa: S501 - loopback

    def close(self) -> None:
        self._server.should_exit = True
        self._thread.join(10)


def start_fake_driver() -> FakeDriver:
    """Serve the fake driver in a thread of this process, until `close`."""
    port, token = free_port(), secrets.token_urlsafe(32)
    configuration = load_configuration(
        {
            "SIBILLO_SANDBOXD_HOST": "127.0.0.1",
            "SIBILLO_SANDBOXD_PORT": str(port),
            "SIBILLO_SANDBOXD_TOKEN": token,
            "SIBILLO_SANDBOX_IMAGE": "fake",
            "SIBILLO_NETGUARD_SOCKET": "/nonexistent",
        }
    )
    sandboxes = FakeSandboxes()
    app = create_app(configuration)

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncGenerator[None]:
        app.state.sandboxes, app.state.isolation = sandboxes, _Isolation()
        yield

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="fake-sandbox-driver", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    return FakeDriver(f"http://127.0.0.1:{port}/v1", token, sandboxes, server, thread)
