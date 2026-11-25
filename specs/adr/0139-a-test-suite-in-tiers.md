# ADR-0139: A test suite in tiers, its fast tier within two minutes

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** @tapionx
- **Related:** REPO-004, REPO-011, REPO-013, ADR-0015, ADR-0024, ADR-0045, ADR-0053, ADR-0059, ADR-0067, ADR-0114, ADR-0133, ADR-0137

## Context

The suite has grown with the project: 1,777 tests outside the end-to-end
parts, on 2026-11-24. Run as CI's parts, at once, they take about ten
minutes on CI and fourteen on a developer's machine (ADR-0137); as one
session, an hour. Each new feature adds minutes, and the parts' budgets are
raised or split again and again (ADR-0059).

Most of that time is not spent checking what the tests are about. ADR-0024
made phase 0 a system exercised through its API, and later tests followed
that shape: a test of a rule starts a conversation, sends a message to a
model server over HTTP, waits for the durable worker to pick the run up,
starts a gVisor sandbox for a command, and polls the API until the run
ends. What it checks is usually one decision of the control plane: whether
a call needs approval, whether content is untrusted, what a client is shown.

Measured on the parallel run of 2026-11-24 (the time of each test's call
alone, six parts at once on one machine, so longer than on CI but in
proportion), by what a test starts:

| A test starts | Tests | Time | Per test |
|---|---|---|---|
| The whole server: API, worker, sandbox engine, model server | 670 | 1,464 s | 2.2 s |
| The sandbox driver and its engine | 112 | 445 s | 4.0 s |
| Chromium, on top of the whole server | 156 | 428 s | 2.7 s |
| Nothing | 248 | 31 s | 0.2 s |
| The database only | 591 | 20 s | 0.03 s |

Of the 670 tests of the whole server, 415 start no run: they check the API,
accounts, connections and settings, yet each session that holds them starts
a sandbox engine, which takes 20 to 30 seconds, and a worker. The other 279
start runs, and are a third of all the time: those of the agent's rules
(AGT, 151 tests, 453 s), conversations (CNV, 176 s) and tasks (TSK, 132 s).
The database tests, row-level security among them, are already fast. One
file, the sandboxes' network isolation, takes 267 s for 34 tests, waiting
for addresses that never answer.

A full run of every part on one machine, on 2026-11-25, confirms it: 1,812
tests, 2,189 s of test time in 14 sessions of 105 to 514 s each, 3,346 s in
all, because the disk held one session at a time (each keeps about 3 GB of
engine). The sessions' own start, an engine, a database and a server, is the
rest: about 55 s of a session of 200. The slowest files are the sandboxes'
isolation (213 s, 34 tests), the evals (149 s, 14 tests) and the web client
in Chromium (122 s, 43 tests). In the part of runs, five tests make a third
of the time: two wait for a crash of the worker, one for a sandbox that does
not answer (19 s).

The tests are the executable form of the requirements (REPO-004), and many
are security tests that try to break invariants. Whatever replaces a test
must catch what it caught.

## Decision

1. **Four tiers.** Every test belongs to one, by what it needs:

   | Tier | What it checks | What it needs |
   |---|---|---|
   | Unit | Decisions and transformations: tool policy, provenance, approvals' metadata, recurrences, parsing, formats, the app's own logic in Vitest | Nothing |
   | Database | Row-level security, privileges, the schema, queries and functions | Postgres, one transaction per test, rolled back |
   | Agent | Runs, tools, approvals, questions, delegation, tasks, the API's contract | The API in process (ASGI), the agent run in process on a scripted model, checked fakes of the sandbox driver and of durable execution |
   | Infrastructure | What only the real thing shows: sandbox and network isolation, the sandbox driver, durability across crashes, a few journeys in the browser, the deployment, the evals' scripted agent | Everything real |

   The first three are the **fast tier**: it MUST run within two minutes on
   one CI runner, and is what a developer runs before every commit. The
   infrastructure tier runs in CI's parts, in parallel, on every push of
   `master` and of a milestone, and before a release, within budgets of its
   own (ADR-0059, ADR-0137).

2. **Checked fakes.** Where the agent tier replaces a real component (the
   model server, the sandbox driver, the queue and workflows of durable
   execution), it uses a fake in the test process, and a **contract suite**
   runs the same scenarios against the fake and against the real component,
   in the infrastructure tier. A fake that behaves differently fails there,
   never silently. The model is Pydantic AI's `FunctionModel`, scripted as
   the model server's scripts are today (specs/contracts/test-harness.md).

3. **The database stays real.** Row-level security is the isolation
   boundary (TEN-003): no fake of Postgres. Each worker of the test run has
   its own database, made once from a template; each test runs in a
   transaction rolled back at its end, or, where the code under test
   commits, truncates what it wrote.

4. **Tests in parallel by design.** The fast tier runs with `pytest-xdist`,
   one database per worker; a test shares nothing with another but
   read-only fixtures.

5. **Waiting is a smell.** No test of the fast tier sleeps or polls: the
   in-process harness says when a run has ended. In the infrastructure tier,
   probes that wait for silence wait once, all at once, and for the shortest
   time that the guard's rules make certain.

6. **Migration, not a rewrite.** The suite moves by area, the slowest
   first: the agent's rules (AGT), tasks (TSK), conversations (CNV), the API
   tests that start no run, the browser tests whose subject is the app's
   logic, then the sandbox driver's. For each requirement, its test in the
   new tier comes first, in a `test:` commit, and the old test goes in the
   same commit, so that the traceability check (REPO-004) never sees it
   uncovered. Mutation testing of the security modules (the tool policy,
   approvals, provenance, row-level security's helpers) runs before and
   after each area moves: the score must not drop.

7. **What stays end to end.** Each security invariant that crosses a
   process or a container boundary keeps at least one test on the real
   thing: sandbox isolation, the network guard, the driver's refusal of
   what it did not start, a run that survives the worker's crash, approvals
   forged through the API, one journey per persona in the browser. Those are
   the infrastructure tier, a few dozen tests in place of hundreds.

8. **One entrypoint, the same everywhere.** `tools/run_ci_parts.py` (ADR-0137)
   runs the parts and is the only way that CI and a developer run tests;
   its parts and budgets are written once, in CI's workflow, which it reads,
   so that the two never drift. The agent tier is one of its parts,
   `agent`. The fast
   tier gives the same result on any machine with the same Postgres image; the
   infrastructure tier gives the same result and, run beside its other
   parts, a longer time, which is reported, not enforced. A tooling test
   fails a workflow that runs pytest by itself.
9. **Fewer seconds in the infrastructure tier.** Its session starts once
   per part, and shares what it can: one sandbox engine for a part, sandboxes
   kept warm between tests and cleaned, the images built once and cached by
   the hash of their inputs, and more, smaller parts (a part is as slow as its
   slowest file). A change that touches only some areas runs the parts of
   those areas; a push of `master`, of a milestone and a release run all of
   them. Each lever is measured before and after, on CI.
10. **Budgets after measuring.** The fast tier's two minutes are measured on
    CI's runner, not on a developer's machine, with a first area moved,
    before the other areas follow.
11. **What the first migration measured.** The agent tier (ADR-0141) holds
    about 1,200 tests and runs in 200 seconds on a 32-core machine, 8 workers
    at once, about 1,400 CPU seconds in all; on a runner of 4 vCPUs it is
    expected to take five or six minutes, not two. The two minutes stay the
    goal. The lever left is to shard the tier across CI jobs, each with its
    own workers, which the first measure on CI sets. The rest of the suite
    went from 56 to about 29 minutes run one part after another.

## Consequences

- A developer checks a change in under two minutes; CI checks the
  infrastructure in about as long as its slowest part. Before this, every
  feature waited an hour locally, or fourteen minutes with ADR-0137.
- The test harness gains an in-process server, a scripted model in the
  process, and fakes of the sandbox driver and of durable execution, each
  with its contract suite: work before the first area moves, and code that
  is not the product's to maintain.
- The fast tier no longer proves that the pieces connect: the
  infrastructure tier does, with fewer tests. A change that breaks only the
  connection between two pieces is caught later, on push, not before
  commit.
- The test harness contract, ADR-0024's API-only phase 0 and ADR-0045's
  pending tests are amended for the tiers; the parts of CI and their
  budgets are rearranged by `rules:` commits as areas move.
- Until the migration ends, both shapes coexist; each area's move is one
  milestone.

## Alternatives considered

- **Parallel parts only (ADR-0137):** done, and it helps, but time still
  grows with every test, and a developer still waits for infrastructure
  that most tests do not check.
- **Rewriting the suite from scratch:** faster to write, but the suite is
  the executable form of the requirements, and its security tests encode
  attacks found the hard way; a rewrite would lose some of them unseen.
- **Faster infrastructure for the same tests:** a shared sandbox engine,
  sandboxes kept between tests, shorter timeouts. Worth doing in the
  infrastructure tier, but a run through a worker and a container stays
  seconds long, and 279 such tests stay minutes.
- **Mocks without contract suites:** cheaper, but a mock that drifts from
  the component it stands for makes tests pass that should fail.
