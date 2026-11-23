"""Sandboxes on Docker: one per user, commands executed in them (SBX-001, SBX-011, ADR-0022, ADR-0053).

A sandbox that stops is removed; the next command gets a new one from the
image, with only the user's workspace (SBX-018, ADR-0076).

Each sandbox has a bridge of its own, removed with it, and starts without
network: the network guard's set of the bridges with network has only those
whose conversation has internet access, as the control plane says on
`ensure` (SBX-024, ADR-0113). The driver gives the guard the whole set at
every change, and checks that the guard took it before it answers.
"""

# aiodocker leaves some parameters untyped; only those checks are relaxed here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import codecs
import contextlib
import ipaddress
import json
import logging
import shutil
import tarfile
import tempfile
import time
import uuid
import zipfile
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from sibillo_sandboxd.config import DriverConfiguration
from sibillo_sandboxd.disks import DiskError, Disks
from sibillo_sandboxd.files import (
    HELPER,
    FileOperationError,
    file_header,
    padding,
    relative,
    tar_member_content,
)
from sibillo_sandboxd.guard import GuardUnavailableError, give_online
from sibillo_sandboxd.policy import (
    LABEL,
    MIB,
    SCRATCH,
    SKILLS,
    WORKSPACE,
    SandboxId,
    bridge_interface,
    container_config,
    network_config,
    network_name,
)
from sibillo_sandboxd.workspaces import check_archive, check_skills_archive, workspace_entries

logger = logging.getLogger("sibillo.sandboxd")

STOP_GRACE_SECONDS = 2
# Time beyond a command's timeout before the driver stops waiting for it.
TIMEOUT_GRACE_SECONDS = 10
KILLED_EXIT_CODES = frozenset({124, 137})
NOT_FOUND = 404
ARCHIVE_CHUNK_BYTES = 1024 * 1024
# Deleting a workspace waits this long for a file operation that still uses it.
DELETE_ATTEMPTS = 20
DELETE_PAUSE_SECONDS = 0.5


async def _assume_in_place() -> bool:
    return True


class NoSubnetError(Exception):
    """Every subnet of the sandbox bridges' range is taken: no more sandboxes run at once (SBX-024)."""


@dataclass(frozen=True)
class Output:
    stream: str
    data: str


@dataclass(frozen=True)
class Exit:
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int
    # The workspace's size after the command, and its quota (SBX-019).
    workspace_bytes: int
    workspace_quota_bytes: int


class Sandboxes:
    def __init__(self, docker: aiodocker.Docker, configuration: DriverConfiguration) -> None:
        self.docker = docker
        self.configuration = configuration
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}
        # The sandbox of each name in _last_used, whose disk the idle sweep releases (ADR-0098).
        self._known: dict[str, SandboxId] = {}
        self.disks = Disks(docker, configuration)
        # The skills each sandbox's next container gets, as archives of the driver's own (SBX-022).
        self._skills_folder = Path(tempfile.mkdtemp(prefix="sibillo-skills-"))
        self._skills: dict[str, Path] = {}
        # The bridges with network, as the guard was last given them (SBX-024, ADR-0113).
        self._online: set[str] = set()
        self._online_lock = asyncio.Lock()
        self._networks_lock = asyncio.Lock()
        # Asks the guard whether the egress table is in place; the isolation monitor sets it (ADR-0120).
        self.egress_in_place: Callable[[], Awaitable[bool]] = _assume_in_place

    @property
    def online(self) -> frozenset[str]:
        return frozenset(self._online)

    async def publish_online(self) -> None:
        """Give the guard the whole set of bridges with network again, as after it reinstalled its table."""
        async with self._online_lock:
            await give_online(self.configuration.netguard_socket, set(self._online))

    async def set_online(self, container: str, online: bool) -> None:
        """Give a sandbox's bridge network, or take it, at once (SBX-024); raises if the guard does not take it."""
        bridge = bridge_interface(container)
        async with self._online_lock:
            if (bridge in self._online) == online:
                return
            wanted = self._online | {bridge} if online else self._online - {bridge}
            try:
                await give_online(self.configuration.netguard_socket, wanted)
            except GuardUnavailableError:
                if not online:
                    # Not taken from the set: the sandbox goes instead, so that it has no network (fail closed).
                    self._online.discard(bridge)
                    with contextlib.suppress(DockerError):
                        await self._delete_container(container)
                raise
            self._online = wanted

    async def _create_network(self, container: str, labels: dict[str, str]) -> None:
        """The sandbox's own bridge, with the first free subnet of four addresses of the range (ADR-0113)."""
        async with self._networks_lock:
            await self._delete_network(container)
            used: set[ipaddress.IPv4Network] = set()
            for network in await self.docker.networks.list(filters={"label": [f"{LABEL}=network"]}):
                for config in (network.get("IPAM") or {}).get("Config") or []:
                    with contextlib.suppress(ValueError, KeyError, TypeError):
                        used.add(ipaddress.IPv4Network(config["Subnet"]))
            subnet = next(
                (subnet for subnet in self.configuration.subnets.subnets(new_prefix=30) if subnet not in used), None
            )
            if subnet is None:
                raise NoSubnetError("every subnet of SIBILLO_SANDBOX_SUBNETS is taken")
            await self.docker.networks.create(network_config(container, subnet, labels, self.configuration.image))

    async def _delete_network(self, container: str) -> None:
        await self._delete_network_named(network_name(container))

    async def start_container(
        self, name: str, volume: str | None, labels: dict[str, str], *, skills: str | None = None
    ) -> Any:
        """Create and start a container with the fixed policy, on a bridge of its own and without network, then
        point it at the instance's resolver.

        `volume` is a workspace whose disk is attached (ADR-0098).
        """
        # A new sandbox never has network until the control plane says so (SBX-024).
        await self.set_online(name, False)
        await self._create_network(name, labels)
        config = container_config(self.configuration, volume, labels, skills=skills, network=network_name(name))
        container = await self.docker.containers.create(config, name=name)
        await container.start()
        # The table may have gone while this request was past its own check of readiness: nothing runs in the
        # container until the guard says again that it is in place (SBX-015, ADR-0120).
        if not await self.egress_in_place():
            await self._delete_container(name)
            await self._delete_network(name)
            raise GuardUnavailableError("the egress table went missing while a sandbox started")
        await self._write_resolver(container)
        return container

    async def _write_resolver(self, container: Any) -> None:
        # gVisor cannot use Docker's embedded resolver (ADR-0021).
        line = f"nameserver {self.configuration.resolver}\n"
        await self._run_quietly(container, ["sh", "-c", f"printf '{line}' > /etc/resolv.conf"])

    async def _run_quietly(self, container: Any, argv: Sequence[str]) -> int:
        return (await self._run(container, argv))[0]

    async def _run(self, container: Any, argv: Sequence[str]) -> tuple[int, str]:
        """Run a command of the driver's own in the container: its exit code and standard output."""
        code, output, _ = await self._run_logged(container, argv)
        return code, output

    async def _run_logged(self, container: Any, argv: Sequence[str]) -> tuple[int, str, str]:
        """Run a command of the driver's own in the container: its exit code, standard output and error."""
        execute = await container.exec(cmd=list(argv), stdout=True, stderr=True, stdin=False, user="root")
        streams: dict[int, list[bytes]] = {1: [], 2: []}
        async with execute.start(detach=False) as stream:
            while (message := await stream.read_out()) is not None:
                streams[message.stream].append(message.data)
        code = int((await execute.inspect())["ExitCode"] or 0)
        return code, b"".join(streams[1]).decode(errors="replace"), b"".join(streams[2]).decode(errors="replace")

    async def _workspace_bytes(self, container: Any) -> int:
        """The workspace's size, measured inside the sandbox (SBX-019)."""
        try:
            code, output = await self._run(container, ["du", "-sb", WORKSPACE])
            return int(output.split()[0]) if code == 0 and output else 0
        except (DockerError, ValueError, IndexError):
            logger.warning("the workspace of %s could not be measured", container.id)
            return 0

    async def ensure(self, sandbox: SandboxId, internet_access: bool | None = None) -> dict[str, Any]:
        """The conversation's sandbox, created if needed (idempotent), with network when `internet_access` says
        so; as it is when None (SBX-024)."""
        name = sandbox.container
        async with self._locks.setdefault(name, asyncio.Lock()):
            container, _ = await self._running(sandbox)
            if internet_access is not None:
                await self.set_online(name, internet_access)
            info = await container.show()
        return {
            "state": "running",
            "started_at": info["State"]["StartedAt"],
            "working_dir": SCRATCH,
            "internet_access": bridge_interface(name) in self._online,
        }

    async def withdraw_network(self, sandbox: SandboxId) -> None:
        """Take the network from the conversation's sandbox, at once; nothing when it has none (SBX-024)."""
        name = sandbox.container
        async with self._locks.setdefault(name, asyncio.Lock()):
            await self.set_online(name, False)

    async def _running(self, sandbox: SandboxId) -> tuple[Any, bool]:
        """The sandbox's running container, started if needed, and whether it was started; under its lock."""
        name = sandbox.container
        container: Any = None
        try:
            container = await self.docker.containers.get(name)
            if not (await container.show())["State"]["Running"]:
                # A sandbox that stopped is never started again: a new one is (SBX-018).
                await container.delete(force=True)
                container = None
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise
        started = container is None
        if started:
            await self.disks.attach(sandbox)
            skills = await self._fill_skills(sandbox)
            container = await self.start_container(name, sandbox.volume, sandbox.labels, skills=skills)
        self._used(sandbox)
        return container, started

    def _used(self, sandbox: SandboxId) -> None:
        self._last_used[sandbox.container] = time.monotonic()
        self._known[sandbox.container] = sandbox

    async def stop(self, sandbox: SandboxId) -> None:
        """Remove the sandbox's container; its disk stays attached until the sandbox is idle (ADR-0098)."""
        name = sandbox.container
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            await self._remove(name)

    async def _remove(self, name: str) -> None:
        """Stop a sandbox and remove its container, keeping its workspace (SBX-018); its skills and its bridge go
        with it."""
        await self._delete_container(name, STOP_GRACE_SECONDS)
        try:
            await self.set_online(name, False)
        except GuardUnavailableError:
            logger.warning("the network guard did not take the bridge of %s out of its set", name)
        await self._delete_network(name)
        await self._delete_volume(name.replace("sibillo-sandbox-", "sibillo-skills-", 1))

    async def remove_container(self, name: str) -> None:
        """Remove a container the driver started for itself, such as the canary, at once, with its bridge."""
        await self._delete_container(name)
        await self._remove(name)

    async def _delete_container(self, name: str, grace: int | None = None) -> None:
        try:
            container = await self.docker.containers.get(name)
            if grace is not None:
                with contextlib.suppress(DockerError):
                    await container.stop(t=grace)
            await container.delete(force=True)
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise

    async def _delete_network_named(self, name: str) -> None:
        try:
            await (await self.docker.networks.get(name)).delete()
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise

    async def _delete_volume(self, volume: str) -> None:
        try:
            await (await self.docker.volumes.get(volume)).delete()
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise

    # --- Skills (SBX-022, ADR-0096) ---

    async def set_skills(self, sandbox: SandboxId, source: Path) -> None:
        """Keep the archive at `source` for the sandbox's next container, refusing it whole when unsafe."""
        await asyncio.to_thread(check_skills_archive, source)
        target = self._skills_folder / f"{sandbox.container}.tar"
        await asyncio.to_thread(shutil.move, source, target)
        self._skills[sandbox.container] = target

    async def _fill_skills(self, sandbox: SandboxId) -> str:
        """A new volume of skills for the sandbox's new container: what was set for it, else nothing.

        A container of the driver's own, without network, writes the archive into it; the sandbox then
        mounts it read-only. The archive is used once.
        """
        volume = sandbox.skills_volume
        await self._delete_volume(volume)
        image = {f"{LABEL}.image": self.configuration.image}
        await self.docker.volumes.create({"Name": volume, "Labels": {LABEL: "skills"} | sandbox.labels | image})
        archive = self._skills.pop(sandbox.container, None)
        if archive is None:
            return volume
        try:
            labels = sandbox.labels | {f"{LABEL}.files": "true"}
            config = container_config(self.configuration, None, labels, skills=volume, skills_writable=True)
            config["HostConfig"] = {**config["HostConfig"], "NetworkMode": "none", "Dns": []}
            helper = await self.docker.containers.create(
                config, name=f"sibillo-skills-fill-{sandbox.conversation_id}-{uuid.uuid4().hex[:8]}"
            )
            try:
                await helper.start()
                with archive.open("rb") as file:
                    async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                        f"containers/{helper.id}/archive",
                        method="PUT",
                        params={"path": SKILLS},
                        data=file,
                        headers={"content-type": "application/x-tar"},
                    ) as response:
                        await response.read()
            finally:
                with contextlib.suppress(DockerError):
                    await helper.delete(force=True)
        finally:
            archive.unlink(missing_ok=True)
        return volume

    async def stop_all(self) -> int:
        """Stop and remove every sandbox of this driver's image, running or not.

        As when the egress rules disappear (SBX-015), and when the driver starts,
        so that no sandbox is left that the driver does not track (SBX-018,
        ADR-0078). Another driver's sandboxes, of another image, are left alone.
        """
        filters = {"label": [f"{LABEL}=sandbox"], "ancestor": [self.configuration.image]}
        containers = await self.docker.containers.list(all=True, filters=json.dumps(filters))
        await asyncio.gather(*(container.delete(force=True) for container in containers), return_exceptions=True)
        # No bridge has network any more, and every bridge goes (SBX-024, ADR-0113).
        async with self._online_lock:
            self._online = set()
            try:
                await give_online(self.configuration.netguard_socket, set())
            except GuardUnavailableError:
                # A guard that answers again starts with no bridge, or is given none by the monitor.
                logger.warning("the network guard could not be told that no bridge has network")
        networks = await self.docker.networks.list(filters={"label": [f"{LABEL}=network"]})
        mine = [
            network
            for network in networks
            if (network.get("Labels") or {}).get(f"{LABEL}.image") in (self.configuration.image, None)
        ]
        await asyncio.gather(*(self._delete_network_named(network["Name"]) for network in mine), return_exceptions=True)
        # The skills of the containers removed go with them (SBX-022).
        volumes = await self.docker.volumes.list(
            filters={"label": [f"{LABEL}=skills", f"{LABEL}.image={self.configuration.image}"]}
        )
        await asyncio.gather(
            *(self._delete_volume(volume["Name"]) for volume in volumes.get("Volumes") or []), return_exceptions=True
        )
        return len(containers)

    async def start(self) -> None:
        """As the driver starts: no sandbox, and no device, from before is trusted (SBX-018, ADR-0098)."""
        removed = await self.stop_all()
        if removed:
            logger.info("removed %d sandboxes left from before the driver started", removed)
        forgotten = await self.disks.forget_devices()
        if forgotten:
            logger.info("removed %d workspace volumes of devices from before the driver started", forgotten)

    async def shutdown(self) -> None:
        """As the driver stops: its sandboxes are removed and its disks detached (ADR-0098 point 5)."""
        await self.stop_all()
        try:
            await self.disks.release_all()
        except (DockerError, DiskError):
            logger.exception("the disks could not all be detached")

    async def stop_idle(self) -> None:
        """Remove idle sandboxes, and detach their disks once nothing uses them (ADR-0098 point 5)."""
        limit = self.configuration.idle_minutes * 60
        now = time.monotonic()
        for name, last in list(self._last_used.items()):
            if now - last <= limit:
                continue
            async with self._locks.setdefault(name, asyncio.Lock()):
                if self._last_used.get(name) != last:
                    continue
                with contextlib.suppress(DockerError):
                    await self._remove(name)
                logger.info("stopped idle sandbox %s", name)
                sandbox = self._known.get(name)
                released = True
                if sandbox is not None:
                    try:
                        released = await self.disks.release(sandbox)
                    except (DockerError, DiskError):
                        logger.exception("the disk of %s could not be detached", name)
                        released = False
                if released:
                    self._last_used.pop(name, None)
                    self._known.pop(name, None)

    async def execute(
        self,
        sandbox: SandboxId,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str | None,
        timeout_seconds: int | None,
        max_output_bytes: int | None,
    ) -> AsyncIterator[Output | Exit]:
        """Run a command in the conversation's sandbox: its output, then exactly one exit."""
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
        timeout = min(
            timeout_seconds or self.configuration.command_timeout_seconds, self.configuration.command_timeout_seconds
        )
        limit = min(max_output_bytes or self.configuration.max_output_bytes, self.configuration.max_output_bytes)
        # `timeout` kills the command's whole process group when it runs out (ADR-0053).
        command = ["timeout", "--signal=KILL", str(timeout), *argv]
        started = time.monotonic()
        execute = await container.exec(
            cmd=command,
            stdout=True,
            stderr=True,
            stdin=False,
            user="root",
            workdir=workdir or SCRATCH,
            environment={key: value for key, value in env.items()},
        )
        decoders = {
            1: codecs.getincrementaldecoder("utf-8")(errors="replace"),
            2: codecs.getincrementaldecoder("utf-8")(errors="replace"),
        }
        sent = 0
        truncated = False
        finished_in_time = True
        try:
            async with asyncio.timeout(timeout + TIMEOUT_GRACE_SECONDS), execute.start(detach=False) as stream:  # ty: ignore[invalid-context-manager]
                while (message := await stream.read_out()) is not None:
                    data: bytes = message.data
                    if truncated:
                        continue
                    if sent + len(data) > limit:
                        data = data[: limit - sent]
                        truncated = True
                    sent += len(data)
                    text = decoders[message.stream].decode(data)
                    if text:
                        yield Output("stdout" if message.stream == 1 else "stderr", text)
        except TimeoutError:
            finished_in_time = False
        for number, decoder in decoders.items():
            tail = decoder.decode(b"", final=True)
            if tail and not truncated:
                yield Output("stdout" if number == 1 else "stderr", tail)
        exit_code: int | None = None
        if finished_in_time:
            exit_code = (await execute.inspect()).get("ExitCode")
        elapsed = time.monotonic() - started
        timed_out = not finished_in_time or (exit_code in KILLED_EXIT_CODES and elapsed >= timeout)
        self._used(sandbox)
        yield Exit(
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=int(elapsed * 1000),
            workspace_bytes=await self._workspace_bytes(container),
            workspace_quota_bytes=self.configuration.workspace_quota_mb * MIB,
        )

    async def export_workspace(self, sandbox: SandboxId, destination: Path) -> None:
        """Write the conversation's workspace to `destination` as a tar archive of paths relative to it (SBX-020)."""
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
        raw = destination.with_name(f"{destination.name}.docker")
        try:
            async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                f"containers/{container.id}/archive", params={"path": WORKSPACE}
            ) as response:
                with raw.open("wb") as file:
                    async for chunk in response.content.iter_chunked(ARCHIVE_CHUNK_BYTES):
                        await asyncio.to_thread(file.write, chunk)
            await asyncio.to_thread(workspace_entries, raw, destination, WORKSPACE)
        finally:
            raw.unlink(missing_ok=True)

    async def import_workspace(self, sandbox: SandboxId, source: Path) -> None:
        """Replace the conversation's workspace with the archive at `source`, unpacked by Docker (SBX-020).

        Nothing from the archive is run.

        The workspace is emptied first; an archive that would write outside it
        is refused whole, leaving it empty. The sandbox is removed afterwards,
        so that the next command sees the workspace as unpacked.
        """
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
        try:
            await self._run_quietly(container, ["find", WORKSPACE, "-mindepth", "1", "-delete"])
            await asyncio.to_thread(check_archive, source)
            with source.open("rb") as file:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive",
                    method="PUT",
                    params={"path": WORKSPACE},
                    data=file,
                    headers={"content-type": "application/x-tar"},
                ) as response:
                    await response.read()
        finally:
            await self.stop(sandbox)

    async def delete_workspace(self, sandbox: SandboxId) -> None:
        """Remove the conversation's sandbox and delete its workspace and disk, as it is deleted (SBX-010)."""
        name = sandbox.container
        async with self._locks.setdefault(name, asyncio.Lock()):
            await self._remove(name)
            # A file operation may still be ending in a container of its own.
            for _ in range(DELETE_ATTEMPTS):
                try:
                    await self.disks.delete(sandbox)
                    break
                except DiskError:
                    await asyncio.sleep(DELETE_PAUSE_SECONDS)
            else:
                await self.disks.delete(sandbox)
            self._last_used.pop(name, None)
            self._known.pop(name, None)

    async def copy_workspace(self, sandbox: SandboxId, source: SandboxId, folder: Path) -> None:
        """Replace the conversation's workspace with a copy of `source`'s, for a fork (SBX-010, CNV-005)."""
        archive = folder / "workspace.tar"
        await self.export_workspace(source, archive)
        await self.import_workspace(sandbox, archive)

    # --- Files of the workspace (SBX-014, ADR-0079) ---

    async def _helper(self, container: Any, *args: str) -> dict[str, Any]:
        """Run the driver's file helper in the sandbox; its answer, or the refusal it reports."""
        code, output, errors = await self._run_logged(container, ["python3", "-I", "-c", HELPER, *args])
        try:
            answer: dict[str, Any] = json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError) as error:
            logger.warning("the file helper failed in %s (%d): %s", container.id[:12], code, errors[-300:])
            raise FileOperationError(503, f"the file helper failed ({code})") from error
        if "error" in answer:
            raise FileOperationError(int(answer["status"]), str(answer["error"]))
        return answer

    @contextlib.asynccontextmanager
    async def _borrowed(self, sandbox: SandboxId) -> AsyncGenerator[Any]:
        """A container of its own for one file operation: no network, the workspace, removed after (ADR-0079).

        It never shares a container with a run, so neither can stop the other's.
        """
        container = await self._files_container(sandbox)
        try:
            yield container
        finally:
            with contextlib.suppress(DockerError):
                await container.delete(force=True)

    async def _files_container(self, sandbox: SandboxId) -> Any:
        config = container_config(self.configuration, sandbox.volume, sandbox.labels | {f"{LABEL}.files": "true"})
        # File operations need no network at all.
        config["HostConfig"] = {**config["HostConfig"], "NetworkMode": "none", "Dns": []}
        name = f"sibillo-files-{sandbox.conversation_id}-{uuid.uuid4().hex[:8]}"
        # Attached and mounted under the sandbox's lock, so that the idle sweep cannot detach it in between.
        async with self._locks.setdefault(sandbox.container, asyncio.Lock()):
            await self.disks.attach(sandbox)
            container = await self.docker.containers.create(config, name=name)
            self._used(sandbox)
        await container.start()
        return container

    async def workspace_size(self, sandbox: SandboxId) -> dict[str, int]:
        async with self._borrowed(sandbox) as container:
            used = await self._workspace_bytes(container)
        return {"bytes": used, "quota_bytes": self.configuration.workspace_quota_mb * MIB}

    async def list_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "list", relative(path))

    async def delete_entry(self, sandbox: SandboxId, path: str) -> None:
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "delete", relative(path))

    async def create_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "mkdir", relative(path))

    async def move_entry(self, sandbox: SandboxId, source: str, target: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "move", relative(source), relative(target))

    async def read_file(self, sandbox: SandboxId, path: str) -> tuple[dict[str, Any], AsyncIterator[bytes]]:
        """A regular file's entry, and its content as a stream that removes its container when it ends."""
        container = await self._files_container(sandbox)
        try:
            item = await self._helper(container, "stat", relative(path), "regular")
        except BaseException:
            with contextlib.suppress(DockerError):
                await container.delete(force=True)
            raise

        async def content() -> AsyncIterator[bytes]:
            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive", params={"path": f"{WORKSPACE}/{item['path']}"}
                ) as response:
                    async for piece in tar_member_content(response.content.iter_chunked(ARCHIVE_CHUNK_BYTES)):
                        yield piece
            finally:
                with contextlib.suppress(DockerError):
                    await container.delete(force=True)

        return item, content()

    async def write_file(
        self, sandbox: SandboxId, path: str, length: int, body: AsyncIterator[bytes]
    ) -> dict[str, Any]:
        """Write a new file of `length` bytes from `body`, complete or not at all (SBX-014, SBX-019)."""
        target = relative(path)
        if not target:
            raise FileOperationError(422, "the workspace itself")
        quota = self.configuration.workspace_quota_mb * MIB
        temporary = f".sibillo-upload-{uuid.uuid4().hex}"
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "prepare", target, str(length), str(quota))
            received = 0

            async def stream() -> AsyncIterator[bytes]:
                nonlocal received
                yield file_header(temporary, length)
                async for chunk in body:
                    received += len(chunk)
                    if received > length:
                        raise FileOperationError(422, "more than Content-Length")
                    yield chunk
                if received != length:
                    raise FileOperationError(422, "less than Content-Length")
                yield padding(length)

            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive",
                    method="PUT",
                    params={"path": WORKSPACE},
                    data=stream(),
                    headers={"content-type": "application/x-tar"},
                ) as response:
                    await response.read()
                if received != length:
                    raise FileOperationError(422, "less than Content-Length")
            except BaseException:
                with contextlib.suppress(Exception):
                    await self._helper(container, "discard", temporary)
                raise
            return await self._helper(container, "commit", temporary, target)

    async def zip_folder(self, sandbox: SandboxId, path: str, destination: Path) -> None:
        """Write a folder of the workspace to `destination` as a zip archive, links left out."""
        folder = relative(path)
        source = f"{WORKSPACE}/{folder}" if folder else WORKSPACE
        raw = destination.with_name(f"{destination.name}.tar")
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "folder", folder)
            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive", params={"path": source}
                ) as response:
                    with raw.open("wb") as file:
                        async for chunk in response.content.iter_chunked(ARCHIVE_CHUNK_BYTES):
                            await asyncio.to_thread(file.write, chunk)
                await asyncio.to_thread(zip_from_tar, raw, destination)
            finally:
                raw.unlink(missing_ok=True)


def zip_from_tar(source: Path, destination: Path) -> None:
    """Rewrite Docker's tar of a folder as a zip of its regular files, named relative to that folder.

    Each file keeps whether it is executable, which a skill's scripts need (ADR-0096).
    """
    with tarfile.open(source, "r:") as archive, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as result:
        for member in archive:
            if not member.isreg():
                continue
            name = member.name.split("/", 1)[1] if "/" in member.name else member.name
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | (0o755 if member.mode & 0o111 else 0o644)) << 16
            with extracted, result.open(info, "w") as target:
                while chunk := extracted.read(ARCHIVE_CHUNK_BYTES):
                    target.write(chunk)
