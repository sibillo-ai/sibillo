# ADR-0127: Memory guarded in untrusted runs, and smaller gaps of the agent's tools

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0041, ADR-0090, ADR-0095, AGT-003, AGT-004, AGT-005, AGT-007, AGT-016, MEM-004, MEM-008, T-08, T-09, T-35

## Context

ADR-0095 point 4 lets the memory tools run without approval: what they
write is guarded by provenance. But `forget` deletes an item for good, and
`update_memory` replaces its text; in a run with untrusted content, a page
can make the assistant destroy what the user wrote, and one planted
untrusted item makes every later run untrusted.

A security audit also found smaller gaps around the agent's tools:

- `stop_command` returns a command's output, but is not declared as
  ingesting untrusted content.
- A retry prompt of a tool that ingests untrusted content repeats what the
  tool saw, but does not count as untrusted content.
- The approval of a command shows the model's own description as the
  action, as if Sibillo said it.
- When the run that would deny expired approval requests cannot be made, as
  when the conversation's model is no longer offered, the sweep fails at
  every pass and the conversation stays stuck.
- The summary that compaction puts in place of the oldest history reaches
  the model as the user's words.
- A file written under injection runs in a command started earlier, such as
  a server that reloads; permissions and switches change from the next run.

## Decision

1. **Memory written by the user is guarded in untrusted runs.** In a run
   with untrusted content, `update_memory` and `forget` on an item the user
   wrote ask for approval once, with the reason `untrusted_content`, showing
   the item's text. On the assistant's own items, and in runs without
   untrusted content, they run as before. This amends ADR-0095 point 4.
2. **`stop_command` ingests untrusted content,** as `start_command` and
   `check_command` do (ADR-0090's table).
3. **A retry prompt of a tool that ingests untrusted content is untrusted
   content** (AGT-003).
4. **The approval of a command says who described it.** Its action is
   "Run a command in the sandbox", and the model's description follows as
   what the assistant says, quoted.
5. **Expired requests never leave a conversation stuck.** When the run
   that denies them cannot be made, the sweep denies them without a run:
   it records each call as expired, clears the pending request, and the
   conversation can go on once its user chooses a model.
6. **The compaction summary says what it is.** It reaches the model as a
   summary the assistant wrote of the earlier conversation, which may repeat
   content from untrusted sources, not as the user's words (AGT-016).
7. **Two residual risks are written down.** A command started before
   untrusted content arrived keeps running, and may run files written under
   injection; a change of permissions or switches applies from the next run.

## Consequences

- A page cannot make the assistant erase or rewrite what the user saved in
  memory without the user seeing it.
- Approvals of commands no longer present the model's words as Sibillo's.

## Alternatives considered

- **Keeping the old text of an item restorable:** a history of memory, with
  its own retention and privacy questions, for what one approval avoids.
- **Stopping background commands when a run becomes untrusted:** they were
  started for the user's work, and stopping them silently breaks it.
