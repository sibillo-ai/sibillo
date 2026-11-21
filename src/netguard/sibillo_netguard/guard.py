"""The egress table of the sandbox bridge, kept in the sandbox engine's network namespace (ADR-0021, ADR-0114).

The table matches only traffic entering from the sandbox bridge. It drops
forwarded traffic to every local range of SBX-005, all IPv6 (SBX-013), and
everything addressed to the host itself; the rest is left to the host's
normal processing, so sandboxes reach public addresses (SBX-004). DNS, on
ports 53 and 853, reaches only the instance's resolver (SBX-007, ADR-0098).
It never touches other tables.

The guard shares the network namespace of the sandbox engine, where the
sandbox bridge is, and nothing of the host's (SBX-025). The sandbox driver
follows it over a Unix socket that only the two share (ADR-0113).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import signal
import socket
import socketserver
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import cast

logger = logging.getLogger("sibillo.netguard")

TABLE_FAMILY = "inet"
TABLE_NAME = "sibillo"
BRIDGE_INTERFACE = "sibillosbx0"
CHECK_INTERVAL_SECONDS = 1.0
# The guard reports unhealthy this long after it last found the table missing (ADR-0053).
UNHEALTHY_AFTER_MISSING_SECONDS = 10.0
STATE_FILE = Path("/run/sibillo-netguard/last-missing")

BLOCKED_IPV4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
)

RESOLVER_VARIABLE = "SIBILLO_SANDBOX_RESOLVER"
SOCKET_VARIABLE = "SIBILLO_NETGUARD_SOCKET"
DEFAULT_RESOLVER = "9.9.9.9"
DNS_PORTS = (53, 853)
# The interface that joins the sandbox engine to the instance. It is gone from a
# network namespace the engine has left, where a table would guard nothing (ADR-0114).
UPLINK_INTERFACE = "eth0"
# The exit code that says the engine left: the guard is started again, in the engine's new namespace.
EXIT_ENGINE_LEFT = 3


class ConfigurationError(Exception):
    """The configuration is invalid or unknown; the message names the variable."""


@dataclass(frozen=True)
class GuardConfiguration:
    resolver: str
    socket: str


def configuration_from(environment: dict[str, str]) -> GuardConfiguration:
    """The guard's configuration; anything invalid or unknown stops it before it installs the table."""
    known = (RESOLVER_VARIABLE, SOCKET_VARIABLE)
    unknown = sorted(name for name in environment if name.startswith("SIBILLO_") and name not in known)
    if unknown:
        raise ConfigurationError(f"unknown configuration variable {unknown[0]}")
    resolver = resolver_from(environment)
    path = environment.get(SOCKET_VARIABLE, "")
    if not path:
        raise ConfigurationError(f"{SOCKET_VARIABLE} is required")
    if not os.path.isabs(path):
        raise ConfigurationError(f"{SOCKET_VARIABLE} must be an absolute path")
    return GuardConfiguration(resolver, path)


def resolver_from(environment: dict[str, str]) -> str:
    """The instance's resolver: a public IPv4 address, which sandboxes can reach (SBX-005, SBX-007)."""
    value = environment.get(RESOLVER_VARIABLE, DEFAULT_RESOLVER) or DEFAULT_RESOLVER
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ConfigurationError(f"{RESOLVER_VARIABLE} must be an IPv4 address") from None
    if not isinstance(address, ipaddress.IPv4Address):
        raise ConfigurationError(f"{RESOLVER_VARIABLE} must be an IPv4 address")
    if any(address in ipaddress.IPv4Network(network) for network in BLOCKED_IPV4):
        raise ConfigurationError(f"{RESOLVER_VARIABLE} must be a public address: sandboxes cannot reach {value}")
    return value


def rules(resolver: str) -> str:
    """The table: no IPv6, no local ranges, nothing to the host, and DNS only to the resolver."""
    ports = ", ".join(str(port) for port in DNS_PORTS)
    return f"""
table {TABLE_FAMILY} {TABLE_NAME} {{
  chain forward {{
    type filter hook forward priority -10; policy accept;
    iifname "{BRIDGE_INTERFACE}" meta nfproto ipv6 drop
    iifname "{BRIDGE_INTERFACE}" ip daddr {{ {", ".join(BLOCKED_IPV4)} }} drop
    iifname "{BRIDGE_INTERFACE}" meta l4proto {{ tcp, udp }} th dport {{ {ports} }} ip daddr != {resolver} drop
  }}
  chain input {{
    type filter hook input priority -10; policy accept;
    iifname "{BRIDGE_INTERFACE}" drop
  }}
}}
"""


def _nft(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - nft with fixed arguments
        ["nft", *args],  # noqa: S607 - nft from the image's PATH
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def table_present() -> bool:
    """Whether the table is installed with both of its chains."""
    listed = _nft("list", "table", TABLE_FAMILY, TABLE_NAME)
    return listed.returncode == 0 and "chain forward" in listed.stdout and "chain input" in listed.stdout


def install(resolver: str) -> None:
    """Install the table, replacing any previous version of it atomically."""
    script = f"table {TABLE_FAMILY} {TABLE_NAME}\ndelete table {TABLE_FAMILY} {TABLE_NAME}\n{rules(resolver)}"
    result = _nft("-f", "-", stdin=script)
    if result.returncode != 0:
        raise RuntimeError(f"nft refused the egress table: {result.stderr.strip()}")


def remove() -> None:
    _nft("delete", "table", TABLE_FAMILY, TABLE_NAME)


def _mark_missing() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(time.time()))


def engine_present() -> bool:
    """Whether the sandbox engine is in this network namespace: its uplink is here (ADR-0114)."""
    return any(name == UPLINK_INTERFACE for _, name in socket.if_nameindex())


def healthy() -> bool:
    """The health check: the engine is here, the table is in place, and was not missing in the last seconds."""
    if not engine_present() or not table_present():
        return False
    try:
        last_missing = float(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return True
    return time.time() - last_missing > UNHEALTHY_AFTER_MISSING_SECONDS


class _Requests(socketserver.StreamRequestHandler):
    """One request of the sandbox driver on each connection: a JSON object on a line, answered the same way."""

    def handle(self) -> None:
        try:
            request: object = json.loads(self.rfile.readline(65536) or b"{}")
        except ValueError:
            request = None
        operation = cast("dict[str, object]", request).get("op") if isinstance(request, dict) else None
        if operation == "status":
            answer: dict[str, object] = {"healthy": healthy()}
        else:
            answer = {"error": "unknown operation"}
        self.wfile.write(json.dumps(answer).encode() + b"\n")


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(path: str) -> _Server:
    """Listen for the sandbox driver on the socket the two share (ADR-0113)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).unlink(missing_ok=True)
    server = _Server(path, _Requests)
    os.chmod(path, 0o600)
    threading.Thread(target=server.serve_forever, name="requests", daemon=True).start()
    return server


def run(configuration: GuardConfiguration) -> int:
    """Install the table, keep it in place, and remove it on shutdown; the exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = False
    resolver = configuration.resolver

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not engine_present():
        logger.error("no %s here: the guard must share the sandbox engine's network namespace", UPLINK_INTERFACE)
        return EXIT_ENGINE_LEFT
    install(resolver)
    logger.info("egress table %s %s installed for %s", TABLE_FAMILY, TABLE_NAME, BRIDGE_INTERFACE)
    server = serve(configuration.socket)
    try:
        while not stopping:
            time.sleep(CHECK_INTERVAL_SECONDS)
            if not engine_present():
                # The engine restarted, in a new namespace: this one guards nothing (SBX-025).
                logger.error("the sandbox engine left this network namespace: stopping, to join its new one")
                return EXIT_ENGINE_LEFT
            if not table_present():
                logger.warning("egress table missing: reinstalling it")
                _mark_missing()
                install(resolver)
    finally:
        server.shutdown()
        Path(configuration.socket).unlink(missing_ok=True)
        remove()
        logger.info("egress table removed")
    return 0
