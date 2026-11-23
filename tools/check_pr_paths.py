"""Enforce pull request types and allowed paths (REPO-001).

Usage: python3 tools/check_pr_paths.py --branch BRANCH --base REF --head REF [--author LOGIN]

The branch prefix (the text before the first '/') is the pull request type.
Each type may change only its allowed paths. Rules files can be changed only
by 'rules' pull requests, so that a change can never relax the checks that
gate it, and 'rules' pull requests target the default branch.

A milestone pull request, from a 'milestone/' branch into the default branch,
has no type of its own: each of its commits is checked against the type that
starts its subject, such as 'impl:', and a commit without a type, of type
'rules:', or changing paths outside its type is rejected. Merges may only
bring the default branch into the milestone branch (ADR-0060), and may change
nothing but what merging their parents gives, conflicting paths aside, none
of them a rules file; a commit without parents is rejected, and so is a
milestone that changes a rules file (ADR-0121).

The 'dependabot' type holds only for pull requests that GitHub says
Dependabot opened, whose login CI passes as --author. CI runs this tool from
the base branch, never from the pull request (ADR-0121).
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys

DEFAULT_BRANCH = "master"
# The login GitHub gives Dependabot: the only author of 'dependabot/' pull requests (ADR-0121).
DEPENDABOT = "dependabot[bot]"
# A milestone branch has no type of its own; each of its commits has one,
# given by the start of its subject, such as "impl:" or "test(sandbox):".
MILESTONE = "milestone"
COMMIT_TYPE_RE = re.compile(r"^([a-z]+)(?:\([^)]*\))?!?:")
COMMIT_TYPES = ("spec", "test", "impl", "docs")

# A pattern ending with '/' matches everything below that directory;
# any other pattern matches exactly one file.
RULES_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "LICENSES/",
    "REUSE.toml",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".github/",
    ".devcontainer/",
    "tools/",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/tooling/",
)

POLICY: dict[str, tuple[str, ...]] = {
    "spec": ("specs/", "ROADMAP.md", "VISION.md"),
    "test": ("tests/", "evals/"),
    "impl": ("src/", "migrations/", "deploy/", "pyproject.toml", "uv.lock"),
    "docs": ("docs/", "README.md", "CHANGELOG.md"),
    "rules": RULES_PATHS,
    # Automated dependency updates: pinned workflow actions, manifests and lock files, and pinned images.
    "dependabot": (
        ".github/workflows/",
        "pyproject.toml",
        "uv.lock",
        "src/web/package.json",
        "src/web/package-lock.json",
        "src/web/pnpm-lock.yaml",
        "deploy/images/*/Dockerfile",
        "deploy/compose.yaml",
    ),
}


def matches(pattern: str, path: str) -> bool:
    """A pattern ending with '/' matches below that directory, one with '*' a file name of one segment there."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "*" in pattern:
        return fnmatch.fnmatchcase(path, pattern) and path.count("/") == pattern.count("/")
    return path == pattern


def matches_any(patterns: tuple[str, ...], path: str) -> bool:
    return any(matches(pattern, path) for pattern in patterns)


def pr_type(branch: str) -> str | None:
    prefix, separator, rest = branch.partition("/")
    if not separator or not rest:
        return None
    return prefix


def violations(branch: str, paths: list[str], author: str | None = None) -> list[str]:
    """Return a message for every path the branch's pull request type may not change."""
    kind = pr_type(branch)
    if kind is None or kind not in POLICY:
        allowed = ", ".join(f"{name}/" for name in (*POLICY, MILESTONE))
        return [f"branch '{branch}' must be named '<type>/<description>' with type one of: {allowed}"]
    if kind == "dependabot" and author != DEPENDABOT:
        return [f"'dependabot/' pull requests are opened by {DEPENDABOT}, not by {author or 'an unknown author'}"]

    allowed_paths = POLICY[kind]
    problems: list[str] = []
    for path in paths:
        if not matches_any(allowed_paths, path):
            problems.append(f"{path}: not allowed in a '{kind}/' pull request")
        elif kind not in ("rules", "dependabot") and matches_any(RULES_PATHS, path):
            problems.append(f"{path}: rules files can only be changed by a 'rules/' pull request")
    return problems


def target_violations(branch: str, base_branch: str) -> list[str]:
    """Return a message when the pull request targets a branch its type may not."""
    kind = pr_type(branch)
    if kind in ("rules", MILESTONE) and base_branch != DEFAULT_BRANCH:
        return [f"'{kind}/' pull requests target '{DEFAULT_BRANCH}', not '{base_branch}'"]
    return []


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def is_ancestor(commit: str, ref: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], check=False).returncode == 0


def commit_type(subject: str) -> str | None:
    match = COMMIT_TYPE_RE.match(subject)
    return None if match is None else match.group(1)


def merge_violations(sha: str, parents: list[str]) -> list[str]:
    """What a merge commit changes beyond merging its parents: paths, or a rules path it resolved (ADR-0121)."""
    commit = sha[:12]
    merged = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", *parents],
        check=False,
        capture_output=True,
        text=True,
    )
    if merged.returncode not in (0, 1):
        return [f"{commit}: its parents cannot be merged again to check it: {merged.stderr.strip()}"]
    tree, *conflicting = [line for line in merged.stdout.splitlines() if line]
    problems = [
        f"{commit}: a merge resolves a conflict in {path}, a rules file"
        for path in conflicting
        if matches_any(RULES_PATHS, path)
    ]
    changed = git("diff", "--name-only", "--no-renames", tree, sha)
    problems += [
        f"{commit}: a merge changes {path}, which merging its parents does not"
        for path in changed.splitlines()
        if path and path not in conflicting
    ]
    return problems


def milestone_violations(base: str, head: str) -> list[str]:
    """Check each commit of a milestone branch against its own type (ADR-0060, ADR-0121)."""
    problems: list[str] = []
    log = git("log", "--format=%H%x1f%P%x1f%s", f"{base}..{head}")
    for line in log.splitlines():
        sha, parents, subject = line.split("\x1f", 2)
        commit, parent_shas = sha[:12], parents.split()
        if not parent_shas:
            problems.append(f"{commit}: a commit with no parent is not allowed in a milestone")
            continue
        if len(parent_shas) > 1:
            if not all(is_ancestor(parent, base) for parent in parent_shas[1:]):
                problems.append(f"{commit}: a merge may only bring '{DEFAULT_BRANCH}' into a milestone branch")
            problems += merge_violations(sha, parent_shas)
            continue
        kind = commit_type(subject)
        if kind not in COMMIT_TYPES:
            allowed = ", ".join(f"'{name}:'" for name in COMMIT_TYPES)
            problems.append(f"{commit}: its subject must start with its type, one of {allowed}: {subject!r}")
            continue
        changed = git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", sha)
        paths = [path for path in changed.splitlines() if path]
        problems += [f"{commit} ({kind}): {problem}" for problem in violations(f"{kind}/commit", paths)]
    # Whatever the commits say, the milestone as a whole changes no rules file.
    problems += [
        f"{path}: rules files can only be changed by a 'rules/' pull request"
        for path in changed_paths(base, head)
        if matches_any(RULES_PATHS, path)
    ]
    return problems


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--branch", required=True, help="name of the pull request's head branch")
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/master")
    parser.add_argument("--head", default="HEAD", help="head ref")
    parser.add_argument("--author", default=None, help="login of the pull request's author, as GitHub gives it")
    args = parser.parse_args(argv)

    base_branch = args.base.removeprefix("origin/")
    paths = changed_paths(args.base, args.head)
    if pr_type(args.branch) == MILESTONE:
        problems = target_violations(args.branch, base_branch) + milestone_violations(args.base, args.head)
    else:
        problems = violations(args.branch, paths, args.author) + target_violations(args.branch, base_branch)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("\nSee 'Pull request types' in AGENTS.md. Split the change into separate pull requests.", file=sys.stderr)
        return 1
    print(f"Pull request policy OK ({len(paths)} file(s) changed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
