# ADR-0098: Hard disk limits, and names resolved only by the instance's resolver

- **Status:** Proposed
- **Date:** 2026-11-15
- **Deciders:** @tapionx
- **Related:** ADR-0021, ADR-0022, ADR-0053, ADR-0076, ADR-0077, ADR-0078, ADR-0079, SBX-003, SBX-005, SBX-007, SBX-010, SBX-012, SBX-016, SBX-018, SBX-019, SBX-020, T-04, T-15

## Context

A sandbox's disk has no bound. Everything outside `/workspace` lives in
gVisor's overlay, whose upper layer is a file on the host's disk; the
workspace is a Docker volume, a folder on the host's disk. The workspace
quota (SBX-019) is measured after each command and only tells the agent:
one command, such as `fallocate -l 100G` or a runaway download, fills the
host's disk, and with it the database and every other household service
(T-15). ADR-0022 point 7 planned workspaces as fixed-size filesystem images,
and ADR-0076 point 5 found that Docker's local volumes cannot mount one:
`o=loop` is an option of `mount(8)`, not of the kernel.

A spike on 2026-11-15, on ext4 with gVisor `release-20261109.0`, found two
mechanisms that work:

- **Outside the workspace:** gVisor's `--overlay2=root:self,size=…` bounds
  the overlay's upper layer, and a container can set it with the annotation
  `dev.gvisor.flag.overlay2`, which runsc accepts without
  `--allow-flag-override`: no runtime needs registering on the host. In
  the sandbox, `/` then has that size, and writes beyond it fail with
  `ENOSPC`.
- **The workspace:** a sparse file holding an ext4 filesystem, attached to a
  loop device, is mounted by Docker's local volume driver as
  `type=ext4,device=/dev/loopN`; gVisor uses it as any other volume, writes
  stop at its size, and its content outlives the containers. Attaching a loop
  device needs `CAP_SYS_ADMIN` and the host's `/dev`, that is a privileged
  container; the driver already holds the Docker API, which is equivalent to
  root on the host (ADR-0022).

Names: sandboxes are told to use the instance's resolver (ADR-0053), but
root in a sandbox can query any public resolver, on port 53 or with DNS over
TLS on 853. They cannot reach Docker's embedded resolver, which gVisor does
not see, nor a resolver of the household's network, which SBX-005 blocks.
A resolver configured at a private address would therefore not work, and is
accepted today without a word.

## Decision

1. **Everything outside the workspace has a hard limit** (SBX-016). Every
   container the driver creates under gVisor carries the annotation
   `dev.gvisor.flag.overlay2` set to `root:self,size=<N>m`, where N is
   `SIBILLO_SANDBOX_DISK_MB`, 4096 by default. The canary checks that `/`
   has that size: a runtime that ignores the annotation fails the canary,
   and the driver refuses to start sandboxes (SBX-003).
2. **Each workspace is a disk** of a fixed size: a sparse file,
   `workspace.ext4`, in a Docker volume of its own, `sibillo-disk-<ids>`,
   holding an ext4 filesystem made with no reserved blocks: the workspace
   disk. Its size is the
   workspace quota (SBX-019), which thereby becomes a wall as well as a
   measure. The disk's file is never mounted in a sandbox, nor in any
   container that runs user content: sandboxes see only the filesystem the
   host's kernel mounted from it, so they can never write its raw blocks.
3. **The disk helper.** A container of the driver's own does what needs the
   host's kernel: from the sandbox image, with the `runc` runtime, privileged,
   without network, with only the conversation's disk volume mounted, running
   only the driver's fixed commands (`mkfs.ext4`, `e2fsck`, `resize2fs`,
   `losetup`, and `mount` with the copy of point 7), and removed when they
   end. It never runs or interprets what is in a workspace, and reads it
   only to convert one (point 7). It is the one exception to ADR-0022 point 5,
   which still holds for every container that runs user content. The sandbox
   image gets `e2fsprogs` for it.
4. **Attaching.** Before the driver creates a container that mounts a
   workspace, a sandbox or a container for a file operation, it attaches the
   conversation's disk, under the sandbox's lock: the helper makes the disk
   if it is missing, grows it if it is smaller than the quota, finds the
   loop device that backs its file (`losetup -j`) or attaches one, and the
   driver creates the volume `sibillo-workspace-<ids>` of type `ext4` on that
   device, with `nodev`, `nosuid` and `discard`, so that deleted files free
   the host's disk. A device the driver did not check since it started is
   never trusted: after a reboot, `/dev/loopN` may back another
   conversation's disk, so the driver removes every workspace volume of its
   image when it starts, and checks a device before it first uses it.
5. **Detaching.** The driver detaches a disk when it removes its workspace
   volume, which Docker refuses while any container uses it: when the
   conversation is deleted, when it was not used for
   `SIBILLO_SANDBOX_IDLE_MINUTES`, and when the driver stops.
6. **Changing the quota.** A larger quota grows each disk the next time it
   is attached. A smaller one applies to new disks; a disk is never shrunk,
   and the agent is told when its workspace is over the quota (SBX-019).
7. **Existing workspaces** are converted when first attached: the helper
   mounts the old volume read-only and copies its regular files, folders and
   symbolic links, as workspace archives hold them (SBX-020), into a new
   disk, at least as large as the quota and large enough to hold them; the
   driver then removes the old volume. A conversion that fails leaves the old volume as it was, and the
   operation fails with `sandbox.unavailable` (SBX-023).
8. **Forks, exports and imports** go through containers that mount the
   workspace, as before (SBX-020). A copy that does not fit the new disk
   fails as a copy that exceeds the quota.
9. **Names are resolved by the instance's resolver only** (SBX-007). The
   network guard reads `SIBILLO_SANDBOX_RESOLVER`, as the driver does, and its
   table drops traffic from the sandbox bridge to ports 53 and 853, over UDP
   and TCP, addressed anywhere but that resolver. The resolver must be a
   public address: a private one, which SBX-005 blocks, is refused by both
   at startup. DNS over HTTPS cannot be told from other traffic on port 443
   and stays possible; what it resolves still cannot be reached when it is
   local (SBX-005).
10. **Host requirements.** The host must provide loop devices, as every
    common Linux distribution does, and Docker must run as root. The README
    says so, and the driver's health reports the disk helper's check: it
    runs once at startup and must find a free loop device.

## Consequences

- No sandbox can fill the host's disk: what a conversation can use is at
  most the workspace quota plus `SIBILLO_SANDBOX_DISK_MB` for the length of
  an answer.
- A full workspace makes commands fail with `ENOSPC`; the agent is already
  told when it nears its quota, and can tidy up or ask the user.
- Disks are sparse and mounted with `discard`, so the host's disk holds what
  workspaces use, not their quota; a household can still promise more than
  it has, and the README says to size the quota with that in mind.
- Starting a sandbox for a conversation not used recently costs a helper
  run, a few tenths of a second; later starts reuse the attached device.
- The driver creates one privileged container; its commands are fixed, and
  it sees only a file it made itself. A compromised driver could do as much
  through the Docker API already.
- Rootless Docker, and hosts without loop devices, cannot run Sibillo.
- Lowering the quota does not reclaim space from existing workspaces.

## Alternatives considered

- **Measuring only:** the quota as today, and a hard limit outside the
  workspace; simple, but one command can still fill the host's disk, which
  SBX-016 exists to prevent.
- **Killing commands when the workspace grows past its quota,** measured
  while they run: writes of gigabytes a second outrun any measurement.
- **Project quotas on ext4, or XFS with `pquota`:** they need the host's
  filesystem formatted or mounted for them, which a household's server is
  not.
- **Mounting the disks on a host folder from a privileged driver,** with
  shared mount propagation: the driver would run privileged all the time,
  and depend on a path of the host.
- **gVisor's overlay over `/workspace` too,** with a bounded upper layer:
  writes would not reach the volume, and the workspace would not persist.
- **Blocking DNS over HTTPS,** by blocking the addresses of known public
  resolvers: an endless list, and SBX-007 is a SHOULD.
