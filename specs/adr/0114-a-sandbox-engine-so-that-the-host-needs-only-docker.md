# ADR-0114: A sandbox engine, so that the host needs only Docker

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0021, ADR-0022, ADR-0023, ADR-0053, ADR-0098, ADR-0113, OPS-001, OPS-002, OPS-006, OPS-009, SBX-002, SBX-003, SBX-005, SBX-009, SBX-015, SBX-017, SBX-024, SBX-025

## Context

Installing Sibillo takes more than Docker Compose. The instance admin must
first install gVisor on the host, from gVisor's own repository, and register
it with Docker as a runtime (ADR-0023); the README says how, and the driver
refuses to work until it is done (SBX-017). Sibillo then reaches further
into the host:

- the sandbox driver mounts the host's Docker socket, and sandboxes are
  containers of the host's Docker, beside whatever else the host runs
  (ADR-0022);
- the network guard runs with host networking and writes a table into the
  host's firewall (ADR-0021).

Each of these is a step a person can get wrong, a difference between hosts,
and something an uninstall must undo. ADR-0113 is about to add a bridge for
each sandbox to the host as well.

## Decision

1. **A sandbox engine.** One container, the sandbox engine, runs a Docker
   Engine of its own with gVisor in it. Sandboxes, their bridges, their
   workspaces and the disk helper (ADR-0098) are containers, networks and
   volumes of that engine, not of the host's Docker. The host needs Docker
   Engine with Compose and nothing else: no gVisor, no change to its Docker
   configuration, no table in its firewall (OPS-001).

2. **gVisor comes with Sibillo.** The engine's image holds `runsc` and the
   programs it runs with, of one release from gVisor's official repository,
   pinned and verified by checksum when the image is built. The driver still
   refuses to start sandboxes below the minimum release (SBX-017), which now
   guards against a wrong image rather than a wrong host. gVisor is updated
   by updating Sibillo.

3. **The driver talks to the engine only.** The engine's Docker listens on a
   Unix socket, in a volume that only the driver shares, and never on a
   network address. No component mounts the host's Docker socket (SBX-009,
   SBX-025). The driver's code changes little: it is still a client of a
   Docker API.

4. **The egress table lives in the engine.** The sandbox bridges are in the
   engine's network namespace, so the table of ADR-0021 and the set of
   ADR-0113 are installed there, by the network guard, which shares that
   namespace with `NET_ADMIN` and nothing else, in place of host
   networking. The rules are the same: they match the sandbox bridges, drop
   every local range, which now includes the instance's own networks, and
   drop everything addressed to the engine itself. They are still outside
   the sandbox's kernel, in the kernel of the host, and hold for code with
   full control of a sandbox's network configuration. The driver follows the
   guard over the socket the two share (ADR-0113), since it can no longer
   ask the host's Docker about the guard's container.

5. **The engine is privileged, and nothing else is.** A Docker Engine in a
   container needs the `privileged` flag. The engine runs no project code
   beyond starting Docker, takes no requests but the driver's, and is the
   only privileged container of the instance; the disk helper is privileged
   inside it, as it was on the host.

6. **Fail closed across restarts.** When the engine restarts, its network
   namespace is new and the egress table is gone until the guard installs
   it. The engine never starts a sandbox by itself, the driver starts none
   before it has verified the table, and it stops every sandbox it finds
   when it starts (SBX-015, SBX-018).

7. **The sandbox image travels with the engine.** The engine has the sandbox
   image without a registry and without the host's Docker: it is part of
   what the engine's image is built from, and the engine loads it when it
   starts and the image changed.

8. **Workspaces move by backup and restore.** Workspaces are volumes of the
   engine from now on. An instance that has workspaces in the host's Docker
   keeps them by making a backup before the upgrade and restoring it after
   (OPS-006).

A spike tried this on 2026-11-21, on Ubuntu 26.04 with kernel 7.0 and
cgroup v2, an AMD Ryzen 9 5950X without `/dev/kvm`, Docker 29.1.0 on the
host and 29.10.0 in the engine, and gVisor `release-20261116.0`:

| Tried | Result |
|---|---|
| A gVisor sandbox of the sandbox image in the engine | **Passed.** It started in 0.31 s, against 0.25 s on the host |
| The egress table of ADR-0021 with the set of ADR-0113, in the engine's network namespace | **Passed.** A sandbox out of the set reached nothing. In the set it reached the internet, by address and by name, and not the host's LAN address, the router, the gateway of the engine's network, a container beside the engine, the engine itself or the engine's Docker. A runc container on the engine's default bridge, which the table does not match, reached every one of them: the table is what blocks |
| A container with `NET_ADMIN` on a bridge out of the set, with the address of an online sandbox | **Passed.** It was dropped, and the online sandbox kept working |
| The memory limit of a sandbox | **Passed.** A sandbox that used more than its limit was stopped, as on the host |
| A workspace disk: an ext4 file on a loop device, mounted as a volume of a gVisor sandbox | **Passed.** Writes stopped at the disk's size, and files were kept |
| The engine without `privileged`, with every capability and without seccomp and AppArmor | **Failed.** Docker did not start: the control groups are read-only |
| A restart of the engine | The table was gone. A sandbox started again by hand, before any table, reached the internet and the host's SSH: point 6 |
| Loading the sandbox image into the engine | 18 s, once; the engine's volume held 2.7 GB |

The spike also found that gVisor is `runsc` and a folder of programs beside
it, all of which the image needs, and that the engine's stock image listens
on a network port without TLS when TLS is switched off: the control
container reached it, which is why point 3 forbids it. The host's firewall
held no table of the spike at any time.

## Consequences

- Installing is `docker compose up`. The README loses the installation of
  gVisor; uninstalling removes containers and volumes, and leaves the host
  as it was.
- Every instance runs the gVisor release its Sibillo release was tested
  with, and a new one arrives with an upgrade, without a step of the admin.
- The host's Docker socket is mounted nowhere. A compromised driver controls
  the engine rather than the host's Docker; since the engine is privileged,
  that is still root on the host in effect, so T-07 stands as it was and
  SBX-009 stays as important.
- An escape from gVisor lands in a privileged container, which is no
  stronger a wall than the host was. The isolation of a sandbox is gVisor's,
  as before (ADR-0023).
- The instance needs a host that allows privileged containers and has
  cgroup v2: rootless Docker is not supported, and the startup check says so
  (OPS-002). Hosts with a strict AppArmor or SELinux policy, Docker Desktop,
  cgroup v1 and arm64 were not tried.
- The sandbox image is on disk twice, in the engine's image and in the
  engine, and the first start loads it.
- Loop devices of workspace disks are the host's, as they were: a
  privileged container sees the host's devices.
- ADR-0113 changes in one place only: the table and the bridges are the
  engine's.
- Tests that start sandboxes need a privileged container instead of a
  runner with gVisor installed; the test harness contract and the time
  budget of the test jobs (ADR-0059) follow.
- Contracts to change once this is accepted: the configuration of the
  driver, the engine and the network guard, and the test harness. The
  driver's API does not change for this.
- The KVM platform of gVisor, which ADR-0023 leaves to the admin, becomes a
  setting of the engine; it was not tried.

## Alternatives considered

- **A service that installs gVisor on the host at first start:** hides the
  step without removing it, and changes the host's Docker configuration from
  a container.
- **The driver runs `runsc` itself, without a Docker in between:** no
  nested Docker and no second copy of the sandbox image, the cleanest end.
  But the driver would set up networks, volumes and commands by itself:
  most of its code, all security-critical, rewritten. To be reconsidered
  once this works.
- **Docker in the driver's own container:** one container less, but the
  driver, which takes requests from the control plane, would be privileged
  itself.
- **A runtime for unprivileged nested containers, such as Sysbox:** would
  spare the `privileged` flag, but is itself installed on the host.
- **Plain containers without gVisor:** nothing to install, and too weak for
  code written by a model that reads untrusted content (ADR-0023).
