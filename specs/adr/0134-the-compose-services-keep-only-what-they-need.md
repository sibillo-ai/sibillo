# ADR-0134: The Compose services keep only what they need, checked end to end

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0054, ADR-0129, ADR-0133, OPS-001, OPS-003, SBX-025

## Context

ADR-0129 dropped what the network guard does not need and set
`no-new-privileges`. A security audit also asked for read-only root
filesystems, dropped capabilities for the other services, and an internal
network that does not reach the internet, so that PostgreSQL and the
sandbox driver cannot. These needed the end-to-end test, which can now run
on any host (ADR-0133).

## Decision

1. **Two networks.** `internal` is `internal: true`: PostgreSQL, the
   sandbox driver, migrations, backups and the API and worker meet there,
   and nothing on it reaches the internet. The API and the worker, which
   call providers, MCP servers and push services, and publish the API's
   port, are also on `egress`, which does.
2. **No capabilities where none is needed.** The API, the worker,
   migrations and the sandbox driver drop every capability; the network
   guard keeps `NET_ADMIN` alone.
3. **Read-only root filesystems** for the API, the worker, migrations and
   the network guard, with a `tmpfs` for what each writes: `/tmp`, and the
   guard's `/run/sibillo-netguard`.
4. **Left as they are:** PostgreSQL, the search service and the sandbox
   engine run as their images expect; backup and restore run as root, to
   write the host's backup folder, and stage archives on the container's
   disk, which a `tmpfs` would hold in memory; the driver writes archives to
   its disk for the same reason.

This extends ADR-0129 point 9.

## Consequences

- A compromised API or worker cannot gain a capability, write its own
  code, or reach PostgreSQL from outside the internal network; PostgreSQL
  and the driver reach nothing outside.
- The end-to-end test checks that the deployment still works so.

## Alternatives considered

- **Read-only everywhere:** backups and the driver would stage whole
  workspaces in memory.
