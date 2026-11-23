"""Isolation of sandboxes, checked from inside them (SBX-001 to SBX-015, SBX-024, SBX-025).

See ADR-0021, ADR-0053, ADR-0113 and ADR-0114.

A listener on the host proves that the blocked addresses would be reachable
without the egress rules: a plain container on the default network of the
sandbox engine's Docker, which the egress table does not match, reaches it,
a sandbox does not.

The addresses a sandbox must not reach are probed from a sandbox whose
conversation has internet access: without it a sandbox reaches nothing at
all (SBX-024), which the tests of SBX-024 check by themselves.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.sandbox import (
    BRIDGE_PREFIX,
    SANDBOX_SUBNETS,
    Driver,
    docker,
    free_port,
    host_docker,
    online_sandbox,
    restart_engine,
    restart_guard,
    start_driver_process,
)

CONNECT = (
    "python3 -c \"import socket,sys; s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET);"
    " s.settimeout(3); s.connect((sys.argv[1], int(sys.argv[2]))); print('connected')\""
)
# Connects to every address at once, each with a 3-second timeout, and
# prints `connected <address>` for each that answers: blocked addresses
# time out together instead of one after another.
PROBE = (
    'python3 -c "import socket,sys,threading\n'
    "def probe(host):\n"
    "    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET); s.settimeout(3)\n"
    "    try:\n"
    "        s.connect((host, int(sys.argv[1]))); print('connected', host, flush=True)\n"
    "    except OSError:\n"
    "        pass\n"
    "threads=[threading.Thread(target=probe, args=(host,)) for host in sys.argv[2:]]\n"
    '[thread.start() for thread in threads]; [thread.join() for thread in threads]"'
)
# One address from every range of SBX-005, IPv4 and IPv6.
BLOCKED_RANGES = (
    "0.0.0.1",
    "10.0.0.1",
    "100.64.0.1",
    "127.0.0.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.0.1",
    "224.0.0.1",
    "240.0.0.1",
    "::1",
    "fc00::1",
    "fe80::1",
    "ff02::1",
)
# The instance's resolver, the default (SBX-007).
RESOLVER = "9.9.9.9"
# A public address that answers HTTP, for a connection held open.
PUBLIC_HTTP = "1.1.1.1"
# Opens a connection, waits for the file named by its argument, then asks over that connection and
# writes what came of it beside the file: `answered`, `closed` or `silent`.
HELD_CONNECTION = f"""
import os, socket, sys, time
flag = sys.argv[1]
held = socket.create_connection(("{PUBLIC_HTTP}", 80), 5)
open(flag + ".open", "w").close()
while not os.path.exists(flag):
    time.sleep(0.1)
held.settimeout(4)
try:
    held.sendall(b"HEAD / HTTP/1.0\\r\\nHost: {PUBLIC_HTTP}\\r\\n\\r\\n")
    outcome = "answered" if held.recv(16) else "closed"
except OSError:
    outcome = "silent"
open(flag + ".result", "w").write(outcome)
"""
# Prints `left <mark>` for each of the marks given that it sees in a frame leaving through an
# interface, for a number of seconds: what the egress table let out of the sandbox engine.
SNIFF = """
import socket, sys, time
interface, seconds, marks = sys.argv[1], float(sys.argv[2]), sys.argv[3:]
frames = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
frames.bind((interface, 0))
frames.settimeout(0.2)
print("listening", flush=True)
end, seen = time.monotonic() + seconds, set()
while time.monotonic() < end:
    try:
        frame = frames.recv(4096)
    except OSError:
        continue
    for mark in marks:
        if mark not in seen and mark.encode() in frame:
            seen.add(mark)
            print("left", mark, flush=True)
"""
# Sends its argument three times to a public address, over UDP, which needs no answer.
SEND = (
    'python3 -c "import socket,sys; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM);'
    f" [s.sendto(sys.argv[1].encode(), ('{PUBLIC_HTTP}', 9)) for _ in range(3)]\""
)


def _sandbox() -> tuple[str, str, str]:
    """A tenant, a user and a conversation of theirs: one sandbox (SBX-001)."""
    return str(uuid7()), str(uuid7()), str(uuid7())


def _connects(driver: Driver, tenant_id: str, user_id: str, conversation_id: str, host: str, port: int) -> bool:
    result = driver.sh(tenant_id, user_id, conversation_id, f"{CONNECT} {host} {port}", timeout_seconds=15)
    return result.exit_code == 0 and "connected" in result.stdout


def _reachable(
    driver: Driver, tenant_id: str, user_id: str, conversation_id: str, hosts: list[str], port: int
) -> set[str]:
    """The hosts a sandbox connects to, probed all at once."""
    result = driver.sh(tenant_id, user_id, conversation_id, f"{PROBE} {port} {' '.join(hosts)}", timeout_seconds=15)
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith("connected ")}


def _host_addresses() -> list[str]:
    """IPv4 addresses of this host: its LAN address, Docker's bridges, the sandbox bridge's gateway."""
    output = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, check=True).stdout  # noqa: S607
    addresses = [line.split()[3].split("/")[0] for line in output.splitlines()]
    return [address for address in addresses if not ipaddress.ip_address(address).is_loopback]


@pytest.fixture(scope="module")
def host_listener() -> Iterator[int]:
    """A TCP listener on every address of the host."""
    server = socket.create_server(("0.0.0.0", 0))  # noqa: S104 - reachable from containers on purpose
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                connection, _ = server.accept()
                connection.close()
            except TimeoutError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield port
    stop.set()
    thread.join(5)
    server.close()


def _reachable_from_a_plain_container(image: str, hosts: list[str], port: int) -> set[str]:
    command = f"{PROBE} {port} {' '.join(hosts)}"
    # In the engine, on its Docker's default network, which the egress table does not match.
    output = docker("run", "--rm", image, "sh", "-c", command, timeout=60, check=False)
    return {line.split()[1] for line in output.splitlines() if line.startswith("connected ")}


@pytest.mark.spec("SBX-002")
def test_sandboxes_run_under_gvisor(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    result = sandboxes.sh(tenant_id, user_id, conversation_id, "dmesg 2>/dev/null | head -n 1")
    assert "gVisor" in result.stdout
    for container in sandboxes.sandbox_containers():
        assert container["HostConfig"]["Runtime"] == "runsc"


@pytest.mark.spec("SBX-005")
def test_the_host_is_unreachable_from_sandboxes(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    addresses = _host_addresses()
    assert addresses
    controls = _reachable_from_a_plain_container(sandboxes.image, addresses, host_listener)
    # Not every address: the default bridge of the engine's Docker has the address of the host's.
    assert controls, "negative control: the host is reachable without the egress rules"
    assert _reachable(sandboxes, tenant_id, user_id, conversation_id, addresses, host_listener) == set()


def _engine_addresses(sandboxes: Driver) -> list[str]:
    """IPv4 addresses of the sandbox engine: on the instance's network, and the gateways of its own bridges."""
    output = host_docker("exec", sandboxes.engine, "ip", "-4", "-o", "addr", "show")
    addresses = [line.split()[3].split("/")[0] for line in output.splitlines()]
    return [address for address in addresses if not ipaddress.ip_address(address).is_loopback]


@pytest.mark.spec("SBX-025", "SBX-005")
def test_the_engine_is_unreachable_from_sandboxes(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    addresses = _engine_addresses(sandboxes)
    assert len(addresses) >= 3, addresses
    port = free_port()
    # A listener in the engine's own network namespace, where its Docker would listen if it listened.
    listener = f"sibillo-test-listener-{uuid7()}"
    docker("run", "--detach", "--name", listener, "--network", "host", sandboxes.image,
           "python3", "-m", "http.server", str(port))  # fmt: skip
    try:
        deadline = time.monotonic() + 20
        controls: set[str] = set()
        while controls != set(addresses):
            assert time.monotonic() < deadline, f"negative control: the engine answers at {controls}, not {addresses}"
            controls = _reachable_from_a_plain_container(sandboxes.image, addresses, port)
        assert _reachable(sandboxes, tenant_id, user_id, conversation_id, addresses, port) == set()
    finally:
        docker("rm", "-f", listener, check=False)


@pytest.mark.spec("SBX-025")
def test_the_engines_docker_listens_on_no_network_address(sandboxes: Driver) -> None:
    listening = host_docker("exec", sandboxes.engine, "netstat", "-ltn").splitlines()
    addresses = [line.split()[3] for line in listening if line.startswith(("tcp", "udp"))]
    # Only the resolver the host's Docker gives every container, on its loopback.
    assert [address for address in addresses if not address.startswith("127.0.0.11:")] == []
    sockets = host_docker("exec", sandboxes.engine, "netstat", "-lx")
    assert "/run/sibillo-engine/docker.sock" in sockets


@pytest.mark.spec("SBX-025", "SBX-009")
def test_sandboxes_and_workspaces_are_the_engines_not_the_hosts(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    sandboxes.sh(tenant_id, user_id, conversation_id, "echo kept > /workspace/a.txt")
    label = f"label=dev.sibillo.sandbox.conversation={conversation_id}"
    assert docker("ps", "-q", "--filter", label).split()
    assert docker("volume", "ls", "-q", "--filter", label).split()
    assert host_docker("ps", "-aq", "--filter", label).split() == []
    assert host_docker("volume", "ls", "-q", "--filter", label).split() == []
    (container,) = sandboxes.running(conversation_id)
    (network,) = container["NetworkSettings"]["Networks"].values()
    assert docker("network", "ls", "-q", "--no-trunc", "--filter", f"id={network['NetworkID']}").split()
    assert host_docker("network", "ls", "-q", "--filter", f"id={network['NetworkID']}").split() == []


@pytest.mark.spec("SBX-025")
def test_the_network_guard_shares_the_engines_network_namespace_and_nothing_of_the_host(sandboxes: Driver) -> None:
    guard = cast(list[dict[str, Any]], json.loads(host_docker("inspect", sandboxes.netguard)))[0]
    engine = cast(list[dict[str, Any]], json.loads(host_docker("inspect", sandboxes.engine)))[0]
    host = guard["HostConfig"]
    assert host["NetworkMode"] == f"container:{engine['Id']}"
    assert host["Privileged"] is False
    assert [capability.removeprefix("CAP_") for capability in host["CapAdd"]] == ["NET_ADMIN"]
    assert not any("docker.sock" in mount.get("Source", "") for mount in guard["Mounts"])
    # The table is where the sandbox bridges are: in the engine's namespace.
    sandboxes.ensure(*_sandbox())
    table = host_docker("exec", sandboxes.netguard, "nft", "list", "table", "inet", "sibillo")
    assert BRIDGE_PREFIX in table
    assert BRIDGE_PREFIX in host_docker("exec", sandboxes.engine, "ip", "-o", "link", "show")


@pytest.mark.spec("SBX-005", "SBX-013")
def test_local_ranges_are_unreachable_from_sandboxes(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    assert _reachable(sandboxes, tenant_id, user_id, conversation_id, list(BLOCKED_RANGES), host_listener) == set()


@pytest.mark.spec("SBX-005")
def test_rewriting_routes_inside_the_sandbox_does_not_help(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    # Root in the sandbox controls its own network configuration.
    sandboxes.sh(tenant_id, user_id, conversation_id, "ip route add 192.168.0.0/16 dev eth0 2>/dev/null; ip route show")
    assert _reachable(sandboxes, tenant_id, user_id, conversation_id, _host_addresses(), host_listener) == set()


@pytest.mark.spec("SBX-013")
def test_sandboxes_have_no_ipv6(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    result = sandboxes.sh(
        tenant_id, user_id, conversation_id, "cat /proc/net/if_inet6 2>/dev/null; ip -6 addr show scope global"
    )
    assert "global" not in result.stdout
    assert not _connects(sandboxes, tenant_id, user_id, conversation_id, "2606:4700:4700::1111", 443)


@pytest.mark.spec("SBX-004")
def test_sandboxes_with_internet_access_reach_the_internet(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = online_sandbox(sandboxes)
    assert _connects(sandboxes, tenant_id, user_id, conversation_id, "1.1.1.1", 443)
    by_name = sandboxes.sh(
        tenant_id, user_id, conversation_id, "curl -sS -o /dev/null -w '%{http_code}' https://example.com"
    )
    assert by_name.stdout in {"200", "301", "302"}, by_name.stderr


@pytest.mark.spec("SBX-006")
def test_sandboxes_cannot_reach_each_other(sandboxes: Driver) -> None:
    # Both with network: without it a sandbox reaches nothing at all (SBX-024).
    listener, intruder = online_sandbox(sandboxes), online_sandbox(sandboxes)
    port = 8765
    sandboxes.sh(*listener, f"nohup python3 -m http.server {port} >/dev/null 2>&1 & sleep 1")
    address = sandboxes.sh(*listener, "hostname -i").stdout.split()[0]
    assert _connects(sandboxes, *listener, "127.0.0.1", port), "negative control: the server listens"
    assert not _connects(sandboxes, *intruder, address, port)


@pytest.mark.spec("SBX-001", "TEN-008")
@pytest.mark.parametrize("whose", ["same-user", "same-tenant", "other-tenant"])
def test_workspaces_are_separate(sandboxes: Driver, whose: str) -> None:
    owner = _sandbox()
    other = {
        # Another conversation of the same user (ADR-0078).
        "same-user": (owner[0], owner[1], str(uuid7())),
        "same-tenant": (owner[0], str(uuid7()), str(uuid7())),
        "other-tenant": _sandbox(),
    }[whose]
    secret = f"secret-{uuid7()}"
    written = sandboxes.sh(*owner, f"echo {secret} > /workspace/secret.txt; cat /workspace/secret.txt")
    # Not vacuous: the owner's sandbox has the file.
    assert secret in written.stdout
    found = sandboxes.sh(*other, "ls -a /workspace; cat /workspace/secret.txt 2>/dev/null")
    assert secret not in found.stdout


@pytest.mark.spec("SBX-008")
def test_sandboxes_hold_no_credentials(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    environment = sandboxes.sh(tenant_id, user_id, conversation_id, "env").stdout
    assert sandboxes.token not in environment
    assert "SIBILLO_" not in environment
    assert "DOCKER" not in environment
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "test -e /var/run/docker.sock").exit_code != 0
    for container in sandboxes.sandbox_containers():
        assert not [entry for entry in container["Config"]["Env"] if "TOKEN" in entry or "KEY" in entry]


@pytest.mark.spec("SBX-012", "SBX-002", "SBX-011", "SBX-022")
def test_sandbox_containers_follow_the_fixed_policy(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    sandboxes.sh(tenant_id, user_id, conversation_id, "true")
    containers = sandboxes.sandbox_containers()
    assert containers
    for container in containers:
        host: dict[str, Any] = container["HostConfig"]
        assert host["Privileged"] is False
        assert host["Runtime"] == "runsc"
        assert not host.get("CapAdd")
        assert host.get("PidMode", "") in {"", "private"}
        assert host.get("IpcMode", "") in {"", "private", "shareable", "none"}
        # A bridge of the engine's Docker, never the engine's own network namespace nor another container's.
        assert host["NetworkMode"] not in {"host", "none", "default", "bridge"}
        assert not host["NetworkMode"].startswith("container:")
        assert not host.get("Binds")
        # The workspace, and the skills of the run, read-only (SBX-022, ADR-0096).
        mounts = sorted(container["Mounts"], key=lambda mount: mount["Destination"])
        assert [mount["Type"] for mount in mounts] == ["volume", "volume"]
        assert [mount["Destination"] for mount in mounts] == ["/skills", "/workspace"]
        assert [mount["RW"] for mount in mounts] == [False, True]
        assert host["NanoCpus"] == 500_000_000
        assert host["Memory"] == 256 * 1024 * 1024
        ulimits: list[dict[str, Any]] = host.get("Ulimits") or []
        assert {limit["Name"]: limit["Hard"] for limit in ulimits}.get("nproc") == 64


@pytest.mark.spec("SBX-011")
def test_memory_is_limited(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    result = sandboxes.sh(
        tenant_id,
        user_id,
        conversation_id,
        "python3 -c \"b=bytearray(600*1024*1024); print('allocated')\"",
        timeout_seconds=20,
    )
    assert "allocated" not in result.stdout


@pytest.mark.spec("SBX-011")
def test_processes_are_limited_inside_the_sandbox(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    # Small processes, so that the process limit is reached before memory
    # runs out: forked copies of the interpreter exhaust a small sandbox first.
    script = (
        "import os\n"
        "started = 0\n"
        "for _ in range(200):\n"
        "    try:\n"
        "        os.posix_spawn('/bin/sleep', ['sleep', '5'], {})\n"
        "        started += 1\n"
        "    except OSError:\n"
        "        break\n"
        "print(started)\n"
    )
    result = sandboxes.exec(
        tenant_id, user_id, conversation_id, {"argv": ["python3", "-c", script], "timeout_seconds": 20}
    )
    assert int(result.stdout.strip().splitlines()[-1]) < 64


def _refused_the_runtime(health: dict[str, Any] | None) -> bool:
    """Whether the driver has checked the runtime, or run its canary, and found it is not gVisor."""
    if health is None:
        return False
    checks = cast(dict[str, dict[str, Any]], health["checks"])
    return any(
        checks.get(name, {}).get("ok") is False and checks[name].get("detail")
        for name in ("isolation_runtime", "canary")
    )


@pytest.mark.spec("SBX-003", "SBX-002")
@pytest.mark.parametrize("runtime", ["runc", "no-such-runtime"])
def test_the_driver_refuses_sandboxes_without_gvisor(sandboxes: Driver, runtime: str) -> None:
    port = free_port()
    environment = sandboxes.environment(port, SIBILLO_SANDBOX_RUNTIME=runtime)
    process = start_driver_process(environment)
    try:
        # Never ready, while it starts and once it has checked the runtime.
        last: dict[str, Any] | None = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not _refused_the_runtime(last):
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{port}/v1/health",
                    headers={"Authorization": f"Bearer {sandboxes.token}"},
                    timeout=10,
                )
            except httpx.TransportError:
                time.sleep(0.5)
                continue
            assert response.status_code == 503, "a driver without gVisor reported ready"
            last = response.json()
            time.sleep(0.5)
        assert last is not None, process.output()
        assert last["ready"] is False
        assert not (last["checks"]["isolation_runtime"]["ok"] and last["checks"]["canary"]["ok"])
        tenant_id, user_id, conversation_id = _sandbox()
        refused = httpx.post(
            f"http://127.0.0.1:{port}/v1/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure",
            json={"internet_access": False},
            headers={"Authorization": f"Bearer {sandboxes.token}"},
            timeout=30,
        )
        assert refused.status_code == 503
        assert refused.json()["code"] == "driver.isolation_unavailable"
    finally:
        process.close()


@pytest.mark.spec("SBX-015")
def test_sandboxes_stop_when_the_egress_rules_disappear(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    sandboxes.sh(tenant_id, user_id, conversation_id, "true")
    running = [c for c in sandboxes.sandbox_containers() if c["State"]["Running"]]
    assert running
    host_docker("exec", sandboxes.netguard, "nft", "delete", "table", "inet", "sibillo")
    deadline = time.monotonic() + 30
    while any(c["State"]["Running"] for c in sandboxes.sandbox_containers()):
        assert time.monotonic() < deadline, "sandboxes kept running without egress rules"
        time.sleep(0.5)
    with sandboxes.client() as client:
        assert client.get("/health").status_code == 503
    # The guard restores the table; after a new canary, sandboxes start again.
    health = sandboxes.wait_until_ready()
    assert health["checks"]["egress_table"]["ok"] is True
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "echo back").stdout == "back\n"


@pytest.mark.spec("SBX-025", "SBX-015")
def test_no_sandbox_runs_after_the_engine_restarts_until_the_table_is_verified(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    sandboxes.sh(tenant_id, user_id, conversation_id, "echo kept > /workspace/a.txt")
    assert sandboxes.running(conversation_id)
    restart_engine(sandboxes)
    # The engine starts no sandbox by itself, and its new network namespace has no table yet.
    assert docker("ps", "-q").split() == []
    # The guard, left in a namespace the engine is gone from, stops instead of guarding nothing.
    deadline = time.monotonic() + 20
    while host_docker("inspect", "--format", "{{.State.Running}}", sandboxes.netguard).strip() != "false":
        assert time.monotonic() < deadline, "the network guard kept running in a namespace the engine left"
        time.sleep(0.2)
    assert host_docker("inspect", "--format", "{{.State.ExitCode}}", sandboxes.netguard).strip() == "3"
    # Without a guard the driver accepts nothing.
    deadline = time.monotonic() + 20
    with sandboxes.client() as client:
        while client.get("/health").status_code != 503:
            assert time.monotonic() < deadline, "the driver stayed ready without a network guard"
            time.sleep(0.2)
        refused = client.post(
            f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure", json={"internet_access": False}
        )
        assert refused.status_code == 503
    assert docker("ps", "-q").split() == []
    # Started again, as Docker does in a deployment, the guard joins the engine's new namespace.
    restart_guard(sandboxes)
    health = sandboxes.wait_until_ready()
    assert health["checks"]["egress_table"]["ok"] is True
    assert health["checks"]["canary"]["ok"] is True
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "cat /workspace/a.txt").stdout == "kept\n"


def _resolves(driver: Driver, tenant_id: str, user_id: str, conversation_id: str) -> bool:
    result = driver.sh(tenant_id, user_id, conversation_id, "getent hosts example.com", timeout_seconds=8)
    return result.exit_code == 0 and bool(result.stdout.strip())


def _has_network(driver: Driver, tenant_id: str, user_id: str, conversation_id: str) -> bool:
    """Whether a sandbox reaches a public address, the resolver on its DNS port, or a name."""
    targets = [f"{PUBLIC_HTTP}:443", f"{RESOLVER}:53", f"{RESOLVER}:443"]
    probe = (
        'python3 -c "import socket,sys\n'
        "for target in sys.argv[1:]:\n"
        "    host, port = target.rsplit(':', 1)\n"
        "    s=socket.socket(); s.settimeout(3)\n"
        "    try:\n"
        "        s.connect((host, int(port))); print('connected', target, flush=True)\n"
        "    except OSError:\n"
        '        pass"'
    )
    result = driver.sh(tenant_id, user_id, conversation_id, f"{probe} {' '.join(targets)}", timeout_seconds=15)
    connected = {line.split()[1] for line in result.stdout.splitlines() if line.startswith("connected ")}
    resolves = _resolves(driver, tenant_id, user_id, conversation_id)
    assert (connected == set(targets) and resolves) or (not connected and not resolves), (connected, resolves)
    return resolves


def _bridge(driver: Driver, conversation_id: str) -> dict[str, Any]:
    """The sandbox bridge of a conversation's running sandbox: its Docker network, with the sandbox's place on it."""
    (container,) = driver.running(conversation_id)
    ((name, attachment),) = container["NetworkSettings"]["Networks"].items()
    network = cast(list[dict[str, Any]], json.loads(docker("network", "inspect", attachment["NetworkID"])))[0]
    return {
        "name": name,
        "interface": network["Options"]["com.docker.network.bridge.name"],
        "subnet": ipaddress.ip_network(network["IPAM"]["Config"][0]["Subnet"]),
        "gateway": attachment["Gateway"],
        "address": attachment["IPAddress"],
        "mac": attachment["MacAddress"],
        "network": network,
    }


def _interfaces(driver: Driver) -> str:
    return host_docker("exec", driver.engine, "ip", "-o", "link", "show")


@pytest.mark.spec("SBX-024")
def test_a_sandbox_starts_without_network(sandboxes: Driver) -> None:
    asked, unasked = _sandbox(), _sandbox()
    assert sandboxes.ensure(*asked)["internet_access"] is False
    assert not _has_network(sandboxes, *asked)
    # A sandbox that a command starts, of which the control plane said nothing, has none either.
    assert not _has_network(sandboxes, *unasked)
    # No address answers, the instance's resolver included, also over UDP (SBX-007).
    query = (
        'python3 -c "import socket,struct\n'
        "question=struct.pack('>HHHHHH',4242,0x0100,1,0,0,0)+b'\\x07example\\x03com\\x00'+struct.pack('>HH',1,1)\n"
        "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)\n"
        f"s.sendto(question,('{RESOLVER}',53)); s.recvfrom(512); print('answered')\""
    )
    assert "answered" not in sandboxes.sh(*asked, query, timeout_seconds=8).stdout
    online = online_sandbox(sandboxes)
    assert "answered" in sandboxes.sh(*online, query, timeout_seconds=8).stdout, (
        "negative control: the resolver answers"
    )
    assert _has_network(sandboxes, *online), "negative control: a sandbox with internet access has network"


@pytest.mark.spec("SBX-024")
def test_network_is_given_and_taken_on_a_running_sandbox(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    started = sandboxes.ensure(*sandbox)
    sandboxes.sh(*sandbox, "echo kept > /scratch/note; nohup sleep 300 >/dev/null 2>&1 & echo $! > /scratch/pid")
    (before,) = sandboxes.running(sandbox[2])

    given = sandboxes.ensure(*sandbox, internet_access=True)
    assert given["internet_access"] is True
    assert _has_network(sandboxes, *sandbox)
    # Said again, nothing changes.
    assert sandboxes.ensure(*sandbox, internet_access=True)["internet_access"] is True
    assert _has_network(sandboxes, *sandbox)

    taken = sandboxes.ensure(*sandbox, internet_access=False)
    assert taken["internet_access"] is False
    assert not _has_network(sandboxes, *sandbox)

    assert sandboxes.ensure(*sandbox, internet_access=True)["internet_access"] is True
    assert _has_network(sandboxes, *sandbox)
    sandboxes.withdraw_network(*sandbox)
    assert not _has_network(sandboxes, *sandbox)
    sandboxes.withdraw_network(*sandbox)
    assert sandboxes.ensure(*sandbox)["internet_access"] is False

    # The same sandbox all along: its scratch folder and its background commands are there (SBX-018).
    (after,) = sandboxes.running(sandbox[2])
    assert after["Id"] == before["Id"]
    assert given["started_at"] == taken["started_at"] == started["started_at"]
    survived = sandboxes.sh(*sandbox, "cat /scratch/note; kill -0 $(cat /scratch/pid) && echo alive")
    assert survived.stdout == "kept\nalive\n", survived


@pytest.mark.spec("SBX-024")
def test_taking_the_network_stops_connections_already_open(sandboxes: Driver) -> None:
    sandbox = online_sandbox(sandboxes)
    script = f"cat > /scratch/held.py <<'EOF'\n{HELD_CONNECTION}EOF\n"
    start = "".join(
        f"nohup python3 /scratch/held.py /scratch/{name} >/dev/null 2>&1 & " for name in ("with", "without")
    )
    wait = "for i in $(seq 50); do [ -e /scratch/with.open ] && [ -e /scratch/without.open ] && break; sleep 0.1; done"
    opened = sandboxes.sh(*sandbox, f"{script}{start}{wait}; ls /scratch", timeout_seconds=15)
    assert {"with.open", "without.open"} <= set(opened.stdout.split()), opened

    def outcome(name: str) -> str:
        result = sandboxes.sh(
            *sandbox,
            f"touch /scratch/{name}; for i in $(seq 70); do [ -e /scratch/{name}.result ] && break; sleep 0.1; done;"
            f" cat /scratch/{name}.result",
            timeout_seconds=15,
        )
        return result.stdout

    assert outcome("with") == "answered", "negative control: with network, the connection held open is answered"
    sandboxes.withdraw_network(*sandbox)
    assert outcome("without") == "silent"


@pytest.mark.spec("SBX-024")
def test_taking_the_network_from_no_sandbox_does_nothing(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    sandboxes.withdraw_network(*sandbox)
    assert sandboxes.running(sandbox[2]) == []


@pytest.mark.spec("SBX-024")
@pytest.mark.parametrize("token", [None, "wrong-token-of-sufficient-length-0123456789"], ids=["missing", "wrong"])
def test_taking_the_network_needs_the_control_plane_secret(sandboxes: Driver, token: str | None) -> None:
    sandbox = online_sandbox(sandboxes)
    with sandboxes.client() as client:
        headers = {"Authorization": ""} if token is None else {"Authorization": f"Bearer {token}"}
        response = client.delete(f"/sandboxes/{sandbox[0]}/{sandbox[1]}/{sandbox[2]}/network", headers=headers)
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "driver.unauthenticated"
    assert _has_network(sandboxes, *sandbox)


@pytest.mark.spec("SBX-024")
def test_each_sandbox_has_a_bridge_of_its_own(sandboxes: Driver) -> None:
    first, second = _sandbox(), online_sandbox(sandboxes)
    sandboxes.ensure(*first)
    bridges = [_bridge(sandboxes, sandbox[2]) for sandbox in (first, second)]
    assert len({bridge["name"] for bridge in bridges}) == 2
    assert len({bridge["interface"] for bridge in bridges}) == 2
    assert not bridges[0]["subnet"].overlaps(bridges[1]["subnet"])
    interfaces = _interfaces(sandboxes)
    for bridge in bridges:
        network = bridge["network"]
        assert network["Driver"] == "bridge"
        assert network["EnableIPv6"] is False
        # Four addresses: the network's, the bridge's, the sandbox's and the broadcast's.
        assert bridge["subnet"].prefixlen == 30
        assert bridge["subnet"].subnet_of(ipaddress.ip_network(SANDBOX_SUBNETS))
        assert bridge["interface"].startswith(BRIDGE_PREFIX)
        assert f" {bridge['interface']}:" in interfaces
        assert list(network["Containers"]) == [
            sandboxes.running((first if bridge is bridges[0] else second)[2])[0]["Id"]
        ]
    # The egress table matches every sandbox bridge by the prefix, and lets out only those of its set.
    table = host_docker("exec", sandboxes.netguard, "nft", "list", "table", "inet", "sibillo")
    assert f'iifname "{BRIDGE_PREFIX}*"' in table
    assert f'"{bridges[1]["interface"]}"' in table
    assert f'"{bridges[0]["interface"]}"' not in table

    # The bridge goes with its sandbox.
    sandboxes.stop(*first)
    assert docker("network", "ls", "-q", "--filter", f"name=^{bridges[0]['name']}$").split() == []
    interfaces = _interfaces(sandboxes)
    assert f" {bridges[0]['interface']}:" not in interfaces
    assert f" {bridges[1]['interface']}:" in interfaces
    assert _has_network(sandboxes, *second)
    sandboxes.stop(*second)
    table = host_docker("exec", sandboxes.netguard, "nft", "list", "table", "inet", "sibillo")
    assert f'"{bridges[1]["interface"]}"' not in table


@pytest.mark.spec("SBX-024")
def test_no_network_is_gained_by_posing_as_a_sandbox_that_has_it(sandboxes: Driver) -> None:
    online, offline = online_sandbox(sandboxes), _sandbox()
    sandboxes.ensure(*offline)
    victim = _bridge(sandboxes, online[2])
    suffix = uuid7().hex[-8:]
    marks = {
        name: f"sibillo-{name}-{suffix}"
        for name in ("control", "online", "offline", "posing", "itself", "address", "mac", "still")
    }
    uplink = host_docker("exec", sandboxes.engine, "ip", "-4", "route", "show", "default").split("dev ")[1].split()[0]
    sniffer, bridge, intruder = (f"sibillo-test-{name}-{suffix}" for name in ("sniffer", "bridge", "intruder"))
    # A bridge like a sandbox's, which the driver never said has network, outside the range of its own.
    docker("network", "create", "--driver", "bridge", "--subnet", "10.214.77.0/30",
           "--opt", f"com.docker.network.bridge.name={BRIDGE_PREFIX}test{suffix[:4]}",
           "--opt", "com.docker.network.bridge.enable_ip_masquerade=true", bridge)  # fmt: skip
    try:
        # In the engine's network namespace, listening to what leaves it.
        docker("run", "--detach", "--name", sniffer, "--network", "host", "--cap-add", "NET_RAW", "--user", "0",
               sandboxes.image, "python3", "-u", "-c", SNIFF, uplink, "25", *marks.values())  # fmt: skip
        deadline = time.monotonic() + 10
        while "listening" not in docker("logs", sniffer, check=False):
            assert time.monotonic() < deadline, docker("logs", sniffer, check=False)
            time.sleep(0.2)

        docker("run", "--rm", sandboxes.image, "sh", "-c", f"{SEND} {marks['control']}", timeout=30)
        sandboxes.sh(*online, f"{SEND} {marks['online']}")
        sandboxes.sh(*offline, f"{SEND} {marks['offline']}")
        # Root in the sandbox takes the address of the sandbox that has network.
        route = "ip route replace default via {gateway} dev eth0 onlink"
        sandboxes.sh(
            *offline,
            f"ip addr add {victim['address']}/30 dev eth0; {route.format(gateway=victim['gateway'])};"
            f" {SEND} {marks['posing']}",
        )
        # A compromised sandbox kernel: full control of an interface on a bridge without network. It
        # sends as itself, then with the other sandbox's address, then with its address and MAC.
        own_gateway = "10.214.77.1"
        pose = (
            f"ip addr flush dev eth0; ip addr add {victim['address']}/30 dev eth0; {route.format(gateway=own_gateway)}"
        )
        docker(
            "run", "--rm", "--name", intruder, "--network", bridge, "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
            "--user", "0", sandboxes.image, "sh", "-c",
            f"{SEND} {marks['itself']}; {pose}; {SEND} {marks['address']};"
            f" ip link set eth0 down; ip link set eth0 address {victim['mac']}; ip link set eth0 up; {pose};"
            f" {SEND} {marks['mac']}; ip -o addr show dev eth0; ip -o link show dev eth0",
            timeout=30,
        )  # fmt: skip
        # The sandbox posed as kept its network all along.
        sandboxes.sh(*online, f"{SEND} {marks['still']}")
        assert _has_network(sandboxes, *online)
        assert not _has_network(sandboxes, *offline)

        expected = {marks[name] for name in ("control", "online", "still")}
        deadline = time.monotonic() + 5
        left: set[str] = set()
        while left != expected and time.monotonic() < deadline:
            logs = docker("logs", sniffer, check=False)
            left = {line.split()[1] for line in logs.splitlines() if line.startswith("left ")}
            time.sleep(0.2)
        assert left == expected, {name for name, mark in marks.items() if mark in left}
    finally:
        docker("rm", "-f", sniffer, intruder, check=False)
        docker("network", "rm", bridge, check=False)
