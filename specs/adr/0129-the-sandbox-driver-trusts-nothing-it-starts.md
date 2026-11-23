# ADR-0129: The sandbox driver trusts nothing it starts, and has ceilings

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0021, ADR-0062, ADR-0077, ADR-0078, ADR-0079, ADR-0098, ADR-0113, ADR-0114, OPS-001, SBX-005, SBX-006, SBX-011, SBX-014, SBX-018, SBX-020, T-04, T-05, T-15, T-33, T-34

## Context

A security audit of the sandbox driver and the deployment found:

- **Neighbours on a link.** Sandboxes keep `NET_RAW`, which lets code write
  raw frames. Since ADR-0113 each sandbox has a bridge of its own, so an ARP
  reply reaches only its own gateway, but nothing else needs the
  capability.
- **Sandboxes of an earlier image.** `stop_all` finds sandboxes by the image
  their tag names now; after the image is built again, the sandboxes of the
  earlier build are missed, and keep running without the checks of SBX-015.
- **Ranges SBX-005 does not name:** Azure's WireServer (`168.63.129.16`),
  the IETF protocol assignments (`192.0.0.0/24`), the benchmarking range
  (`198.18.0.0/15`) and the documentation ranges.
- **Programs of the sandbox read without bound.** The driver runs `du` and
  `find` inside a live sandbox, whose code may have replaced them, and reads
  their output whole, without a timeout: a program that writes for ever
  exhausts the driver, and with it every user's sandboxes.
- **Links in archives.** An export keeps a link to an absolute target, as a
  Python virtual environment holds, which the import then refuses after it
  emptied the workspace: such a conversation cannot be forked, nor restored.
  Conversely, a chain of relative links can lead a later member outside the
  workspace while each link stays inside.
- **Exports start networked sandboxes,** which stay up for their idle time;
  a nightly backup starts one per conversation.
- **No ceiling** on the sandboxes and file containers that run at once.
- **Smaller gaps:** a file container whose stream is never read stays; a
  crash leaves the driver's helper containers; FIFOs, sockets and devices
  are reported as files.
- **Deployment:** the network guard keeps Docker's default capabilities
  beside `NET_ADMIN`, though its comment says otherwise; no service sets
  `no-new-privileges`; the driver has no memory limit.

## Decision

1. **Sandboxes drop `NET_RAW`.** A sandbox container drops the capability
   to write raw packets; it has a bridge of its own already (SBX-006).
2. **A sandbox is found by its label.** Every container the driver makes
   carries the label of its image's name, and `stop_all` finds sandboxes by
   it, whatever build they came from.
3. **More ranges are local.** SBX-005, the egress table and the driver's
   check of the resolver add `168.63.129.16/32`, `192.0.0.0/24`,
   `192.0.2.0/24`, `198.18.0.0/15`, `198.51.100.0/24` and `203.0.113.0/24`.
4. **What the driver runs in a sandbox is bounded.** Its own commands in a
   sandbox, such as measuring the workspace, are read up to 1 MiB of output
   and stopped after 60 seconds; a measure that fails is unknown, which the
   disk's own limit covers (ADR-0098).
5. **Links in an archive are links.** An archive may hold links to any
   target, absolute or not, since nothing is written through them; it is
   refused when a member's path goes through a link the archive made, or a
   member is not a file, a folder or a link. The archive is checked before
   the workspace is emptied. This amends SBX-020 and ADR-0077.
6. **Export and import borrow a container without network,** as file
   operations do (ADR-0079), removed when they end; they never start the
   conversation's sandbox.
7. **Ceilings.** At most 64 sandboxes and 32 file containers run at once,
   each configurable; beyond them the driver answers
   `driver.isolation_unavailable` with "no more sandboxes can run at once",
   as it does when subnets run out.
8. **Smaller gaps close.** The monitor removes file containers older than
   ten minutes, and the driver removes its helper containers when it
   starts; a FIFO, socket or device is reported as `other`, and cannot be
   read or downloaded.
9. **The deployment holds what it needs.** The network guard drops every
   capability but `NET_ADMIN`; the API, the worker, the driver and the guard
   run with `no-new-privileges`; the driver has a memory limit of 1 GiB.

## Consequences

- A fork or a restore of a workspace with a virtual environment works.
- A backup no longer leaves a sandbox per conversation running.
- An instance with more than 64 conversations answering at once refuses the
  65th until one ends; the limit can be raised.

## Alternatives considered

- **Measuring the workspace from outside the sandbox:** the driver would
  need to mount every disk itself, which ADR-0114 keeps inside the engine;
  bounding the command achieves the same safety.
- **Dropping links that leave the workspace at export:** breaks the virtual
  environments that are the common case, for no gain once nothing is
  written through a link.
