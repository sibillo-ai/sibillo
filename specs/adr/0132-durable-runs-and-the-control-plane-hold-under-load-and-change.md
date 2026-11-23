# ADR-0132: Durable runs act as their user is now, and the control plane holds under load

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0011, ADR-0034, ADR-0052, ADR-0068, ADR-0073, ADR-0090, ADR-0096, AGT-008, AGT-017, CNV-004, CNV-005, TEN-009, T-10, T-15, T-19, T-25

## Context

A security audit of durable runs and of the control plane's robustness
found:

- **A queued run keeps the role it was queued with.** The worker takes the
  user's role and whether they are the instance admin from the run's stored
  input, which the application role can write, as it can the whole durable
  schema (T-19); a user demoted or disabled after queuing keeps their old
  rights for that run.
- **A rewind races a cancelled run.** Cancelling marks a run cancelled
  before its workflow stops, so a rewind or a deletion may go on while a
  tool of the cancelled run, `remember` or `save_skill`, still commits.
- **A fork copies a workspace inside its transaction,** holding a database
  connection for as long as the copy takes.
- **A YAML alias bomb.** A `SKILL.md` whose front matter nests aliases is
  parsed on the event loop, and its `description`, whatever it is, is
  turned into text: one upload stalls the API for every household. Imports
  may hold 20,000 files and 256 MiB, and a user may run any number at once.
- **Audit events go missing.** A call to a tool that is off or unknown, and
  an approved call to an MCP tool that changed since, leave no event.

## Decision

1. **A run acts as its user is now.** The worker reads the user's role and
   whether they are the instance admin from the database when a run starts,
   not from its input; a run of a disabled account fails at once. Workflow
   inputs and step outputs stay pickled (ADR-0034): the database is trusted
   (ADR-0011), and TEN-009 says that row-level security does not cover the
   durable schema.
2. **A rewind or deletion waits for a cancelled run to stop.** While the
   workflow of one of the conversation's runs is still pending, a rewind or
   a deletion is refused with `run.in_progress`, as for a running run.
3. **A fork copies the workspace after its transaction,** and deletes the
   new conversation when the copy fails.
4. **A skill's front matter is bounded before it is read.** Front matter
   over 16 KiB is refused unread; it is parsed off the event loop; and a
   `description` that is not text is no description. An import holds at
   most 2,000 files and 64 MiB unpacked, and a user runs one import at a
   time.
5. **Every refusal is audited.** A call to a tool that is off for the user
   or the conversation, or unknown, is recorded as `refused`, and so is an
   approved call to a remote MCP server's tool that changed since. Events
   stay keyed by run and call: a model that reuses a call's ID within a run
   adds attempts to one event, which the residual risks say.

This amends ADR-0034, ADR-0068 and ADR-0096 on these points.

## Consequences

- Demoting or disabling a user takes effect on their queued runs.
- A rewind just after a stop may be refused for the seconds the workflow
  takes to stop.

## Alternatives considered

- **A JSON serializer for DBOS:** step outputs hold library objects that
  JSON does not round-trip without code of ours for each; the database is
  trusted.
- **Waiting inside the rewind for the workflow to stop:** a request held
  open for an unknown time, for what the client retries.
