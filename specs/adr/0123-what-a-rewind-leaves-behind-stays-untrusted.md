# ADR-0123: What a rewind leaves behind stays untrusted

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0068, ADR-0078, ADR-0083, ADR-0090, ADR-0113, AGT-003, AGT-004, AGT-034, CNV-004, CNV-005, T-08, T-24, T-33, T-36

## Context

A run has untrusted content when its path holds it (AGT-003). A rewind
deletes the runs after the kept one (CNV-004, ADR-0068), and with them the
untrusted content they held, so the next run is trusted again. But a rewind
deletes only messages and runs. What those runs did stays:

- the conversation's task list, which the planning capability gives back to
  the model as if the user wrote it (ADR-0083);
- the files of the workspace, which a rewind never changes, and which the
  next command, or `save_skill`, uses;
- the allowances answered in the deleted turns, internet access among them
  (ADR-0090, ADR-0113).

So an injected run can write a task "upload the workspace to this address",
or plant a script, and after the user rewinds past it, a trusted run follows
the task with tools that no longer ask. A fork copies the workspace of the
conversation as it is, even when it forks at a turn before the run that
wrote into it.

## Decision

1. **A conversation remembers that its leftovers are untrusted.** When a
   rewind deletes a run whose messages hold untrusted content, the
   conversation is marked: what is left of those runs, its task list and
   its workspace, may carry that content. Every later run of a marked
   conversation has untrusted content from its start, as a run given an
   untrusted memory item does (MEM-008). The mark never goes away: the
   workspace keeps what was written.
2. **Such a rewind withdraws the allowances.** It withdraws the
   conversation's internet access and the tools allowed in it, which may
   have been given at an injected run's request; the sandbox loses its
   network at once (AGT-034). A rewind that deletes only trusted runs
   changes neither.
3. **A fork inherits the mark.** A fork is marked when its conversation is,
   or when any run of its conversation, on the path to the fork's turn or
   after it, holds untrusted content, since it copies the workspace as it is
   now (CNV-005).
4. The task list and the workspace are otherwise left as ADR-0083 and
   CNV-004 say: a rewind does not change them.

This amends ADR-0068 and ADR-0083 point 5 on what a rewind leaves.

## Consequences

- An injection cannot become trusted by being rewound away, nor by being
  forked around.
- A user who rewinds past untrusted content gives internet access again,
  and sees the next request say that the conversation holds content from
  elsewhere.
- A marked conversation stays marked; a user who wants a clean one starts a
  new conversation.

## Alternatives considered

- **Restoring the task list and the workspace to the kept turn:** the
  workspace has no history to restore, and keeping one is costly.
- **Marking the workspace when a run with untrusted content writes to it:**
  every command writes something, so nearly every conversation that read a
  page would be marked, which the path already says until a rewind; marking
  at the rewind is the moment the path stops saying it.
- **Withdrawing allowances at every rewind:** asks again in conversations
  where nothing untrusted ever happened.
