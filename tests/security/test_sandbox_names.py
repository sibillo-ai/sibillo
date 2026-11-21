"""Sandboxes resolve names only through the instance's resolver (SBX-007, ADR-0098).

The session's resolver is the default, 9.9.9.9. Other public resolvers are
probed from inside a sandbox, where root can choose any: their DNS ports are
blocked, while the same addresses stay reachable on other ports.
"""

from __future__ import annotations

import subprocess
import time

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.sandbox import Driver, free_port, start_driver_process

RESOLVER = "9.9.9.9"
OTHER_RESOLVERS = ("1.1.1.1", "8.8.8.8")
# Asks every server at once for example.com's address, over UDP on port 53,
# and prints `answered <server>` for each that answers within 3 seconds.
QUERY = (
    'python3 -c "import socket,struct,sys,threading\n'
    "question=struct.pack('>HHHHHH',4242,0x0100,1,0,0,0)+b'\\x07example\\x03com\\x00'+struct.pack('>HH',1,1)\n"
    "def ask(server):\n"
    "    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)\n"
    "    try:\n"
    "        s.sendto(question,(server,53)); s.recvfrom(512); print('answered', server, flush=True)\n"
    "    except OSError:\n"
    "        pass\n"
    "threads=[threading.Thread(target=ask, args=(server,)) for server in sys.argv[1:]]\n"
    '[thread.start() for thread in threads]; [thread.join() for thread in threads]"'
)
# Connects to every `host:port` at once and prints `connected <host:port>` for each that accepts.
CONNECT = (
    'python3 -c "import socket,sys,threading\n'
    "def probe(target):\n"
    "    host, port = target.rsplit(':', 1)\n"
    "    s=socket.socket(); s.settimeout(3)\n"
    "    try:\n"
    "        s.connect((host, int(port))); print('connected', target, flush=True)\n"
    "    except OSError:\n"
    "        pass\n"
    "threads=[threading.Thread(target=probe, args=(target,)) for target in sys.argv[1:]]\n"
    '[thread.start() for thread in threads]; [thread.join() for thread in threads]"'
)


def _sandbox() -> tuple[str, str, str]:
    """A tenant, a user and a conversation of theirs: one sandbox (SBX-001)."""
    return str(uuid7()), str(uuid7()), str(uuid7())


def _answered(driver: Driver, servers: tuple[str, ...]) -> set[str]:
    result = driver.sh(*_sandbox(), f"{QUERY} {' '.join(servers)}", timeout_seconds=8)
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith("answered ")}


def _connected(driver: Driver, targets: tuple[str, ...]) -> set[str]:
    result = driver.sh(*_sandbox(), f"{CONNECT} {' '.join(targets)}", timeout_seconds=8)
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith("connected ")}


@pytest.mark.spec("SBX-007")
def test_dns_reaches_only_the_instances_resolver(sandboxes: Driver) -> None:
    answered = _answered(sandboxes, (RESOLVER, *OTHER_RESOLVERS))
    assert RESOLVER in answered, "the instance's resolver must answer"
    assert not answered & set(OTHER_RESOLVERS), answered


@pytest.mark.spec("SBX-007")
def test_dns_over_tls_reaches_only_the_instances_resolver(sandboxes: Driver) -> None:
    targets = tuple(f"{server}:853" for server in OTHER_RESOLVERS)
    # The same servers on port 443: blocked for DNS only, not as addresses.
    controls = tuple(f"{server}:443" for server in OTHER_RESOLVERS)
    connected = _connected(sandboxes, (*targets, *controls, f"{RESOLVER}:853"))
    assert set(controls) <= connected, connected
    assert f"{RESOLVER}:853" in connected
    assert not connected & set(targets), connected


@pytest.mark.spec("SBX-007")
def test_sandboxes_resolve_names_through_the_instances_resolver(sandboxes: Driver) -> None:
    result = sandboxes.sh(*_sandbox(), "getent hosts example.com", timeout_seconds=8)
    assert result.exit_code == 0, result
    assert result.stdout.strip()


@pytest.mark.spec("SBX-007")
@pytest.mark.parametrize("resolver", ["192.168.1.1", "10.0.0.53", "127.0.0.53", "172.17.0.1"])
def test_the_driver_refuses_a_local_resolver(sandboxes: Driver, resolver: str) -> None:
    port = free_port()
    # Another image, so that the second driver cannot touch the session's sandboxes.
    environment = sandboxes.environment(
        port, SIBILLO_SANDBOX_IMAGE=f"sibillo-test/none-{uuid7()}:refused", SIBILLO_SANDBOX_RESOLVER=resolver
    )
    process = start_driver_process(environment)
    try:
        deadline = time.monotonic() + 20
        while process.exited() is None and time.monotonic() < deadline:
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{port}/v1/health",
                    headers={"Authorization": f"Bearer {sandboxes.token}"},
                    timeout=5,
                )
            except httpx.TransportError:
                time.sleep(0.2)
                continue
            assert response.status_code != 200, "a driver with a local resolver reported ready"
            time.sleep(0.2)
        assert process.exited() not in (None, 0), process.output()
        assert "SIBILLO_SANDBOX_RESOLVER" in process.output()
    finally:
        process.close()


@pytest.mark.spec("SBX-007")
def test_the_network_guard_refuses_a_local_resolver(sandboxes: Driver) -> None:
    image = subprocess.run(  # noqa: S603
        ["docker", "inspect", "--format", "{{.Config.Image}}", sandboxes.netguard],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    # In a network namespace of its own and without NET_ADMIN, so that it cannot touch the engine's table.
    result = subprocess.run(  # noqa: S603
        ["docker", "run", "--rm", "--env", "SIBILLO_SANDBOX_RESOLVER=192.168.1.1", image],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert "SIBILLO_SANDBOX_RESOLVER" in result.stdout + result.stderr
