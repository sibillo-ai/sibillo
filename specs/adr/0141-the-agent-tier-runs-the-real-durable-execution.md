# ADR-0141: The agent tier runs the real durable execution, in the test process

- **Status:** Accepted
- **Date:** 2026-11-25
- **Deciders:** @tapionx
- **Related:** API-004, AGT-009, REPO-013, ADR-0034, ADR-0050, ADR-0052, ADR-0139

## Context

ADR-0139 (point 2) has the agent tier replace durable execution with a fake
checked by a contract suite. Before building it, a spike ran the API and the
worker in threads of the test process, on the real durable execution engine,
against the same database, and the tests of `test_runs_api.py` passed
unchanged. The cost of a test that starts a run did not move: about 1.1
seconds, with or without the processes.

The cause was not the engine. The API reads a run's events with
`read_stream_async`, which polls the database once a second when no
polling interval is given, so that every wait for the next event cost up to a
second, for the tests and for a client alike. With an interval of 20
milliseconds the same tests took 0.1 to 0.9 seconds.

## Decision

1. **The API reads a run's events with a polling interval of 20
   milliseconds**, so that a client sees an event within a tenth of a second
   of the worker writing it (API-004).
2. **The agent tier runs the API and the worker in the test process**, each
   in a thread, on the real durable execution engine and the real database.
   The tests call the API over HTTP on a free port, as in the infrastructure
   tier, so that a test moves between tiers by changing its fixture, not its
   body. Durable execution is not faked: ADR-0139's fake of it, and its
   contract suite, are not built.
3. **What the agent tier replaces** is the sandbox driver, by a fake in the
   test process with its contract suite (ADR-0139, point 2), and nothing else
   of the system. The model stays the tests' own server (specs/contracts/test-harness.md).
4. **What the agent tier does not check** stays in the infrastructure tier,
   as ADR-0139 lists: a run that survives the worker's crash, the outbound
   connections of the processes, the processes' own start and logs.
5. **One worker's engine per process.** The durable execution engine is a
   singleton of its process, so each worker of a parallel run (`pytest-xdist`)
   has its own database, API and worker.

## Consequences

- No new component to maintain for durable execution; the agent tier tests
  what runs in production.
- The per-run time of a test falls from about a second to a tenth of one, and
  the start of two processes per session disappears.
- Tests that crash the worker with `SIGKILL` cannot run in the process: they
  are infrastructure tests.

## Alternatives considered

- **A fake of durable execution (ADR-0139):** more code to keep honest
  against the engine, for a gain the polling interval gives at no cost.
- **Mocking the worker's use of the engine in each test:** hides the
  integration that the tier is meant to check.
