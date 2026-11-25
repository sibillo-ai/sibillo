# Development workflow

How Sibillo is built: by AI agents, under human direction, with the
specifications as the source of truth (ADR-0003) and CI as the enforcement
layer (ADR-0004). This document is the long form of [AGENTS.md](../../AGENTS.md).

## Roles

Roles can be played by humans or by AI agents, but each run of an agent plays
exactly one role, in its own context.

| Role | Reads | Writes | Notes |
|---|---|---|---|
| Maintainer (human) | everything | approves specs, critical tests, rules | Final say on meaning and scope |
| Spec author | specs, conversation with the maintainer | `specs/` | Accompanies proposals with a summary in the maintainer's language |
| Test author | specs, contracts | `tests/`, `evals/` | **Does not read the implementation** |
| Implementer | specs, contracts, tests | `src/`, `migrations/`, `deploy/` | **Never modifies tests** |
| Reviewer | the diff and the specs | review comments | Separate passes: correctness, security, simplicity |
| Red team | specs, threat model, running system | `tests/` (security) | Tries to break isolation invariants |

Using a different model for the reviewer than for the implementer reduces
correlated errors.

## Lifecycle of a feature

```
1. spec/*   requirements (+ ADR, + glossary, + contracts)   → maintainer approves
2. test/*   tests that reference the requirement IDs, failing → reviewed
3. impl/*   implementation that makes them pass               → reviewed, CI green
4. docs/*   user documentation                                → reviewed
```

Small, self-contained changes are preferred at every step. Requirement status
moves from `draft` to `accepted` in step 1 and to `implemented` once its tests
pass on `master` (in a later `spec/*` pull request).

## When the spec is not enough

If, at any step, the spec is missing, ambiguous or contradictory, the agent
**stops** and proposes a spec change instead of deciding in code or in tests.
"The spec doesn't say" is a valid and welcome outcome.

## The review loop

1. Automated reviewers comment on the pull request.
2. The author (an agent) addresses the comments and pushes fixes.
3. Steps 1–2 repeat **at most three times**. If issues remain, or if fixes
   start oscillating, the pull request is escalated to a maintainer.
4. Reviewers must flag, never accept: weakened tests, broad exception
   handling that hides failures, disabled checks, new dependencies without
   justification, and any change to isolation code.

## Tests

| Kind | Purpose | Examples |
|---|---|---|
| Unit | Logic in isolation | Redaction of logs (OBS-003) |
| Integration | Components with real dependencies (testcontainers) | Database role privileges (TEN-004) |
| End-to-end | The system through its public API or UI | Conversation lifecycle (API-003) |
| Design | Architecture rules on code and live schema | RLS forced on every table (TEN-003), layering, no blocking calls in async code |
| Security | Attempts to break invariants | Reaching the LAN from a sandbox (SBX-005), cross-tenant reads (TEN-006) |
| Eval | Agent behavior against models | Injection must not exfiltrate (EVL-003) |

Evals run against real models, by hand: see [Running the evals](evals.md).

Tests reference requirements with a marker, e.g.
`@pytest.mark.spec("SBX-005")`, which feeds the traceability check
(REPO-004).

### Running the checks before a push

While working, run the agent tier, which is most of the tests (ADR-0139,
ADR-0141): the API and the worker run in the test process, on a fake sandbox
driver, in eight workers at once, with no sandbox engine, image or browser:

```bash
python3 tools/run_ci_parts.py --parts agent --no-checks
```

It is the command CI runs for its `agent` part. The tests that need a real
sandbox, process or browser are in `tests/integration`, `tests/security`,
`tests/evals` and `tests/web`, and take the rest of the time: the whole
suite in one pytest session takes an hour.

Before pushing, run every check of CI with its test parts in parallel, as CI
runs them (ADR-0137):

```bash
python3 tools/run_ci_parts.py
```

It reads the parts and their budgets from `.github/workflows/ci.yml`,
builds the images and the web app once, runs each part in a pytest session
of its own, all at once, beside the lint, type, spec and tooling checks, and
prints a line per part. It takes about as long as the slowest part, plus the
builds. It runs as many parts at once as Docker's disk holds, about 3 GB
each with 5 GB kept free, and says so when that is fewer than all.
`--parts runs tasks` runs only those parts, `--jobs 4` fewer at a time on a
machine with less memory, and `--logs DIR` keeps the logs and
reports there. The end-to-end parts are left out: they remove the images a
local deployment runs from, and CI runs them. Times over CI's budgets are
reported but fail the run only with `--strict-time`, since one machine
running every part is slower per part than CI's runners. The web parts need
Chromium for Playwright (`uv run --locked playwright install chromium`).

Test strength is measured: mutation testing on security-critical modules,
property-based testing for parsers, policies and permission logic.

## Pull request types

See the table in [AGENTS.md](../../AGENTS.md#pull-request-types). The check is
implemented in `tools/check_pr_paths.py`. Dependency updates from Dependabot
(`dependabot/*` branches) may change dependency manifests and workflow files.

## Language

Conversations with agents may be in any language; every artifact is in
English and uses the [glossary](../../specs/glossary.md) (ADR-0005).

## Agent environment

Agents working on the project should run in a development container, not
directly on a maintainer's workstation — the same principle the project
applies to its own users' code.
