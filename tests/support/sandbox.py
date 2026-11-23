"""Sandboxes under test, set up as the test harness contract prescribes ("Sandboxes", ADR-0053, ADR-0114).

The images are built from `deploy/images/`. The sandbox engine runs as a
privileged container with a Docker of its own and gVisor in it, the network
guard as a container in the engine's network namespace with `NET_ADMIN`,
and the sandbox driver as a process that reaches the engine's Docker over
its Unix socket. The host needs Docker and nothing else, and nothing of the
session is left in it at the end.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from tests.support.database import ROOT, uuid7
from tests.support.server import Process

READY_TIMEOUT_SECONDS = 120
BUILD_TIMEOUT_SECONDS = 900
# The prefix of the interface names of the sandbox bridges (SBX-024, ADR-0113).
BRIDGE_PREFIX = "sbx"
# The range the sandbox bridges take their subnets from, by default.
SANDBOX_SUBNETS = "10.213.0.0/16"
EGRESS_TABLE = "inet sibillo"
# The sandbox image as the engine names it (ADR-0114).
ENGINE_SANDBOX_IMAGE = "sibillo/sandbox:engine"
ENGINE_READY_TIMEOUT_SECONDS = 180
# Small limits, so that tests can reach them (SBX-011).
TEST_LIMITS = {
    "SIBILLO_SANDBOX_CPUS": "0.5",
    "SIBILLO_SANDBOX_MEMORY_MB": "256",
    "SIBILLO_SANDBOX_PROCESSES": "64",
    "SIBILLO_SANDBOX_COMMAND_TIMEOUT_SECONDS": "8",
    "SIBILLO_SANDBOX_MAX_OUTPUT_BYTES": "65536",
    "SIBILLO_SANDBOX_IDLE_MINUTES": "30",
    "SIBILLO_SANDBOX_WORKSPACE_QUOTA_MB": "8",
    "SIBILLO_SANDBOX_DISK_MB": "64",
}
# The label the driver gives its sandboxes, with the tenant, the user and the conversation.
SANDBOX_LABEL = "dev.sibillo.sandbox"
# The workspace quota above, in bytes (SBX-019).
WORKSPACE_QUOTA_BYTES = 8 * 1024 * 1024
# The disk of each workspace: the quota plus 10% and 32 MiB (SBX-016, ADR-0098).
WORKSPACE_DISK_BYTES = WORKSPACE_QUOTA_BYTES * 11 // 10 + 32 * 1024 * 1024
# The disk a sandbox may use outside its workspace (SBX-016, ADR-0098).
SANDBOX_DISK_BYTES = 64 * 1024 * 1024


# The Docker socket of the session's sandbox engine, once it runs.
_engine_socket: list[str] = []


def _docker(prefix: list[str], args: tuple[str, ...], timeout: float, check: bool) -> str:
    result = subprocess.run(  # noqa: S603 - the Docker CLI, with arguments from the tests
        ["docker", *prefix, *args],  # noqa: S607 - Docker from the PATH, as an operator runs it
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def host_docker(*args: str, timeout: float = 120, check: bool = True) -> str:
    """The host's Docker: the engine and the network guard are its containers, sandboxes are not."""
    return _docker([], args, timeout, check)


def docker(*args: str, timeout: float = 120, check: bool = True) -> str:
    """The Docker of the session's sandbox engine, where sandboxes and their volumes are (SBX-025)."""
    if not _engine_socket:
        raise RuntimeError("the session's sandbox engine is not running")
    return _docker(["--host", f"unix://{_engine_socket[0]}"], args, timeout, check)


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    # The workspace's size and quota after the command (SBX-019).
    workspace_bytes: int | None = None
    workspace_quota_bytes: int | None = None


@dataclass(frozen=True)
class Driver:
    """The sandbox driver of the test session, and what the session built for it."""

    url: str
    token: str
    # The sandbox image as the engine names it.
    image: str
    # The network guard's container, of the host's Docker.
    netguard: str
    process: Process
    # The sandbox engine's container, of the host's Docker.
    engine: str = ""
    # The engine's Docker socket and the network guard's socket, on the host.
    docker_socket: str = ""
    guard_socket: str = ""

    def environment(self, port: int, **overrides: str) -> dict[str, str]:
        """The environment of another driver on the session's engine and network guard."""
        return driver_environment(self.token, self.docker_socket, self.guard_socket, port, **overrides)

    def client(self, token: str | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token or self.token}"}, timeout=120)

    def exec(self, tenant_id: str, user_id: str, conversation_id: str, request: Mapping[str, Any]) -> ExecResult:
        """Run a command in a conversation's sandbox and collect its streamed output."""
        stdout: list[str] = []
        stderr: list[str] = []
        exit_object: dict[str, Any] | None = None
        with (
            self.client() as client,
            client.stream(
                "POST", f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/exec", json=dict(request)
            ) as response,
        ):
            assert response.status_code == 200, response.read().decode()
            for line in response.iter_lines():
                if not line:
                    continue
                item = cast(dict[str, Any], json.loads(line))
                if item["kind"] == "output":
                    (stdout if item["stream"] == "stdout" else stderr).append(item["data"])
                else:
                    assert exit_object is None, "more than one exit object"
                    exit_object = item
        assert exit_object is not None, "the stream ended without an exit object"
        return ExecResult(
            exit_object["exit_code"],
            "".join(stdout),
            "".join(stderr),
            exit_object["timed_out"],
            exit_object["truncated"],
            exit_object.get("workspace_bytes"),
            exit_object.get("workspace_quota_bytes"),
        )

    def sh(self, tenant_id: str, user_id: str, conversation_id: str, command: str, **options: Any) -> ExecResult:
        return self.exec(tenant_id, user_id, conversation_id, {"shell_command": command} | options)

    def ensure(
        self, tenant_id: str, user_id: str, conversation_id: str, *, internet_access: bool = False
    ) -> dict[str, Any]:
        """Start a conversation's sandbox, or find it running, saying whether it has internet access (SBX-024)."""
        with self.client() as client:
            response = client.post(
                f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure", json={"internet_access": internet_access}
            )
        assert response.status_code == 200, response.text
        return cast(dict[str, Any], response.json())

    def withdraw_network(self, tenant_id: str, user_id: str, conversation_id: str) -> None:
        """Take the network from a conversation's sandbox, if it runs (SBX-024)."""
        with self.client() as client:
            response = client.delete(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/network")
        assert response.status_code == 204, response.text

    def stop(self, tenant_id: str, user_id: str, conversation_id: str) -> None:
        with self.client() as client:
            assert client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/stop").status_code == 204

    def running(self, conversation_id: str) -> list[dict[str, Any]]:
        """The running containers of a conversation's sandbox."""
        return [
            container
            for container in self.sandbox_containers()
            if container["State"]["Running"]
            and container["Config"]["Labels"].get(f"{SANDBOX_LABEL}.conversation") == conversation_id
        ]

    def sandbox_containers(self) -> list[dict[str, Any]]:
        """`docker inspect` of every container of the session's sandbox image."""
        ids = docker("ps", "-aq", "--filter", f"ancestor={self.image}").split()
        if not ids:
            return []
        # The driver removes sandboxes as they stop (SBX-018): one listed may be gone by now.
        return cast(list[dict[str, Any]], json.loads(docker("inspect", *ids, check=False) or "[]"))

    def wait_until_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            if self.process.exited() is not None:
                raise RuntimeError(f"the sandbox driver exited:\n{self.process.output()}")
            try:
                with self.client() as client:
                    response = client.get("/health")
                last = response.text
                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())
            except httpx.TransportError as error:
                last = repr(error)
            time.sleep(0.5)
        raise RuntimeError(f"the sandbox driver was not ready: {last}\n{self.process.output()}")


def online_sandbox(driver: Driver) -> tuple[str, str, str]:
    """A tenant, a user and a conversation with internet access, whose sandbox runs with network (SBX-004)."""
    sandbox = str(uuid7()), str(uuid7()), str(uuid7())
    driver.ensure(*sandbox, internet_access=True)
    return sandbox


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _build(name: str, tag: str, *options: str) -> None:
    # From the repository root, so that an image may include project code.
    dockerfile = ROOT / "deploy" / "images" / name / "Dockerfile"
    host_docker(
        "build", "--quiet", "--tag", tag, "--file", str(dockerfile), *options, str(ROOT), timeout=BUILD_TIMEOUT_SECONDS
    )


def build_engine(tag: str, sandbox_image: str) -> None:
    """The engine's image holds the sandbox image, given as a named build context (ADR-0114).

    Built by Docker's own builder, which sees the images of its Docker: the sandbox image is one of
    them, whether the suite or CI built it, and a builder in a container would look for it in a registry.
    """
    _build("engine", tag, "--builder", "default", "--build-context", f"sandbox-image=docker-image://{sandbox_image}")


def wait_healthy(container: str, what: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    status = ""
    while time.monotonic() < deadline:
        status = host_docker("inspect", "--format", "{{.State.Health.Status}}", container, check=False).strip()
        if status == "healthy":
            return
        time.sleep(0.5)
    logs = host_docker("logs", "--tail", "80", container, check=False)
    raise RuntimeError(f"{what} is {status or 'missing'}:\n{logs}")


def start_engine(name: str, image: str, sockets: Path, *, network: str | None = None) -> str:
    """Start a sandbox engine: privileged, on a network of its own, its Docker on a socket in `sockets`.

    Returns the path of its Docker socket, opened to the user who runs the tests.
    """
    network = network or name
    host_docker("network", "create", network)
    host_docker(
        "run", "--detach", "--name", name, "--privileged", "--network", network,
        "--volume", f"{name}:/var/lib/docker", "--volume", f"{sockets}:/run/sibillo-engine", image,
    )  # fmt: skip
    wait_healthy(name, "the sandbox engine", ENGINE_READY_TIMEOUT_SECONDS)
    # The engine's Docker is root's; the driver under test runs as the user of the tests.
    host_docker("exec", name, "chmod", "0666", "/run/sibillo-engine/docker.sock")
    return str(sockets / "docker.sock")


def start_guard(name: str, image: str, engine: str, sockets: Path, *options: str) -> str:
    """Start a network guard in the engine's network namespace; returns the path of its socket."""
    host_docker(
        "run", "--detach", "--name", name, "--network", f"container:{engine}", "--cap-add", "NET_ADMIN",
        "--volume", f"{sockets}:/run/sibillo-netguard-socket",
        "--env", "SIBILLO_NETGUARD_SOCKET=/run/sibillo-netguard-socket/guard.sock", *options, image,
    )  # fmt: skip
    wait_healthy(name, "the network guard")
    host_docker("exec", name, "chmod", "0666", "/run/sibillo-netguard-socket/guard.sock")
    return str(sockets / "guard.sock")


def restart_engine(driver: Driver) -> None:
    """Restart the session's engine, as a crash or an update of the host's Docker would."""
    host_docker("restart", "--time", "20", driver.engine)
    wait_healthy(driver.engine, "the sandbox engine", ENGINE_READY_TIMEOUT_SECONDS)
    host_docker("exec", driver.engine, "chmod", "0666", "/run/sibillo-engine/docker.sock")


def restart_guard(driver: Driver) -> None:
    """Start the session's network guard again: it joins the network namespace the engine has now."""
    host_docker("start", driver.netguard)
    wait_healthy(driver.netguard, "the network guard")
    host_docker("exec", driver.netguard, "chmod", "0666", "/run/sibillo-netguard-socket/guard.sock")


def remove_engine(name: str, guard: str | None, sockets: Path, *, network: str | None = None) -> None:
    """Remove an engine with everything in it, its network guard, and their sockets."""
    if guard is not None:
        host_docker("stop", "--time", "15", guard, check=False)
        host_docker("rm", "-f", guard, check=False)
    host_docker("stop", "--time", "30", name, check=False)
    host_docker("rm", "-f", "--volumes", name, check=False)
    host_docker("volume", "rm", "-f", name, check=False)
    host_docker("network", "rm", network or name, check=False)
    shutil.rmtree(sockets, ignore_errors=True)


def socket_directory() -> Path:
    """A directory for the sockets: short, since a Unix socket's path is at most 107 characters."""
    directory = Path(tempfile.mkdtemp(prefix="sbx-", dir="/tmp"))
    directory.chmod(0o755)
    return directory


def start_driver_process(environment: Mapping[str, str]) -> Process:
    base = {name: value for name, value in os.environ.items() if not name.startswith("SIBILLO_")}
    return Process("sandboxd", base | dict(environment), module="sibillo_sandboxd", command=None)


def driver_environment(
    token: str, docker_socket: str, guard_socket: str, port: int, **overrides: str
) -> dict[str, str]:
    return {
        "DOCKER_HOST": f"unix://{docker_socket}",
        "SIBILLO_SANDBOXD_HOST": "127.0.0.1",
        "SIBILLO_SANDBOXD_PORT": str(port),
        "SIBILLO_SANDBOXD_TOKEN": token,
        "SIBILLO_SANDBOX_IMAGE": ENGINE_SANDBOX_IMAGE,
        "SIBILLO_NETGUARD_SOCKET": guard_socket,
        **TEST_LIMITS,
        **overrides,
    }


def _cleanup(removed: tuple[str, ...], engine: str, netguard: str, sockets: Path, driver: Process | None) -> None:
    """Remove what the session created: the driver, the network guard, the engine with everything in it."""
    if driver is not None:
        # SIGTERM: the driver detaches the loop devices of its workspaces' disks (ADR-0098).
        driver.close()
    _engine_socket.clear()
    remove_engine(engine, netguard, sockets)
    if removed:
        host_docker("rmi", "-f", *removed, check=False)


_DRIVER = pytest.StashKey[Driver | BaseException]()
_STARTING = pytest.StashKey[threading.Thread]()


def begin_sandboxes(config: pytest.Config) -> None:
    """Start the engine, the network guard and the sandbox driver in the background, once per session.

    They take about half a minute to be ready, which the session would otherwise wait for before its
    first test that needs them; meanwhile it runs other tests or builds the web app (ADR-0059).
    """
    if _STARTING in config.stash or _DRIVER in config.stash:
        return
    starting = threading.Thread(target=_start_sandboxes, args=(config,), name="sibillo-test-sandboxes", daemon=True)
    config.stash[_STARTING] = starting
    starting.start()


def start_sandboxes(config: pytest.Config) -> Driver:
    """The session's engine, network guard and sandbox driver, started now unless they already are."""
    begin_sandboxes(config)
    config.stash[_STARTING].join()
    started = config.stash[_DRIVER]
    if isinstance(started, BaseException):
        raise started
    return started


def pytest_collection_finish(session: pytest.Session) -> None:
    """Begin starting the sandboxes once the session knows it will run a test that needs them."""
    if any("sandboxes" in getattr(item, "fixturenames", ()) for item in session.items):
        begin_sandboxes(session.config)


def _start_sandboxes(config: pytest.Config) -> None:
    """Build the images, start the engine, the network guard and the sandbox driver, and stash the outcome."""
    suffix = secrets.token_hex(4)
    # Images CI built with its build cache are used as they are, and kept (ADR-0059).
    names = ("TEST_SANDBOX_IMAGE", "TEST_ENGINE_IMAGE", "TEST_NETGUARD_IMAGE")
    prebuilt = tuple(os.environ.get(name) for name in names)
    sandbox_image = prebuilt[0] or f"sibillo-test/sandbox:{suffix}"
    engine_image = prebuilt[1] or f"sibillo-test/engine:{suffix}"
    guard_image = prebuilt[2] or f"sibillo-test/netguard:{suffix}"
    engine, netguard = f"sibillo-test-engine-{suffix}", f"sibillo-test-netguard-{suffix}"
    sockets = socket_directory()
    holder: dict[str, Process] = {}
    built = (sandbox_image, engine_image, guard_image)
    removed = tuple(name for name, given in zip(built, prebuilt, strict=True) if not given)
    starting = config.stash[_STARTING]

    def cleanup() -> None:
        # A session that ends while the sandboxes start, interrupted, waits for them to remove them.
        starting.join()
        _cleanup(removed, engine, netguard, sockets, holder.get("driver"))

    config.add_cleanup(cleanup)
    try:
        if not prebuilt[0]:
            _build("sandbox", sandbox_image)
        if not prebuilt[1]:
            build_engine(engine_image, sandbox_image)
        if not prebuilt[2]:
            _build("netguard", guard_image)
        docker_socket = start_engine(engine, engine_image, sockets)
        _engine_socket.append(docker_socket)
        guard_socket = start_guard(netguard, guard_image, engine, sockets)
        token, port = secrets.token_urlsafe(32), _free_port()
        holder["driver"] = start_driver_process(driver_environment(token, docker_socket, guard_socket, port))
        driver = Driver(
            f"http://127.0.0.1:{port}/v1", token, ENGINE_SANDBOX_IMAGE, netguard, holder["driver"],
            engine=engine, docker_socket=docker_socket, guard_socket=guard_socket,
        )  # fmt: skip
        driver.wait_until_ready()
    except BaseException as exc:  # handed to the first test that needs the sandboxes
        config.stash[_DRIVER] = exc
        return
    config.stash[_DRIVER] = driver


def free_port() -> int:
    return _free_port()
