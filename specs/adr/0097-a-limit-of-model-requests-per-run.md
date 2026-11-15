# ADR-0097: A limit of model requests per run, said as such

- **Status:** Proposed
- **Date:** 2026-11-15
- **Deciders:** @tapionx
- **Related:** ADR-0036, ADR-0052, ADR-0076, ADR-0096, AGT-022, AGT-027, MOD-017, UX-014

## Context

ADR-0036 said that per-run limits use Pydantic AI's `UsageLimits`, but no
limit was ever chosen: runs had Pydantic AI's default of 50 model requests.
A run that reached it failed as `internal.error`. The first long task a
user tried, making a skill with its own scripts, a Typst template and
previews of its pages (ADR-0096), reached it after real progress: the user
saw an internal error, and the work, in the scratch folder, was gone with
the sandbox (ADR-0076).

A limit is still needed: a model that loops would otherwise spend the
household's money and the instance's time until a person stops it. Models
the household runs locally cost no money, but still hold the worker.

## Decision

1. **A run makes at most `SIBILLO_RUN_REQUEST_LIMIT` model requests,** 200
   by default, set by the instance admin from 10 to 10,000 (AGT-027). The
   requests of the run's own work count: a title request (CNV-006) and a
   compaction (AGT-016) do not.
2. **A run that reaches it fails with `run.step_limit`,** never with
   `internal.error`, saying how many requests it made. What the run did
   until then stays in the conversation, as for any failed run (CNV-018),
   so the user can ask the assistant to go on, and the next run continues
   from there with a new allowance.
3. **Clients say that the assistant stopped after many steps,** not that
   something broke, and that the user can ask it to continue.
4. **Long work survives a stop.** The working instructions tell the agent
   to keep work in progress that takes many steps, such as a skill being
   made, in a folder of `/workspace` rather than in `/scratch`, so that a
   run that stops does not lose it; it tidies up when the work is done.
   This qualifies AGT-022's scratch folder for work longer than one answer
   might be.

## Consequences

- Long tasks have four times the room they had, and one that stops says so
  and can be continued.
- A looping model can make up to 200 requests before it stops; budgets
  over time remain MOD-004's.
- Work in progress kept in `/workspace` counts against its quota until the
  agent tidies it up (SBX-019).

## Alternatives considered

- **No limit:** a looping model runs until a person notices.
- **A limit of cost:** says nothing for local models, which cost nothing;
  budgets come with MOD-004.
- **Continuing by itself after the limit:** hides the length of the task
  from the user, which is what the limit is for.
