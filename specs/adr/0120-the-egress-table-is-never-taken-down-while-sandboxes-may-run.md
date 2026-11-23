# ADR-0120: The egress table is never taken down while sandboxes may run

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0021, ADR-0113, ADR-0114, SBX-003, SBX-005, SBX-015, SBX-024, T-04, T-18

## Context

The network guard installs the egress table (ADR-0021) in the sandbox
engine's network namespace (ADR-0114), and the sandbox driver stops every
sandbox when the guard reports it missing (SBX-015). Reading both showed
windows in which a sandbox runs without it:

- **The guard removes the table when it stops.** A restart of the guard, a
  `docker compose up` that recreates it, or an `nft` call that hangs for its
  10 s timeout, removes the table while sandboxes run. A guard back within
  two seconds is healthy again before the driver's next check, so the
  driver never stops the sandboxes that ran without the table.
- **The driver stops sandboxes once.** It stops them when a check fails
  after one that passed. A sandbox that a request was still starting at that
  moment, past its own check of readiness, starts after the stop, and no
  later check stops it.
- **The guard checks only names.** It reports the table in place when the
  set and the two chains exist, so a table emptied of its rules passes. The
  canary counts a probe that times out as blocked, which an address nobody
  answers gives without any rule.

## Decision

1. **The guard never removes the table.** It installs the table when it
   starts and reinstalls it when it disappears, as before, but leaves it in
   place when it stops, fails or times out. The table lives in the engine's
   network namespace, which goes with the engine, so removing Sibillo still
   removes it. This replaces "uninstalling Sibillo removes them" in
   ADR-0021 point 5 by that consequence of ADR-0114.
2. **A table found missing is reported missing for a while.** At start, a
   guard that finds no table while bridges of sandboxes exist in its
   namespace records it missing, as it does when the table disappears while
   it runs, so it is unhealthy for 10 seconds after installing it and the
   driver stops those sandboxes. An `nft` call that times out counts as the
   table missing: the guard records it, keeps running, and tries again.
3. **The guard compares the whole table.** When it installs the table it
   keeps what `nft` lists of it, without the set's elements. The table is in
   place only while that listing is unchanged.
4. **The canary has something to reach.** The guard listens on TCP port
   9000 of its namespace and closes every connection it accepts. The canary
   probes that port at its bridge's gateway, with and without network: it
   must be refused or time out, and any connection there means the input
   chain is not in place.
5. **The driver stops sandboxes at every failed check.** While the guard
   reports the table missing or does not answer, every check of the monitor,
   every two seconds, stops every sandbox that runs, not only the first.
6. **The driver checks again after starting a container.** Once a sandbox's
   or a workspace's container has started, before anything runs in it, the
   driver asks the guard again; when the table is not in place it removes
   the container and refuses the request with `driver.egress_rules_missing`.

## Consequences

- A guard that restarts, crashes or hangs leaves the sandboxes behind the
  table; one that finds it gone, or a driver that finds the guard silent,
  stops them.
- A sandbox starts one round trip to the guard later.
- The guard holds one more listener, in the engine's namespace only, which
  answers nothing.
- An operator who wants the table gone while the engine runs removes it by
  hand, with the engine's sandboxes stopped.

## Alternatives considered

- **An uninstall command of the guard,** as the audit suggested: nothing
  calls it, since the table goes with the engine.
- **Comparing the rules with the text the guard installs:** `nft` lists a
  table in its own form, not the one it was given.
- **Stopping only the sandboxes started after a failed check:** the driver
  would have to know when each started relative to the guard's state; stopping
  all is simpler and what SBX-015 asks.
