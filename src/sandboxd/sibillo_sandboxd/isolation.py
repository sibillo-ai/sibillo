"""Whether sandboxes may run: the runtime, its release, the egress table and the canary.

The driver fails closed (SBX-003): it accepts requests only after the
canary passed, follows the network guard's health every two seconds, and
stops every sandbox when the guard is not healthy (SBX-015, ADR-0053). The
runtime is the sandbox engine's, and the guard is asked over the Unix
socket the two share (SBX-025, ADR-0113, ADR-0114).
"""

# aiodocker leaves some parameters untyped; only those checks are relaxed here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from sibillo_sandboxd.config import DriverConfiguration, release_key
from sibillo_sandboxd.disks import DiskError
from sibillo_sandboxd.guard import GuardUnavailableError, ask_guard
from sibillo_sandboxd.policy import LABEL, MIB, network_name
from sibillo_sandboxd.sandboxes import Sandboxes

logger = logging.getLogger("sibillo.sandboxd")

SUPPORTED_ARCHITECTURES = frozenset({"x86_64", "aarch64"})
MONITOR_INTERVAL_SECONDS = 2.0
_RELEASE = re.compile(r"release-(\d{8})\.(\d+)")
# The canary connects to an address of the host on the sandbox bridge and to
# a private address: a dropped SYN times out, a reachable host refuses or accepts.
_PROBE = (
    "import socket, sys\n"
    "s = socket.socket(); s.settimeout(3)\n"
    "try:\n"
    "    s.connect((sys.argv[1], int(sys.argv[2])))\n"
    "except TimeoutError:\n"
    "    print('blocked')\n"
    "except OSError as error:\n"
    "    print(f'reachable: {error}')\n"
    "else:\n"
    "    print('reachable: connected')\n"
)


@dataclass
class Check:
    ok: bool = False
    detail: str = "not checked yet"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail}


@dataclass
class IsolationState:
    runtime_version: str | None = None
    platform: Check = field(default_factory=Check)
    isolation_runtime: Check = field(default_factory=Check)
    release: Check = field(default_factory=Check)
    egress_table: Check = field(default_factory=Check)
    canary: Check = field(default_factory=Check)
    # Workspaces' disks can be attached (SBX-016, ADR-0098).
    disks: Check = field(default_factory=Check)

    @property
    def ready(self) -> bool:
        checks = (self.platform, self.isolation_runtime, self.release, self.egress_table, self.canary, self.disks)
        return all(check.ok for check in checks)

    def refusal_code(self) -> str:
        if self.isolation_runtime.ok and not self.release.ok and self.runtime_version is not None:
            return "driver.runtime_too_old"
        if self.isolation_runtime.ok and self.release.ok and not self.egress_table.ok:
            return "driver.egress_rules_missing"
        return "driver.isolation_unavailable"

    def health(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "runtime_version": self.runtime_version or "",
            "checks": {
                "platform": self.platform.as_dict(),
                "isolation_runtime": self.isolation_runtime.as_dict(),
                "runtime_version": self.release.as_dict(),
                "egress_table": self.egress_table.as_dict(),
                "canary": self.canary.as_dict(),
                "disks": self.disks.as_dict(),
            },
        }


def _visible_binary(path: str) -> str | None:
    """The runtime binary, when this process can run it."""
    return path if os.path.isabs(path) and os.path.exists(path) else shutil.which(path)


def _release_key(version: str) -> tuple[int, int] | None:
    found = _RELEASE.search(version)
    return None if found is None else (int(found.group(1)), int(found.group(2)))


class Isolation:
    def __init__(self, docker: aiodocker.Docker, configuration: DriverConfiguration, sandboxes: Sandboxes) -> None:
        self.docker = docker
        self.configuration = configuration
        self.sandboxes = sandboxes
        self.state = IsolationState()
        sandboxes.egress_in_place = self.check_egress

    async def _runtime_path(self) -> str | None:
        info = await self.docker.system.info()
        runtimes: dict[str, Any] = info.get("Runtimes") or {}
        runtime = runtimes.get(self.configuration.runtime)
        if runtime is None:
            return None
        return str(runtime.get("path") or self.configuration.runtime)

    async def _runtime_release(self, path: str) -> str:
        """The release of the runtime binary: run directly when visible, else in a probe container."""
        local = await asyncio.to_thread(_visible_binary, path)
        if local is not None:
            result = await asyncio.to_thread(
                subprocess.run,
                [local, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return f"{result.stdout}{result.stderr}"
        # The driver runs in a container without the binary: read it, read-only,
        # from a short-lived container with no network.
        container = await self.docker.containers.run(
            {
                "Image": self.configuration.image,
                "Cmd": ["/runtime", "--version"],
                "HostConfig": {
                    "Binds": [f"{path}:/runtime:ro"],
                    "NetworkMode": "none",
                    "AutoRemove": False,
                },
                "Labels": {LABEL: "probe"},
            },
            name=f"sibillo-runtime-probe-{secrets.token_hex(4)}",
        )
        try:
            await container.wait(timeout=60)
            return "".join(await container.log(stdout=True, stderr=True))
        finally:
            await container.delete(force=True)

    async def check_platform(self) -> None:
        """Linux on x86_64 or arm64, with cgroup v2; no hardware virtualization needed (OPS-002, OPS-009)."""
        info = await self.docker.system.info()
        system, architecture = str(info.get("OSType", "")), str(info.get("Architecture", ""))
        cgroups = str(info.get("CgroupVersion", ""))
        if system != "linux" or architecture not in SUPPORTED_ARCHITECTURES:
            self.state.platform = Check(
                False, f"{system or 'unknown'} {architecture or 'unknown'} is not supported: Linux on x86_64 or arm64"
            )
        elif cgroups != "2":
            self.state.platform = Check(
                False, f"cgroup v{cgroups or '?'} is not supported: the host must use cgroup v2 (ADR-0114)"
            )
        else:
            self.state.platform = Check(True, f"{system} {architecture}, cgroup v2")

    async def check_runtime(self) -> None:
        path = await self._runtime_path()
        if path is None:
            self.state.isolation_runtime = Check(False, f"Docker has no runtime named {self.configuration.runtime!r}")
            self.state.release = Check(False, "no runtime")
            return
        try:
            version = await self._runtime_release(path)
        except (OSError, subprocess.SubprocessError, DockerError) as error:
            self.state.isolation_runtime = Check(False, f"cannot read the runtime's release: {error}")
            self.state.release = Check(False, "unknown release")
            return
        key = _release_key(version)
        if key is None:
            self.state.isolation_runtime = Check(False, f"{self.configuration.runtime!r} is not gVisor")
            self.state.release = Check(False, "not a gVisor release")
            return
        self.state.runtime_version = f"release-{key[0]}.{key[1]}"
        self.state.isolation_runtime = Check(True, f"{self.configuration.runtime} ({path})")
        minimum_release = self.configuration.minimum_release
        minimum = release_key(minimum_release)
        if minimum is not None and key < minimum:
            self.state.release = Check(
                False,
                f"{self.state.runtime_version} is older than {minimum_release}: gVisor comes with the sandbox "
                "engine's image, so update Sibillo, or lower the configured minimum",
            )
        else:
            self.state.release = Check(True, f"{self.state.runtime_version} >= {minimum_release}")

    async def check_egress(self) -> bool:
        """The guard answers, its table is in place, and its set of bridges with network is the driver's; given
        again when it is not, as after the guard reinstalled its table, which starts with none (ADR-0113)."""
        try:
            answer = await ask_guard(self.configuration.netguard_socket, {"op": "status"})
            if answer.get("healthy") is True and answer.get("online") != sorted(self.sandboxes.online):
                await self.sandboxes.publish_online()
        except GuardUnavailableError as error:
            self.state.egress_table = Check(False, str(error))
            return False
        if answer.get("healthy") is True:
            self.state.egress_table = Check(
                True, "the network guard reports the table in place, with the bridges that have network"
            )
            return True
        self.state.egress_table = Check(False, "the network guard reports the table missing")
        return False

    async def _blocked(self, container: Any, targets: list[tuple[str, int]]) -> str | None:
        """The first target the canary reaches, as `host: what happened`; None when every one is blocked."""
        probes = await asyncio.gather(
            *(self._output(container, ["python3", "-c", _PROBE, host, str(port)]) for host, port in targets)
        )
        for (host, port), probe in zip(targets, probes, strict=True):
            if "blocked" not in probe:
                return f"{host}:{port}: {probe.strip()}"
        return None

    async def run_canary(self) -> None:
        """A sandbox like any other must run under gVisor, reach nothing without network, and nothing local with it
        (SBX-003, SBX-024)."""
        prerequisites = (self.state.platform, self.state.isolation_runtime, self.state.release, self.state.egress_table)
        if not all(check.ok for check in prerequisites):
            self.state.canary = Check(False, "waiting for the runtime and the egress table")
            return
        name = f"sibillo-canary-{secrets.token_hex(4)}"
        try:
            container = await self.sandboxes.start_container(name, None, {f"{LABEL}.canary": "true"})
            try:
                network = await (await self.docker.networks.get(network_name(name))).show()
                gateway = network["IPAM"]["Config"][0]["Gateway"]
                kernel = await self._output(container, ["sh", "-c", "dmesg 2>/dev/null | head -n 1"])
                if "gVisor" not in kernel:
                    self.state.canary = Check(False, "the canary does not run under gVisor")
                    return
                # Without network: not even the resolver (SBX-024).
                # Nothing listens on the gateway's port: refused without the table, timed out with it (ADR-0120).
                local = [(gateway, 9), ("10.0.0.1", 80)]
                reached = await self._blocked(container, [*local, (self.configuration.resolver, 53)])
                if reached is not None:
                    self.state.canary = Check(False, f"the canary reaches without network {reached}")
                    return
                # With network: still nothing local (SBX-005).
                await self.sandboxes.set_online(name, True)
                reached = await self._blocked(container, local)
                if reached is not None:
                    self.state.canary = Check(False, f"the canary reaches {reached}")
                    return
                # The disk outside the workspace has the configured size (SBX-016, ADR-0098).
                size = await self._output(container, ["sh", "-c", "df -B1 --output=size / | tail -n 1"])
                expected = self.configuration.disk_mb * MIB
                if not size.strip().isdigit() or abs(int(size.strip()) - expected) > MIB:
                    self.state.canary = Check(False, f"the canary's disk is {size.strip()} bytes, not {expected}")
                    return
            finally:
                await self.sandboxes.remove_container(name)
        except (DockerError, KeyError, IndexError, GuardUnavailableError) as error:
            self.state.canary = Check(False, f"the canary failed: {error}")
            return
        self.state.canary = Check(
            True,
            "gVisor, nothing reachable without network, the host and private addresses unreachable with it,"
            " and the disk is limited",
        )

    async def check_disks(self) -> None:
        """The disk helper runs and finds a free loop device (ADR-0098 point 10)."""
        try:
            await self.sandboxes.disks.check()
        except (DockerError, DiskError) as error:
            self.state.disks = Check(
                False, f"workspace disks cannot be attached: {error}; the sandbox engine must see loop devices"
            )
            return
        self.state.disks = Check(True, "the disk helper found a free loop device")

    async def _output(self, container: Any, argv: list[str]) -> str:
        execute = await container.exec(cmd=argv, stdout=True, stderr=True, stdin=False, user="root")
        chunks: list[bytes] = []
        async with execute.start(detach=False) as stream:
            while (message := await stream.read_out()) is not None:
                chunks.append(message.data)
        return b"".join(chunks).decode(errors="replace")

    async def startup(self) -> None:
        # Sandboxes and devices from before this start are not tracked: none is kept (SBX-018, ADR-0078, ADR-0098).
        await self.sandboxes.start()
        await self.check_platform()
        await self.check_runtime()
        await self.check_egress()
        await self.run_canary()
        await self.check_disks()
        logger.info("isolation: %s", json.dumps(self.state.health()))

    async def monitor(self) -> None:
        """Follow the network guard; stop sandboxes when it fails, and re-verify when it recovers."""
        while True:
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
            try:
                if not await self.check_egress():
                    self.state.canary = Check(False, "the egress rules are not verified")
                    # At every check, so that a sandbox a request was still starting is stopped too (ADR-0120).
                    stopped = await self.sandboxes.stop_all()
                    if stopped:
                        logger.warning("egress rules missing: stopped %d sandboxes", stopped)
                elif not self.state.canary.ok:
                    await self.run_canary()
                await self.sandboxes.stop_idle()
            except Exception:
                logger.exception("isolation monitor failed")
