# ADR-0136: Delegating work to a fresh context

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** AGT-003, AGT-004, AGT-006, AGT-008, AGT-014, AGT-027, AGT-034, AGT-035 to AGT-038, MOD-006, TSK-004, ADR-0012, ADR-0030, ADR-0034, ADR-0037, ADR-0043, ADR-0076, ADR-0090, ADR-0097, ADR-0106, ADR-0107

## Context

A run does all its work in one context. Long work fills it: every page read,
every command's output and every file stays in the history until compaction
summarizes it (ADR-0041), and work made of independent parts, such as
comparing five products, runs one part after the other. A second opinion
from the same run is not a fresh one: it has read everything the first
opinion was made from.

Delegating a self-contained piece of work to a new run of the agent, with
a context of its own, answers all three: the pieces run at the same time,
the delegating run receives a report instead of everything that was read,
and the delegated run judges with only what its brief gives it.

ADR-0043 listed the harness's `SubAgents` as a later candidate. With
`include_self`, it runs the agent itself again on a task, and forwards the
run's `deps` unchanged. Ours are one run's own: its ID, where its messages
are stored, its cost and its compaction (ADR-0036). A second run sharing
them would write its messages into the first run's history. Its durable
delegations run inside the parent's workflow, whose steps replay in order,
so parallel delegations would interleave their steps.

A delegated run is also a new way for content to travel. What it reads
reaches the delegating run through its report, and what the delegating run
read reaches it through its brief. Neither may pass unseen (AGT-003,
ADR-0107).

## Decision

1. **A tool, `delegate`.** It takes a `brief`: the whole of what the
   delegated run is told of the work, written to stand on its own. It starts
   a **delegated run** of the agent on it, waits for it, and returns its
   **report**, the delegated run's final answer, bounded as tool results are
   (AGT-014). Several calls in one answer run at the same time. Its class is
   `reads_private_data`; it is allowed by default, and is in a tool group of
   its own, so that the user can switch it off (CNV-013, ADR-0087)
   (AGT-035).

2. **A fresh context.** A delegated run's one message is its brief. It is
   given the conversation's base instructions, the user's preferred
   language, the working instructions of its tools, the skills of the
   delegating run, and instructions that say it was delegated a piece of
   work, cannot ask the user, and ends with a complete report. It is not
   given the conversation's history, its task list, the user's memory, the
   conversation's additional instructions or the voice instructions. It
   runs on the delegating run's model, with its reasoning level.

3. **The same sandbox.** A delegated run works in its conversation's sandbox
   and workspace, beside the delegating run and the other delegated runs.
   Its instructions tell it to keep its work in a folder of its own. The
   sandbox stops with the delegating run, never with a delegated one.

4. **What it may do** (AGT-036). Its tools are the delegating run's, with
   the user's permissions and switches, without those that speak to the user
   or leave something beyond the work: `delegate` itself, so that
   delegation is one level deep; `ask_user_question` and the task list's
   tools; `offer_download`; the memory tools; `save_skill`, `propose_task`
   and `update_task`; `request_internet_access`; and the tools of remote MCP
   servers. Nobody can answer a delegated run: a call that needs approval
   is not asked. It runs only when a task grant of the delegating run covers
   it (TSK-004), and is otherwise denied, recorded as `not_granted`, and the
   model is told to say in its report what it would have needed. It has the
   conversation's internet access, read again before each call as a run
   reads it (ADR-0115), and the turn's.

5. **Provenance both ways** (AGT-037). A delegated run starts with untrusted
   content when the delegating run holds untrusted content at the call, so
   that its brief cannot carry injected instructions into a run that counts
   as clean. Its report is untrusted content when the delegated run held
   untrusted content at its end; the result says so in its metadata, as
   reading a conversation does (ADR-0107), and the delegating run counts it.
   A delegated run that ran a command or read a page therefore makes its
   delegating run untrusted, exactly as the same call would have.

6. **Its own durable workflow** (AGT-038). Each delegated run is a DBOS
   workflow of its own, whose ID is derived from the delegating run's and the
   call's. A delegating run that starts again after a crash calls its tools
   again (ADR-0034), and then waits for the same delegated run instead of
   starting another. Delegated runs wait on a queue of their own, at most four
   of one delegating run at once. A run makes at most ten delegations; a
   call beyond them is not made, and the model is told. A delegated run
   makes at most the model requests of a run (AGT-027); reaching them, or
   failing, ends it with a report that says so, and the delegating run goes
   on.

7. **Stopping.** A delegated run ends when its delegating run is no longer
   running, whether it was stopped (CNV-003), failed or ended: it watches the
   delegating run while it works, and is cancelled at once.

8. **Records.** A table, `delegations`, keeps each delegation with its
   delegating run: the call, the brief, the status, whether the delegated
   run held untrusted content, its report and its messages. It is deleted
   with its run, by a rewind or with its conversation. A fork copies the
   delegating run's messages, which hold the brief and the report, but not
   the delegations. The delegated run's model requests are recorded in the
   cost ledger with the purpose `delegation` and the delegating run's ID
   (MOD-006). Its tool calls are audited with the delegation's ID in place
   of a run's (AGT-008). Its events are not written to the delegating run's
   stream: the `delegate` call shows as any tool call does, with its brief
   and, once it ends, its report (ADR-0085).

This settles the `SubAgents` candidate of ADR-0043: we use our own
delegation on the agent itself instead.

## Consequences

- Work made of independent parts runs at the same time, and a long piece of
  work leaves the delegating run's context with only its report.
- A delegated run that reads anything from outside makes its delegating run
  untrusted, as the same reading would have: delegation saves context, not
  provenance.
- Delegated runs never ask, so work that needs approval stays with the
  delegating run, which asks as it always does. The model must be told so,
  and the instructions say it.
- A conversation can spend up to eleven runs' worth of model requests on one
  answer; the cost ledger shows it under the delegating run.
- The user sees a delegation as one tool call until it ends. Showing a
  delegated run's own activity as it happens, and its messages afterwards,
  is left for later; the messages are kept for it.

## Alternatives considered

- **The harness's `SubAgents` with `include_self`:** the least code, but it
  shares one run's `deps` between runs, and its delegations would run as
  steps of the delegating run's workflow, which replays them in order.
- **Delegated runs as runs of the conversation's tree:** they would reuse
  the storage of messages and the API of runs, but every query of the tree,
  its versions and its active path would have to leave them out.
- **Asking the user from a delegated run:** the delegating run would end
  interrupted while several delegated runs wait, each with its own
  approvals; denying is simpler and fails closed.
- **A second model judging the delegated run's calls:** rejected by
  ADR-0043, point 4.
