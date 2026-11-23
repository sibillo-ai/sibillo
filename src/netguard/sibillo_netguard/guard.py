"""The egress table of the sandbox bridges, kept in the sandbox engine's network namespace (ADR-0021, ADR-0114).

The table matches only traffic entering from a sandbox bridge, every
interface whose name starts with the prefix of the sandbox bridges. It drops
everything from a bridge that is not in the set of the bridges with network,
those whose conversation has internet access (SBX-024, ADR-0113). From the
others, it drops forwarded traffic to every local range of SBX-005, all IPv6
(SBX-013), and everything addressed to the host itself; the rest is left to
the host's normal processing, so they reach public addresses (SBX-004). DNS,
on ports 53 and 853, reaches only the instance's resolver (SBX-007,
ADR-0098). It never touches other tables.

The sandbox driver gives the guard the whole list of the bridges with
network; a table the guard installs, or installs again, starts with none.

The guard shares the network namespace of the sandbox engine, where the
sandbox bridge is, and nothing of the host's (SBX-025). The sandbox driver
follows it over a Unix socket that only the two share (ADR-0113).

The guard never removes the table: it stays when the guard stops, fails or
times out, and goes with the engine's namespace (ADR-0120). It is in place
only while it lists as the guard installed it, but for the set's elements.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
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
# The prefix of the sandbox bridges' interface names, and the set of those that have network (SBX-024, ADR-0113).
BRIDGE_PREFIX = "sbx"
ONLINE_SET = "online"
# A sandbox bridge's interface name: the prefix and twelve hexadecimal digits, as the driver names them.
BRIDGE_NAME = re.compile(r"^sbx[0-9a-f]{12}$")
MAX_ONLINE = 16384
CHECK_INTERVAL_SECONDS = 1.0
# The guard reports unhealthy this long after it last found the table missing (ADR-0053).
UNHEALTHY_AFTER_MISSING_SECONDS = 10.0
STATE_FILE = Path("/run/sibillo-netguard/last-missing")
# The table as `nft` listed it once installed, without the set's elements, for the health check (ADR-0120).
EXPECTED_FILE = Path("/run/sibillo-netguard/expected-table")
NFT_TIMEOUT_SECONDS = 10

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
    """The table: nothing from a bridge without network; from the others no IPv6, no local ranges, nothing to the
    host, and DNS only to the resolver. The set of bridges with network starts empty."""
    ports = ", ".join(str(port) for port in DNS_PORTS)
    bridges = f'iifname "{BRIDGE_PREFIX}*"'
    return f"""
table {TABLE_FAMILY} {TABLE_NAME} {{
  set {ONLINE_SET} {{
    type ifname;
  }}
  chain forward {{
    type filter hook forward priority -10; policy accept;
    {bridges} iifname != @{ONLINE_SET} drop
    {bridges} meta nfproto ipv6 drop
    {bridges} ip daddr {{ {", ".join(BLOCKED_IPV4)} }} drop
    {bridges} meta l4proto {{ tcp, udp }} th dport {{ {ports} }} ip daddr != {resolver} drop
  }}
  chain input {{
    type filter hook input priority -10; policy accept;
    {bridges} drop
  }}
}}
"""


def _nft(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """`nft` with `args`; one that hangs past its timeout answers as a failure, and the table counts as missing."""
    try:
        return subprocess.run(  # noqa: S603 - nft with fixed arguments
            ["nft", *args],  # noqa: S607 - nft from the image's PATH
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=NFT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["nft", *args], 124, "", "nft timed out")


def _listing() -> str | None:
    """The table as `nft` lists it, without the set's elements, in a canonical form; None when it is missing."""
    listed = _nft("--json", "list", "table", TABLE_FAMILY, TABLE_NAME)
    if listed.returncode != 0:
        return None
    try:
        items = cast("list[dict[str, object]]", json.loads(listed.stdout)["nftables"])
    except (ValueError, KeyError, TypeError):
        return None
    kept: list[dict[str, object]] = []
    item: dict[str, object]
    for item in items:
        if "metainfo" in item:
            continue
        found = item.get("set")
        if isinstance(found, dict):
            bare: dict[str, object] = {k: v for k, v in cast("dict[str, object]", found).items() if k != "elem"}
            item = {"set": bare}
        kept.append(item)
    return json.dumps(kept, sort_keys=True)


def table_exists() -> bool:
    """Whether a table of that name is there, whatever it holds."""
    return _nft("list", "table", TABLE_FAMILY, TABLE_NAME).returncode == 0


def table_present() -> bool:
    """Whether the table is in place: as the guard installed it, but for the bridges in its set (ADR-0120)."""
    listing = _listing()
    try:
        expected = EXPECTED_FILE.read_text()
    except FileNotFoundError:
        return False
    return listing is not None and listing == expected


def online() -> list[str] | None:
    """The bridges in the set of those with network; None when the table is missing."""
    listed = _nft("--json", "list", "set", TABLE_FAMILY, TABLE_NAME, ONLINE_SET)
    if listed.returncode != 0:
        return None
    try:
        items = cast("list[dict[str, object]]", json.loads(listed.stdout)["nftables"])
    except (ValueError, KeyError, TypeError):
        return None
    for item in items:
        found = item.get("set")
        if isinstance(found, dict):
            elements = cast("list[object]", cast("dict[str, object]", found).get("elem") or [])
            return sorted(str(element) for element in elements)
    return None


def set_online(bridges: list[str]) -> list[str] | None:
    """Make the set of bridges with network exactly `bridges`, at once; the set as it then is, None on failure."""
    elements = ", ".join(f'"{bridge}"' for bridge in bridges)
    script = f"flush set {TABLE_FAMILY} {TABLE_NAME} {ONLINE_SET}\n"
    if bridges:
        script += f"add element {TABLE_FAMILY} {TABLE_NAME} {ONLINE_SET} {{ {elements} }}\n"
    if _nft("-f", "-", stdin=script).returncode != 0:
        return None
    return online()


def install(resolver: str) -> None:
    """Install the table, replacing any previous version of it atomically."""
    script = f"table {TABLE_FAMILY} {TABLE_NAME}\ndelete table {TABLE_FAMILY} {TABLE_NAME}\n{rules(resolver)}"
    result = _nft("-f", "-", stdin=script)
    if result.returncode != 0:
        raise RuntimeError(f"nft refused the egress table: {result.stderr.strip()}")
    listing = _listing()
    if listing is None:
        raise RuntimeError("nft does not list the egress table it installed")
    EXPECTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPECTED_FILE.write_text(listing)


def _mark_missing() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(time.time()))


def sandbox_bridges() -> list[str]:
    """The sandbox bridges in this network namespace."""
    return [name for _, name in socket.if_nameindex() if name.startswith(BRIDGE_PREFIX)]


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


# One change of the set at a time.
_CHANGES = threading.Lock()


class _Requests(socketserver.StreamRequestHandler):
    """One request of the sandbox driver on each connection: a JSON object on a line, answered the same way."""

    def handle(self) -> None:
        try:
            request: object = json.loads(self.rfile.readline(65536) or b"{}")
        except ValueError:
            request = None
        fields = cast("dict[str, object]", request) if isinstance(request, dict) else {}
        operation = fields.get("op")
        if operation == "status":
            answer: dict[str, object] = {"healthy": healthy(), "online": online()}
        elif operation == "online":
            # The whole list of the sandbox bridges with network (SBX-024, ADR-0113).
            bridges = fields.get("bridges")
            if (
                not isinstance(bridges, list)
                or len(cast("list[object]", bridges)) > MAX_ONLINE
                or not all(isinstance(name, str) and BRIDGE_NAME.match(name) for name in cast("list[object]", bridges))
            ):
                answer = {"error": "invalid bridges"}
            else:
                with _CHANGES:
                    answer = {"online": set_online(sorted(set(cast("list[str]", bridges))))}
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


def _keep(resolver: str) -> None:
    """Reinstall the table when it is not in place, and remember that it was missing."""
    if table_present():
        return
    # Reinstalled with no bridge with network: the driver gives the list again (ADR-0113).
    logger.warning("egress table missing or changed: reinstalling it")
    _mark_missing()
    with _CHANGES:
        try:
            install(resolver)
        except RuntimeError:
            logger.exception("the egress table could not be reinstalled; trying again")


def run(configuration: GuardConfiguration) -> int:
    """Install the table and keep it in place, never removing it (ADR-0120); the exit code."""
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
    if not table_exists() and sandbox_bridges():
        # Sandboxes may have run without it: unhealthy for a while, so that the driver stops them (ADR-0120).
        logger.warning("egress table missing at start while sandbox bridges exist")
        _mark_missing()
    install(resolver)
    logger.info("egress table %s %s installed for the bridges %s*", TABLE_FAMILY, TABLE_NAME, BRIDGE_PREFIX)
    server = serve(configuration.socket)
    try:
        while not stopping:
            time.sleep(CHECK_INTERVAL_SECONDS)
            if not engine_present():
                # The engine restarted, in a new namespace: this one guards nothing (SBX-025).
                logger.error("the sandbox engine left this network namespace: stopping, to join its new one")
                return EXIT_ENGINE_LEFT
            _keep(resolver)
    finally:
        # The table stays: it goes with the engine's namespace (ADR-0120).
        server.shutdown()
        Path(configuration.socket).unlink(missing_ok=True)
        logger.info("stopped; the egress table stays in place")
    return 0
