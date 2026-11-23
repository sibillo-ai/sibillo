# ADR-0121: The repository's gates check what they gate, from the base branch

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0004, ADR-0060, REPO-001, REPO-002, REPO-004, REPO-005, REPO-007, REPO-009, REPO-012, T-16, T-17

## Context

ADR-0004 makes CI the gate that keeps a pull request within its type, and
ADR-0060 lets a milestone branch carry commits of several types. A security
audit of the repository found that the gate can be walked around:

- **Merge commits are not checked.** A merge in a milestone is accepted when
  its other parents are on `master`; what the merge commit itself changes is
  never looked at, so an amended merge can change `tools/`, CI or
  `AGENTS.md`. A commit without parents changes nothing as `git diff-tree`
  sees it.
- **The tools run from the pull request.** CI checks out the pull request
  and runs its own `tools/check_pr_paths.py`, which the pull request can
  change to accept anything.
- **Exemptions are self-declared.** Any branch named `dependabot/…` gets the
  paths of Dependabot's updates, and any commit whose author's name ends in
  `[bot]` skips the sign-off check.
- **The workflow check reads only part of a workflow.** It finds events only
  at two spaces of indentation, untrusted expressions only in `run:`
  scripts, and accepts `permissions: write-all` and `docker://` actions by
  tag.
- **Images are pinned by tag.** The base images of the Dockerfiles and the
  images the compose file pulls, but SearXNG's, can change under the same
  tag; so can the web app's package manager. Dependabot watches only the
  actions, so nothing proposes the updates that pins need.
- **Smaller gaps.** The tools and their tests are left out of the linter and
  the type checker; a `spec` marker counts for traceability on a skipped
  test; code owners name the sensitive areas only through `*`; a lock file
  of the sandbox image records its author's local path.

## Decision

1. **A merge brings only its parents.** In a milestone, a merge commit's
   tree must be the tree `git merge-tree --write-tree` gives for its
   parents. When the merge has conflicts, only the conflicting paths may
   differ, and none of them may be a rules path. A commit without parents
   is refused. Over the whole milestone, no rules path may change.
2. **The tools run from the base branch.** The policy job checks out the
   base branch's commit into a folder of its own and runs
   `check_pr_paths.py` and `check_dco.py` from there, against the pull
   request's commits. A pull request that changes the tools is checked by
   the tools as they were.
3. **Bots are named by GitHub, not by the branch or the commit.** The policy
   job passes the login of the pull request's author to the tools. The
   `dependabot/` type applies only to pull requests opened by
   `dependabot[bot]`, and the sign-off exemption only to commits authored as
   `dependabot[bot]` in those pull requests. Dependabot may change the
   actions' pins, the Python manifest and lock file, the web app's manifest
   and lock file, the Dockerfiles of `deploy/images/` and
   `deploy/compose.yaml`; nothing else of `deploy/`.
4. **Required checks are written down.** REPO-005 names the checks that a
   merge into `master` requires, and the repository keeps the ruleset of
   `master` in `.github/rulesets/master.json`, as GitHub exports it, so that
   a change to it is reviewed like any rule.
5. **The workflow check reads every line.** Events are found at any
   indentation under `on:`; `workflow_run` and `issue_comment` are refused
   beside `pull_request_target`; untrusted expressions are refused in every
   line, inputs of actions included; `write-all` is refused anywhere;
   `docker://` actions must be pinned by digest.
6. **Images and tools are pinned by digest** (REPO-012). Every `FROM` of a
   Dockerfile in `deploy/images/` names its image with a digest, but for a
   stage of the same file or a build context; every `image:` of
   `deploy/compose.yaml` that is pulled names a digest; the web app's
   `packageManager` carries its hash. A tool checks it in CI. Packages that
   `apt-get` installs come from the pinned image's release and are not
   pinned one by one. Dependabot watches the actions, `uv`, `npm` in
   `src/web` and the Docker images, every week.
7. **The smaller gaps close.** `tools/` and `tests/tooling/` are linted and
   type-checked like the rest. A test with a `spec` marker that is skipped
   unconditionally does not count for traceability. Code owners list
   `deploy/`, the lock files and `tests/conftest.py` by name. Lock files
   record no path of a machine. The threat model says that T-17 waits for
   OPS-007, which is still a draft.

## Consequences

- A pull request can no longer relax the gate that checks it, nor hide
  changes in a merge.
- A conflicting merge still needs review for the paths it resolves: the
  tool shows which.
- Updating a pinned image is a Dependabot pull request, or a change of a
  digest by hand.
- Dependabot's own pull requests pass only when GitHub says Dependabot
  opened them.

## Alternatives considered

- **A required review instead of CI for merges:** review is already
  required; CI should not rely on it.
- **Running the tools from a separate repository:** a second repository to
  keep in step, for what the base branch already gives.
- **zizmor or actionlint in CI:** better analysis, but a tool more to pin
  and trust; the project's own check, tightened, covers its rules, and a
  later ADR can add one.
- **Pinning every apt package:** Debian removes old versions from its
  mirrors, so builds would break; the pinned image's release bounds what
  can change.
