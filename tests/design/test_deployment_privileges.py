"""What the deployment's services may touch of the host (SBX-009, SBX-025, OPS-001, ADR-0114).

The sandbox engine is the only privileged service, nothing mounts the host's
Docker socket, nothing uses the host's network, and the engine's Docker
listens on a Unix socket only.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
import yaml

from tests.support.database import ROOT

COMPOSE = ROOT / "deploy" / "compose.yaml"
ENGINE = ROOT / "deploy" / "images" / "engine"
HOST_RUNTIME_SOCKETS = ("docker.sock", "containerd.sock", "podman.sock", "/var/run", "/run/docker", "/run/containerd")


def _services() -> dict[str, dict[str, Any]]:
    compose = cast(dict[str, Any], yaml.safe_load(COMPOSE.read_text()))
    return cast(dict[str, dict[str, Any]], compose["services"])


def _sources(service: dict[str, Any]) -> list[str]:
    """What a service mounts: named volumes and paths of the host."""
    sources: list[str] = []
    for volume in cast(list[Any], service.get("volumes", [])):
        source = cast(dict[str, Any], volume)["source"] if isinstance(volume, dict) else str(volume).split(":")[0]
        sources.append(str(source))
    return sources


@pytest.mark.spec("SBX-009", "SBX-025")
def test_no_service_mounts_the_hosts_container_runtime() -> None:
    for name, service in _services().items():
        for source in _sources(service):
            assert not any(socket in source for socket in HOST_RUNTIME_SOCKETS), f"{name} mounts {source}"
        assert "DOCKER_HOST" not in json.dumps(service.get("environment", {})) or name == "sandboxd", name


@pytest.mark.spec("SBX-025")
def test_only_the_sandbox_engine_is_privileged() -> None:
    services = _services()
    assert [name for name, service in services.items() if service.get("privileged")] == ["engine"]
    # Capabilities beyond Docker's defaults: the network guard's NET_ADMIN, and nothing else.
    assert {name: service["cap_add"] for name, service in services.items() if service.get("cap_add")} == {
        "netguard": ["NET_ADMIN"]
    }
    for name, service in services.items():
        assert not service.get("pid"), name
        assert not service.get("devices"), name
        assert not service.get("security_opt"), name


@pytest.mark.spec("SBX-025", "OPS-001")
def test_no_service_uses_the_hosts_network() -> None:
    services = _services()
    assert [name for name, service in services.items() if service.get("network_mode") == "host"] == []
    # The network guard is in the engine's network namespace, where the sandbox bridges are.
    assert services["netguard"]["network_mode"] == "service:engine"
    assert "privileged" not in services["netguard"]


@pytest.mark.spec("SBX-025", "OPS-003")
def test_the_engine_is_reached_by_the_driver_alone() -> None:
    services = _services()
    engine = services["engine"]
    assert "ports" not in engine
    # A network of its own, for its way out: no other service is on it.
    assert engine["networks"] == ["sandboxes"]
    assert [name for name, service in services.items() if "sandboxes" in service.get("networks", [])] == ["engine"]
    holders = {
        volume: sorted(name for name, service in services.items() if volume in _sources(service))
        for volume in ("engine-socket", "netguard-socket", "engine")
    }
    assert holders == {
        "engine-socket": ["engine", "sandboxd"],
        "netguard-socket": ["netguard", "sandboxd"],
        "engine": ["engine"],
    }
    assert services["sandboxd"]["environment"]["DOCKER_HOST"].startswith("unix:///run/sibillo-engine/")


@pytest.mark.spec("SBX-025")
def test_the_engines_docker_is_configured_for_a_unix_socket_only() -> None:
    daemon = cast(dict[str, Any], json.loads((ENGINE / "daemon.json").read_text()))
    assert daemon["hosts"] == ["unix:///run/sibillo-engine/docker.sock"]
    assert "tls" not in daemon
    assert "tlsverify" not in daemon
    entry = (ENGINE / "sibillo-engine").read_text()
    for flag in ("tcp://", "-H ", "--host"):
        assert flag not in entry


@pytest.mark.spec("SBX-017")
def test_the_engines_image_pins_gvisor_by_release_and_checksum() -> None:
    dockerfile = (ENGINE / "Dockerfile").read_text()
    assert "ARG GVISOR_RELEASE=" in dockerfile
    assert "storage.googleapis.com/gvisor/releases/" in dockerfile
    for architecture in ("AMD64", "ARM64"):
        (line,) = [line for line in dockerfile.splitlines() if line.startswith(f"ARG GVISOR_SHA256_{architecture}=")]
        assert len(line.split("=", 1)[1]) == 64
    assert "sha256sum --check --strict" in dockerfile
