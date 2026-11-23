# ADR-0137: CI's test parts in parallel on a developer's machine

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** @tapionx
- **Related:** REPO-011, ADR-0053, ADR-0059, ADR-0060, ADR-0114, ADR-0133

## Context

Every check of CI runs on a developer's machine before a milestone is pushed
(ADR-0060). CI splits the tests into parts, each a pytest session on a
runner of its own, all at the same time, within a budget each (ADR-0059):
about ten minutes in all. On a developer's machine the same tests ran as one
pytest session, one part after another, which took forty minutes to an hour
on a machine with 32 cores, most of them idle. Each new feature waited that
long before it could be pushed.

Test sessions already keep apart: each starts its own database, sandbox
engine, network guard and servers, under names and ports of its own
(ADR-0114). What they share is what they build: the images, which CI builds
once and hands to every part, and the web app, which every session of the
web tests built in place, in `src/web/dist`, where another session may be
serving it.

## Decision

1. **A script runs CI's checks locally, its parts in parallel.**
   `tools/run_ci_parts.py` reads the parts and their budgets from the `tests`
   job of `.github/workflows/ci.yml`, so that it never drifts from CI, and
   runs each in a pytest session of its own, as many at once as Docker's
   disk holds (each session's engine keeps about 3 GB, and 5 GB stay free),
   beside one lane with the lint, type, spec and tooling checks. It prints, for each
   part, whether it passed, how long it took and its budget, and keeps every
   log and JUnit report.
2. **Built once.** It builds the sandbox, engine and network guard images
   once, as CI does, and names them to every session with
   `TEST_SANDBOX_IMAGE`, `TEST_ENGINE_IMAGE` and `TEST_NETGUARD_IMAGE`. It
   installs, unit-tests and builds the web app once, copies the build aside,
   and names it with `TEST_WEB_BUILD`, which the web tests use as it is
   instead of building their own (specs/contracts/test-harness.md).
3. **Not the end-to-end parts.** They install a deployment and remove the
   images a local deployment runs from (ADR-0133); CI alone runs them.
4. **Time is reported, not enforced, by default.** One machine running every
   part at once is slower per part than CI's runners, so a part over its
   budget or a test over 30 seconds is listed without failing the run;
   `--strict-time` fails it. CI's budgets stay the gate (REPO-011).
5. **While working, run only the tests a change touches;** the script is for
   the moment before a push.

## Consequences

- Checking a milestone takes about as long as its slowest part plus the
  builds, instead of the sum of all parts.
- The machine needs disk and memory for every session at once, each with its
  own engine: the first run, with every part at once, filled a 144 GB disk.
  The script runs no more parts than the disk holds, and `--jobs` runs fewer
  at a time.
- The script parses the workflow's matrix itself, with the standard library
  only, as the other tools do; a change of the matrix's shape needs the
  script changed with it, which its tooling test shows.

## Alternatives considered

- **pytest-xdist:** splits one session's tests among workers, but each
  worker would start its own engine and servers anyway, the parts' budgets
  would no longer be measured, and the fixtures that start sandboxes in the
  background were not made for it.
- **Relying on CI alone:** quicker for the developer, but a push would carry
  untested work, against ADR-0060.
- **Raising nothing and waiting:** an hour per feature does not scale.
