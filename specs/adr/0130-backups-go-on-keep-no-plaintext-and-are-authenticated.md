# ADR-0130: Backups go on, keep no plaintext, and are authenticated

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0077, OPS-006, OPS-010, OPS-011, T-15, T-33

## Context

ADR-0077 makes a backup wait for runs to end, stage its contents in the
backup folder, and trust an archive that decrypts. A security audit found:

- **One run stops every backup.** A backup fails when a run is still
  queued or running after ten minutes. A user can keep a run active at the
  backup's hour, and a run left `running` by a crash stays so for ever, since
  nothing fails it: no backup is made again.
- **Plaintext in the backup folder.** The database dump and the secret key
  are written unencrypted under the backup folder while an archive is made,
  and stay there if the backup is killed; the off-site copy the README
  shows ships them. `pg_dump` and `pg_restore` get the superuser's password
  on their command line.
- **Archives are not authenticated.** Anyone who knows the public
  recipient can make an archive that decrypts, and a restore runs
  `pg_restore` as the superuser on what it holds; entries outside the
  manifest are imported too, and folder names of the archive reach the
  driver's addresses.

## Decision

1. **A backup goes on.** It waits for runs to end for up to ten minutes, as
   before, then goes on, and the manifest lists the conversations whose runs
   were still active: their workspaces may be newer than the database. A
   run queued or running for more than 48 hours is failed by the worker's
   sweep, as abandoned.
2. **No plaintext reaches the backup folder.** Contents are staged in the
   container's own temporary folder, never the backup folder, and only the
   encrypted archive is moved there. A backup or restore removes the
   staging folders an interrupted one left, in either place, as it starts,
   and stopping one removes its own. The superuser's password reaches
   `pg_dump` and `pg_restore` in their environment, not their arguments.
3. **Archives are authenticated.** An archive holds `manifest.mac`, an
   HMAC-SHA-256 of the manifest under a key derived from the backup key,
   which only the holder of the backup key can compute. A restore checks it
   before unpacking anything else, and refuses an archive with an entry the
   manifest does not list, or a workspace not named
   `workspaces/<tenant>/<user>/<conversation>.tar` with three UUIDs. This
   corrects ADR-0077 point 5, which trusted an archive that decrypts.

This amends ADR-0077 points 3 to 5.

## Consequences

- A backup is made every night whatever users do; a conversation that was
  answering may be restored with a workspace a little ahead of its messages.
- An interrupted backup leaves nothing readable behind.
- Archives made before this decision have no `manifest.mac` and cannot be
  restored; before the first release, archives are not kept across versions
  anyway (ADR-0071).

## Alternatives considered

- **Signing archives with a key of their own:** a second key for the
  household to keep, for what one derived from the backup key gives.
- **Streaming the dump into `age` without staging:** no plaintext anywhere,
  but the manifest's checksums need each part read twice.
