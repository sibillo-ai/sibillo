"""The fixed sandbox policy (ADR-0022, ADR-0053): nothing in a request can change it."""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from dataclasses import dataclass
from typing import Any

from sibillo_sandboxd.config import DriverConfiguration

# The prefix of every sandbox bridge's interface name, which the egress table matches (SBX-024, ADR-0113).
BRIDGE_PREFIX = "sbx"
WORKSPACE = "/workspace"
# Where commands start: discarded with the sandbox, unlike the workspace (SBX-018, ADR-0076).
SCRATCH = "/scratch"
# The skills given to a run, read-only and outside the workspace (SBX-022, ADR-0096).
SKILLS = "/skills"
LABEL = "dev.sibillo.sandbox"
# The gVisor flag that bounds the overlay of a sandbox's root filesystem (SBX-016, ADR-0098).
DISK_ANNOTATION = "dev.gvisor.flag.overlay2"
MIB = 1024 * 1024


@dataclass(frozen=True)
class SandboxId:
    """A conversation's sandbox and workspace: its tenant, its user and the conversation (SBX-001, ADR-0078)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID

    @property
    def container(self) -> str:
        return f"sibillo-sandbox-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def volume(self) -> str:
        return f"sibillo-workspace-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def disk_volume(self) -> str:
        """The volume holding the workspace's disk, `workspace.ext4`; never mounted in a sandbox (ADR-0098)."""
        return f"sibillo-disk-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def skills_volume(self) -> str:
        """The skills of the sandbox's container, mounted read-only at /skills and removed with it (SBX-022)."""
        return f"sibillo-skills-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def labels(self) -> dict[str, str]:
        return {
            f"{LABEL}.tenant": str(self.tenant_id),
            f"{LABEL}.user": str(self.user_id),
            f"{LABEL}.conversation": str(self.conversation_id),
        }


def network_name(container: str) -> str:
    """The Docker network of a sandbox's own bridge, named after its container (SBX-024, ADR-0113)."""
    return f"{container}-bridge"


def bridge_interface(container: str) -> str:
    """The interface name of a sandbox's bridge: the prefix and twelve hexadecimal digits, fifteen characters."""
    return BRIDGE_PREFIX + hashlib.sha256(container.encode()).hexdigest()[:12]


def network_config(container: str, subnet: ipaddress.IPv4Network, labels: dict[str, str], image: str) -> dict[str, Any]:
    """A sandbox's own bridge (ADR-0021, ADR-0113): its interface name with the prefix, a subnet of four
    addresses, no IPv6. Whether it has network is the egress table's set, never the bridge's."""
    gateway = next(subnet.hosts())
    return {
        "Name": network_name(container),
        "Driver": "bridge",
        "EnableIPv6": False,
        "Internal": False,
        "IPAM": {"Driver": "default", "Config": [{"Subnet": str(subnet), "Gateway": str(gateway)}]},
        "Options": {
            "com.docker.network.bridge.name": bridge_interface(container),
            "com.docker.network.bridge.enable_icc": "false",
            "com.docker.network.bridge.enable_ip_masquerade": "true",
        },
        "Labels": {LABEL: "network", f"{LABEL}.image": image} | labels,
    }


def container_config(
    configuration: DriverConfiguration,
    volume: str | None,
    labels: dict[str, str],
    *,
    skills: str | None = None,
    skills_writable: bool = False,
    network: str | None = None,
) -> dict[str, Any]:
    """A sandbox container: gVisor, its own bridge, the limits, no privileges, no credentials.

    `volume` is the conversation's workspace; the canary has none. `skills` is the volume of the skills
    given to the sandbox, read-only at /skills (SBX-022, ADR-0096); writable only to the driver's own
    container that fills it.
    """
    mounts: list[dict[str, Any]] = [] if volume is None else [{"Type": "volume", "Source": volume, "Target": WORKSPACE}]
    if skills is not None:
        mounts.append({"Type": "volume", "Source": skills, "Target": SKILLS, "ReadOnly": not skills_writable})
    memory = configuration.memory_mb * MIB
    return {
        "Image": configuration.image,
        "Cmd": ["sleep", "infinity"],
        "WorkingDir": SCRATCH,
        "Hostname": "sandbox",
        # No credentials, and nothing from the driver's environment (SBX-008).
        "Env": [],
        # Found by its image's name, whatever build of it it runs (SBX-018, ADR-0129).
        "Labels": {LABEL: "sandbox", f"{LABEL}.image": configuration.image} | labels,
        "HostConfig": {
            "Runtime": configuration.runtime,
            # Its own bridge; the driver's own helper containers have no network.
            "NetworkMode": network or "none",
            "Dns": [configuration.resolver],
            "NanoCpus": int(configuration.cpus * 1_000_000_000),
            "Memory": memory,
            "MemorySwap": memory,
            # Docker's pids limit counts gVisor's own threads, not the sandbox's
            # processes, and breaks programs at small values: RLIMIT_NPROC counts
            # the processes inside the sandbox (ADR-0022).
            "Ulimits": [{"Name": "nproc", "Soft": configuration.processes, "Hard": configuration.processes}],
            "Mounts": mounts,
            "Privileged": False,
            # No raw packets on its link (SBX-006, ADR-0129).
            "CapDrop": ["NET_RAW"],
            "SecurityOpt": ["no-new-privileges"],
            "RestartPolicy": {"Name": "no"},
            # gVisor bounds everything outside the workspace, without a runtime of its own (SBX-016, ADR-0098).
            "Annotations": {DISK_ANNOTATION: f"root:self,size={configuration.disk_mb}m"},
        },
    }
