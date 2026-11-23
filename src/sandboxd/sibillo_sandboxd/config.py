"""Configuration of the sandbox driver, read only from the environment (ADR-0050, ADR-0053).

specs/contracts/configuration.md lists the variables. Anything missing,
invalid or unknown stops the driver before it listens.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass

PREFIX = "SIBILLO_"
VARIABLES = frozenset(
    {
        "SIBILLO_SANDBOXD_HOST",
        "SIBILLO_SANDBOXD_PORT",
        "SIBILLO_SANDBOXD_TOKEN",
        "SIBILLO_SANDBOX_IMAGE",
        "SIBILLO_SANDBOX_RUNTIME",
        "SIBILLO_NETGUARD_SOCKET",
        "SIBILLO_SANDBOX_RESOLVER",
        "SIBILLO_SANDBOX_SUBNETS",
        "SIBILLO_SANDBOX_CPUS",
        "SIBILLO_SANDBOX_MEMORY_MB",
        "SIBILLO_SANDBOX_PROCESSES",
        "SIBILLO_SANDBOX_COMMAND_TIMEOUT_SECONDS",
        "SIBILLO_SANDBOX_MAX_OUTPUT_BYTES",
        "SIBILLO_SANDBOX_IDLE_MINUTES",
        "SIBILLO_SANDBOX_MAX_RUNNING",
        "SIBILLO_SANDBOX_MAX_FILE_CONTAINERS",
        "SIBILLO_SANDBOX_WORKSPACE_QUOTA_MB",
        "SIBILLO_SANDBOX_DISK_MB",
        "SIBILLO_SANDBOX_MINIMUM_GVISOR_RELEASE",
    }
)
MINIMUM_TOKEN_LENGTH = 32
# The oldest gVisor release the driver accepts (ADR-0053); the instance
# admin may require a newer one, never an older one (ADR-0058).
BUILT_IN_MINIMUM_RELEASE = "release-20261026.0"
RELEASE = re.compile(r"^release-(\d{8})\.(\d+)$")


DEFAULT_SUBNETS = "10.213.0.0/16"
DEFAULT_RANGE = ipaddress.IPv4Network(DEFAULT_SUBNETS)
PRIVATE_RANGES = tuple(ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class ConfigurationError(Exception):
    """A configuration variable is missing, invalid or unknown; the message names it."""


@dataclass(frozen=True)
class DriverConfiguration:
    host: str
    port: int
    token: str
    image: str
    runtime: str
    # The Unix socket of the network guard, which only the two share (ADR-0113, ADR-0114).
    netguard_socket: str
    resolver: str
    cpus: float
    memory_mb: int
    processes: int
    command_timeout_seconds: int
    max_output_bytes: int
    idle_minutes: int
    # The workspace quota (SBX-019).
    workspace_quota_mb: int = 2048
    # The disk a sandbox may use outside its workspace (SBX-016).
    disk_mb: int = 4096
    minimum_release: str = BUILT_IN_MINIMUM_RELEASE
    # The range the sandbox bridges take their subnets of four addresses from (SBX-024, ADR-0113).
    subnets: ipaddress.IPv4Network = DEFAULT_RANGE
    # The most sandboxes, and containers of file operations, that run at once (SBX-011, ADR-0129).
    max_running: int = 64
    max_file_containers: int = 32


def _integer(environment: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    value = environment.get(name, str(default))
    if not value.isdigit() or not low <= int(value) <= high:
        raise ConfigurationError(f"{name} must be a whole number from {low} to {high}")
    return int(value)


def _cpus(environment: Mapping[str, str]) -> float:
    value = environment.get("SIBILLO_SANDBOX_CPUS", "1")
    try:
        cpus = float(value)
    except ValueError:
        cpus = -1.0
    if not 0.1 <= cpus <= 64:
        raise ConfigurationError("SIBILLO_SANDBOX_CPUS must be a number from 0.1 to 64")
    return cpus


def release_key(release: str) -> tuple[int, int] | None:
    found = RELEASE.match(release)
    return None if found is None else (int(found.group(1)), int(found.group(2)))


def _minimum_release(environment: Mapping[str, str]) -> str:
    name = "SIBILLO_SANDBOX_MINIMUM_GVISOR_RELEASE"
    value = environment.get(name, BUILT_IN_MINIMUM_RELEASE) or BUILT_IN_MINIMUM_RELEASE
    key, built_in = release_key(value), release_key(BUILT_IN_MINIMUM_RELEASE)
    if key is None:
        raise ConfigurationError(f"{name} must be a gVisor release such as {BUILT_IN_MINIMUM_RELEASE}")
    if built_in is not None and key < built_in:
        raise ConfigurationError(f"{name} may not be older than the built-in minimum, {BUILT_IN_MINIMUM_RELEASE}")
    return value


# The local ranges sandboxes cannot reach (SBX-005): a resolver there would not work (SBX-007, ADR-0098).
LOCAL_RANGES = tuple(
    ipaddress.IPv4Network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        # Azure's WireServer, IETF protocol assignments, benchmarking and documentation ranges (SBX-005, ADR-0129).
        "168.63.129.16/32",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
    )
)


def _resolver(environment: Mapping[str, str]) -> str:
    name = "SIBILLO_SANDBOX_RESOLVER"
    resolver = environment.get(name, "9.9.9.9")
    try:
        address = ipaddress.ip_address(resolver)
    except ValueError:
        raise ConfigurationError(f"{name} must be an IPv4 address") from None
    if not isinstance(address, ipaddress.IPv4Address):
        raise ConfigurationError(f"{name} must be an IPv4 address")
    if any(address in network for network in LOCAL_RANGES):
        raise ConfigurationError(f"{name} must be a public address: sandboxes cannot reach {resolver} (SBX-005)")
    return resolver


def _subnets(environment: Mapping[str, str]) -> ipaddress.IPv4Network:
    """The private range of the sandbox bridges, from a /24 to a /12 (SBX-024, ADR-0113)."""
    name = "SIBILLO_SANDBOX_SUBNETS"
    value = environment.get(name, DEFAULT_SUBNETS) or DEFAULT_SUBNETS
    try:
        network = ipaddress.IPv4Network(value)
    except ValueError:
        raise ConfigurationError(f"{name} must be an IPv4 range such as {DEFAULT_SUBNETS}") from None
    if not 12 <= network.prefixlen <= 24:
        raise ConfigurationError(f"{name} must be a range from a /24 to a /12")
    if not any(network.subnet_of(private) for private in PRIVATE_RANGES):
        raise ConfigurationError(f"{name} must be a private range")
    return network


def _socket(environment: Mapping[str, str]) -> str:
    name = "SIBILLO_NETGUARD_SOCKET"
    path = _required(environment, name)
    if not path.startswith("/"):
        raise ConfigurationError(f"{name} must be an absolute path")
    return path


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def load_configuration(environment: Mapping[str, str]) -> DriverConfiguration:
    unknown = sorted(name for name in environment if name.startswith(PREFIX) and name not in VARIABLES)
    if unknown:
        raise ConfigurationError(f"unknown configuration variable {unknown[0]}")
    token = _required(environment, "SIBILLO_SANDBOXD_TOKEN")
    if len(token) < MINIMUM_TOKEN_LENGTH:
        raise ConfigurationError(f"SIBILLO_SANDBOXD_TOKEN must be at least {MINIMUM_TOKEN_LENGTH} characters")
    resolver = _resolver(environment)
    return DriverConfiguration(
        host=environment.get("SIBILLO_SANDBOXD_HOST", "0.0.0.0"),  # noqa: S104 - the internal network only (OPS-003)
        port=_integer(environment, "SIBILLO_SANDBOXD_PORT", 8100, 1, 65535),
        token=token,
        image=_required(environment, "SIBILLO_SANDBOX_IMAGE"),
        runtime=environment.get("SIBILLO_SANDBOX_RUNTIME", "runsc") or "runsc",
        netguard_socket=_socket(environment),
        resolver=resolver,
        cpus=_cpus(environment),
        memory_mb=_integer(environment, "SIBILLO_SANDBOX_MEMORY_MB", 1024, 64, 262144),
        processes=_integer(environment, "SIBILLO_SANDBOX_PROCESSES", 512, 16, 65536),
        command_timeout_seconds=_integer(environment, "SIBILLO_SANDBOX_COMMAND_TIMEOUT_SECONDS", 300, 1, 86400),
        max_output_bytes=_integer(environment, "SIBILLO_SANDBOX_MAX_OUTPUT_BYTES", 1048576, 1024, 67108864),
        idle_minutes=_integer(environment, "SIBILLO_SANDBOX_IDLE_MINUTES", 5, 1, 10080),
        workspace_quota_mb=_integer(environment, "SIBILLO_SANDBOX_WORKSPACE_QUOTA_MB", 2048, 1, 1048576),
        disk_mb=_integer(environment, "SIBILLO_SANDBOX_DISK_MB", 4096, 64, 1048576),
        minimum_release=_minimum_release(environment),
        subnets=_subnets(environment),
        max_running=_integer(environment, "SIBILLO_SANDBOX_MAX_RUNNING", 64, 1, 16384),
        max_file_containers=_integer(environment, "SIBILLO_SANDBOX_MAX_FILE_CONTAINERS", 32, 1, 1024),
    )
