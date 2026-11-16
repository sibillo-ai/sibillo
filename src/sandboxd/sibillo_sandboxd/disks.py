"""Workspace disks: sparse ext4 files attached to loop devices (SBX-016, ADR-0098).

Each workspace is a file, `workspace.ext4`, in a Docker volume of its own.
The disk helper, a short-lived privileged container of the sandbox image
under `runc`, makes it, grows it, attaches it to a loop device and detaches
it, with the fixed commands of `HELPER`; it converts a workspace from before
ADR-0098 by copying its files into a new disk. The driver then mounts the
device as the workspace's volume, of type `ext4`. Sandboxes see only that
filesystem, never the file that holds it.
"""

# aiodocker leaves some parameters untyped; only those checks are relaxed here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import contextlib
import logging
import re
import secrets
from collections.abc import Sequence
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from sibillo_sandboxd.config import DriverConfiguration
from sibillo_sandboxd.policy import LABEL, MIB, SandboxId

logger = logging.getLogger("sibillo.sandboxd")

NOT_FOUND = 404
IN_USE = 409
HELPER_TIMEOUT_SECONDS = 600
# Where the helper sees the disk's volume, and a workspace from before ADR-0098.
DISK_FOLDER = "/disk"
OLD_FOLDER = "/old"
DISK_FILE = "workspace.ext4"
MOUNT_OPTIONS = "nodev,nosuid,discard"
DEVICE = re.compile(r"^/dev/loop\d+$")

# The helper's fixed commands; the arguments are the command, then numbers or device names the driver made.
# A disk is the quota plus 10% and 32 MiB, rounded up to a MiB; one converted from a workspace holding more
# than the quota is sized for what it holds instead (ADR-0098 points 2 and 7).
HELPER = r"""
set -eu
command=$1
quota=${2:-0}
disk=/disk/workspace.ext4
mib=1048576

size_for() {
    echo $(( ( ($1 * 11 / 10 + 32 * mib) + mib - 1 ) / mib * mib ))
}

make_disk() {
    rm -f "$disk.new"
    truncate -s "$1" "$disk.new"
    mkfs.ext4 -q -F -m 0 -E root_owner=0:0,lazy_itable_init=1,lazy_journal_init=1 "$disk.new"
    # A new workspace is empty: no lost+found, which e2fsck makes again if it ever needs one.
    debugfs -w -R "rmdir lost+found" "$disk.new" >/dev/null 2>&1
}

# A free loop device for a file: its node is made when the device is newer than the helper's /dev.
attach_file() {
    for attempt in 1 2 3 4 5 6 7 8; do
        number=$(python3 -I -c 'import fcntl, os; print(fcntl.ioctl(os.open("/dev/loop-control", os.O_RDWR), 0x4C82))')
        node=/dev/loop$number
        if [ ! -b "$node" ]; then
            numbers=$(cat "/sys/block/loop$number/dev")
            mknod "$node" b "${numbers%%:*}" "${numbers##*:}"
        fi
        if losetup "$node" "$1" 2>/dev/null; then
            echo "$node"
            return 0
        fi
    done
    echo "no free loop device" >&2
    return 1
}

case "$command" in
attach)
    wanted=$(size_for "$quota")
    if [ ! -e "$disk" ]; then
        make_disk "$wanted"
        mv "$disk.new" "$disk"
    fi
    device=$(losetup -j "$disk" | head -n 1 | cut -d: -f1)
    if [ -z "$device" ]; then
        if [ "$(stat -c %s "$disk")" -lt "$wanted" ]; then
            truncate -s "$wanted" "$disk"
            e2fsck -f -p "$disk" >/dev/null || [ $? -le 1 ]
            resize2fs "$disk" >/dev/null 2>&1
        fi
        device=$(attach_file "$disk")
    fi
    echo "device $device"
    ;;
convert)
    if [ ! -e "$disk" ]; then
        held=$(du -sb /old | cut -f 1)
        base=$quota
        if [ "$held" -gt "$base" ]; then base=$held; fi
        make_disk "$(size_for "$base")"
        device=$(attach_file "$disk.new")
        mkdir -p /new
        mount -o nodev,nosuid "$device" /new
        # Files, folders and links only, as workspace archives hold them (SBX-020); links are not followed.
        (cd /old && find . -mindepth 1 \( -type f -o -type d -o -type l \) -print0 \
            | tar --null --no-recursion -T - -cf -) | tar -C /new -xpf -
        umount /new
        losetup -d "$device"
        mv "$disk.new" "$disk"
    fi
    echo "converted"
    ;;
detach)
    for device in $(losetup -j "$disk" | cut -d: -f1); do
        losetup -d "$device"
    done
    echo "detached"
    ;;
detach-devices)
    shift
    for device in "$@"; do
        losetup -d "$device" 2>/dev/null || true
    done
    echo "detached"
    ;;
check)
    test -c /dev/loop-control
    python3 -I -c 'import fcntl, os; print(fcntl.ioctl(os.open("/dev/loop-control", os.O_RDWR), 0x4C82))' >/dev/null
    command -v mkfs.ext4 losetup e2fsck resize2fs >/dev/null
    echo "ready"
    ;;
*)
    echo "unknown command" >&2
    exit 2
    ;;
esac
"""


class DiskError(Exception):
    """A workspace's disk could not be made, attached, converted or detached."""


def helper_config(
    configuration: DriverConfiguration,
    labels: dict[str, str],
    argv: Sequence[str],
    *,
    disk: str | None,
    old: str | None = None,
) -> dict[str, Any]:
    """The disk helper: privileged under runc, without network, with only the disk's volume (ADR-0098 point 3)."""
    mounts: list[dict[str, Any]] = []
    if disk is not None:
        mounts.append({"Type": "volume", "Source": disk, "Target": DISK_FOLDER})
    if old is not None:
        mounts.append({"Type": "volume", "Source": old, "Target": OLD_FOLDER, "ReadOnly": True})
    return {
        "Image": configuration.image,
        "Entrypoint": ["sh", "-c", HELPER, "disk-helper"],
        "Cmd": list(argv),
        "Env": [],
        "Labels": {LABEL: "disk-helper"} | labels,
        "NetworkDisabled": True,
        "HostConfig": {
            "Runtime": "runc",
            "Privileged": True,
            "NetworkMode": "none",
            "Mounts": mounts,
            "RestartPolicy": {"Name": "no"},
        },
    }


class Disks:
    """Workspace disks and their loop devices. Callers hold the sandbox's lock (ADR-0098 point 4)."""

    def __init__(self, docker: aiodocker.Docker, configuration: DriverConfiguration) -> None:
        self.docker = docker
        self.configuration = configuration
        # The device each attached disk was found on since the driver started; nothing older is trusted.
        self._devices: dict[str, str] = {}

    @property
    def quota_bytes(self) -> int:
        return self.configuration.workspace_quota_mb * MIB

    def _labels(self, sandbox: SandboxId, kind: str) -> dict[str, str]:
        # Labelled with the image too, so that what a driver created can be told from another's.
        return {LABEL: kind} | sandbox.labels | {f"{LABEL}.image": self.configuration.image}

    async def _helper(self, argv: Sequence[str], *, disk: str | None, old: str | None = None) -> str:
        """Run the helper to its end: its standard output, or a DiskError with its standard error."""
        labels = {} if disk is None else {f"{LABEL}.disk": disk}
        config = helper_config(self.configuration, labels, argv, disk=disk, old=old)
        container = await self.docker.containers.create(config, name=f"sibillo-disk-helper-{secrets.token_hex(6)}")
        try:
            await container.start()
            result = await container.wait(timeout=HELPER_TIMEOUT_SECONDS)
            output = "".join(await container.log(stdout=True, stderr=False))
            if int(result.get("StatusCode", 1)) != 0:
                errors = "".join(await container.log(stdout=False, stderr=True))
                raise DiskError(f"the disk helper failed ({argv[0]}): {errors.strip()[-500:]}")
            return output
        finally:
            with contextlib.suppress(DockerError):
                await container.delete(force=True)

    async def check(self) -> str:
        """Whether disks can be attached here: the helper finds a free loop device (ADR-0098 point 10)."""
        return (await self._helper(["check"], disk=None)).strip()

    async def _volume(self, name: str) -> dict[str, Any] | None:
        try:
            return await (await self.docker.volumes.get(name)).show()
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise
            return None

    async def _delete_volume(self, name: str) -> bool:
        """Delete a volume; False when a container still uses it."""
        try:
            await (await self.docker.volumes.get(name)).delete()
        except DockerError as error:
            if error.status == NOT_FOUND:
                return True
            if error.status == IN_USE:
                return False
            raise
        return True

    async def attach(self, sandbox: SandboxId) -> None:
        """Make sure the workspace's volume mounts the conversation's own disk, converting an old workspace."""
        key = sandbox.container
        mount = await self._volume(sandbox.volume)
        device = (mount or {}).get("Options", {}) or {}
        known = self._devices.get(key)
        if mount is not None and known is not None and device.get("device") == known:
            return
        try:
            await self.docker.volumes.create({"Name": sandbox.disk_volume, "Labels": self._labels(sandbox, "disk")})
            if mount is not None and not device.get("device"):
                # A workspace from before ADR-0098, holding the files themselves (point 7).
                await self._helper(["convert", str(self.quota_bytes)], disk=sandbox.disk_volume, old=sandbox.volume)
                if not await self._delete_volume(sandbox.volume):
                    raise DiskError("the old workspace is still in use")
                logger.info("converted the workspace %s to a disk", sandbox.volume)
                mount = None
            output = await self._helper(["attach", str(self.quota_bytes)], disk=sandbox.disk_volume)
        except DockerError as error:
            raise DiskError(f"the disk could not be attached: {error}") from error
        found = [line.split()[1] for line in output.splitlines() if line.startswith("device ")]
        if len(found) != 1 or not DEVICE.match(found[0]):
            raise DiskError(f"the disk helper named no device: {output.strip()[-200:]}")
        attached = found[0]
        if mount is not None and device.get("device") != attached and not await self._delete_volume(sandbox.volume):
            raise DiskError("the workspace's volume is in use with another device")
        if mount is None or device.get("device") != attached:
            await self.docker.volumes.create(
                {
                    "Name": sandbox.volume,
                    "Driver": "local",
                    "DriverOpts": {"type": "ext4", "device": attached, "o": MOUNT_OPTIONS},
                    "Labels": self._labels(sandbox, "workspace"),
                }
            )
        self._devices[key] = attached

    def attached(self) -> list[str]:
        """The sandboxes whose disks this driver attached."""
        return list(self._devices)

    async def release(self, sandbox: SandboxId) -> bool:
        """Detach the disk once no container uses its volume; False when one still does (point 5)."""
        if not await self._delete_volume(sandbox.volume):
            return False
        device = self._devices.pop(sandbox.container, None)
        if device is not None:
            await self._helper(["detach-devices", device], disk=None)
        return True

    async def delete(self, sandbox: SandboxId) -> None:
        """Delete the workspace: its volume, its disk's loop devices and its disk (SBX-010)."""
        if not await self._delete_volume(sandbox.volume):
            raise DiskError("the workspace is in use")
        self._devices.pop(sandbox.container, None)
        if await self._volume(sandbox.disk_volume) is not None:
            await self._helper(["detach"], disk=sandbox.disk_volume)
            await self._delete_volume(sandbox.disk_volume)

    async def release_all(self) -> None:
        """Detach every disk this driver attached, as it stops; their volumes go with them (point 5)."""
        devices: list[str] = []
        for key, device in list(self._devices.items()):
            name = key.replace("sibillo-sandbox-", "sibillo-workspace-", 1)
            with contextlib.suppress(DockerError):
                if await self._delete_volume(name):
                    devices.append(device)
            self._devices.pop(key, None)
        if devices:
            await self._helper(["detach-devices", *devices], disk=None)

    async def forget_devices(self) -> int:
        """Remove every workspace volume of this image that mounts a loop device, as the driver starts (point 4).

        A device from before this start may now back another conversation's disk. Workspaces without a
        device hold their files themselves, from before ADR-0098, and are kept for conversion.
        """
        listed = await self.docker.volumes.list(
            filters={"label": [f"{LABEL}=workspace", f"{LABEL}.image={self.configuration.image}"]}
        )
        removed = 0
        for volume in listed.get("Volumes") or []:
            options = volume.get("Options") or {}
            if options.get("device") and await self._delete_volume(volume["Name"]):
                removed += 1
        self._devices.clear()
        return removed
