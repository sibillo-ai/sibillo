"""Tests for tools/check_pr_paths.py (REPO-001)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.tooling.marks import mark
from tools.check_pr_paths import commit_type, milestone_violations, target_violations, violations


@mark.spec("REPO-001")
class PullRequestPathsTest(unittest.TestCase):
    def assertAllowed(self, branch: str, *paths: str) -> None:
        self.assertEqual(violations(branch, list(paths)), [])

    def assertRejected(self, branch: str, *paths: str) -> None:
        self.assertNotEqual(violations(branch, list(paths)), [], f"{branch} should not change {paths}")

    def test_branch_without_type_is_rejected(self) -> None:
        self.assertRejected("feature-x", "specs/glossary.md")
        self.assertRejected("spec/", "specs/glossary.md")

    def test_unknown_type_is_rejected(self) -> None:
        self.assertRejected("feature/x", "src/app.py")

    def test_spec_pull_request(self) -> None:
        self.assertAllowed("spec/sandbox-egress", "specs/requirements/sandbox.md", "specs/adr/0021-x.md", "ROADMAP.md")
        self.assertRejected("spec/sandbox-egress", "src/sandbox.py")
        self.assertRejected("spec/sandbox-egress", "tests/test_sandbox.py")

    def test_test_pull_request(self) -> None:
        self.assertAllowed("test/sandbox-egress", "tests/security/test_egress.py", "evals/injection.yaml")
        self.assertRejected("test/sandbox-egress", "src/sandbox.py")

    def test_impl_pull_request_cannot_touch_tests(self) -> None:
        self.assertAllowed("impl/sandbox-egress", "src/sibillo/sandbox.py", "migrations/0001.py", "pyproject.toml")
        self.assertRejected("impl/sandbox-egress", "src/sibillo/sandbox.py", "tests/test_sandbox.py")
        self.assertRejected("impl/sandbox-egress", "specs/requirements/sandbox.md")

    def test_docs_pull_request(self) -> None:
        self.assertAllowed("docs/install-guide", "docs/how-to/install.md", "README.md")
        self.assertRejected("docs/install-guide", "AGENTS.md")

    def test_rules_files_only_in_rules_pull_requests(self) -> None:
        for path in (
            "AGENTS.md",
            ".github/workflows/ci.yml",
            ".devcontainer/devcontainer.json",
            "tools/check_dco.py",
            "tests/tooling/test_x.py",
            "tests/conftest.py",
            "LICENSE",
        ):
            with self.subTest(path=path):
                self.assertAllowed("rules/tighten-ci", path)
                self.assertRejected("test/anything", path)
                self.assertRejected("impl/anything", path)

    def test_rules_pull_request_is_limited_to_rules(self) -> None:
        self.assertRejected("rules/tighten-ci", "src/app.py")
        self.assertRejected("rules/tighten-ci", "specs/glossary.md")

    def test_directory_prefix_does_not_match_similar_names(self) -> None:
        self.assertRejected("docs/x", "docs-old/page.md")
        self.assertRejected("impl/x", "srcx/app.py")

    def test_dependabot_may_update_workflows_manifests_and_images(self) -> None:
        bot = "dependabot[bot]"
        allowed = {
            "dependabot/github_actions/actions/checkout-7.1.0": (".github/workflows/ci.yml",),
            "dependabot/pip/pydantic-2.12": ("pyproject.toml", "uv.lock"),
            "dependabot/npm_and_yarn/src/web/react-19.3": ("src/web/package.json", "src/web/package-lock.json"),
            "dependabot/docker/deploy/python-3.13.10": ("deploy/images/server/Dockerfile", "deploy/compose.yaml"),
        }
        for branch, paths in allowed.items():
            with self.subTest(branch=branch):
                self.assertEqual(violations(branch, list(paths), author=bot), [])
        self.assertNotEqual(violations("dependabot/github_actions/x", ["tools/check_dco.py"], author=bot), [])
        # Of deploy/, only the Dockerfiles of the images and the compose file (ADR-0121).
        self.assertNotEqual(violations("dependabot/docker/x", ["deploy/.env.example"], author=bot), [])
        self.assertNotEqual(violations("dependabot/docker/x", ["deploy/images/server/entrypoint.sh"], author=bot), [])

    def test_the_dependabot_type_is_only_for_pull_requests_that_dependabot_opened(self) -> None:
        # A branch named like Dependabot's, from anyone else, gets no type at all (ADR-0121).
        for author in (None, "mallory", "dependabot"):
            with self.subTest(author=author):
                self.assertNotEqual(violations("dependabot/pip/x", ["uv.lock"], author=author), [])

    def test_empty_change_is_allowed(self) -> None:
        self.assertAllowed("spec/nothing")


@mark.spec("REPO-001")
class PullRequestTargetTest(unittest.TestCase):
    def test_rules_and_milestone_pull_requests_target_the_default_branch(self) -> None:
        for branch in ("rules/tighten-ci", "milestone/conversations"):
            with self.subTest(branch=branch):
                self.assertEqual(target_violations(branch, "master"), [])
                self.assertNotEqual(target_violations(branch, "spec/other"), [])

    def test_other_pull_requests_may_target_any_branch(self) -> None:
        for branch in ("spec/x", "test/x", "impl/x", "docs/x"):
            with self.subTest(branch=branch):
                self.assertEqual(target_violations(branch, "master"), [])


@mark.spec("REPO-001")
class CommitTypeTest(unittest.TestCase):
    def test_types_from_subjects(self) -> None:
        self.assertEqual(commit_type("impl: the gateway"), "impl")
        self.assertEqual(commit_type("test(sandbox): faster probes"), "test")
        self.assertEqual(commit_type("spec!: a breaking change"), "spec")
        self.assertIsNone(commit_type("Add the gateway"))
        self.assertIsNone(commit_type("Merge branch 'master'"))


@mark.spec("REPO-001")
class MilestonePullRequestTest(unittest.TestCase):
    """Runs the milestone check against a real temporary git repository (ADR-0060)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ada",
            "GIT_AUTHOR_EMAIL": "ada@example.org",
            "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "-q", "-b", "master")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.git("checkout", "-q", "-b", "milestone/x")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.repo,
            env=self.env,
            check=check,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def commit(self, subject: str, *paths: str, branch: str = "milestone/x") -> None:
        self.git("checkout", "-q", branch)
        for path in paths:
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(f"{subject}\n")
            self.git("add", path)
        self.git("commit", "-q", "--allow-empty", "-m", subject)

    def problems(self) -> list[str]:
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            return milestone_violations("master", "milestone/x")
        finally:
            os.chdir(cwd)

    def test_commits_of_every_type_pass(self) -> None:
        self.commit("spec: a requirement", "specs/requirements/x.md")
        self.commit("test: its tests", "tests/test_x.py")
        self.commit("impl: the code", "src/x.py", "migrations/0001.py")
        self.commit("docs: how to use it", "README.md")
        self.assertEqual(self.problems(), [])

    def test_each_commit_is_checked_against_its_own_type(self) -> None:
        self.commit("spec: a requirement", "specs/requirements/x.md")
        self.commit("impl: the code, and a test", "src/x.py", "tests/test_x.py")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("tests/test_x.py", problems[0])

    def test_a_commit_without_a_type_is_rejected(self) -> None:
        self.commit("Add the code", "src/x.py")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("must start with its type", problems[0])

    def test_rules_commits_are_rejected(self) -> None:
        self.commit("rules: relax a check", "tools/check_x.py")
        self.assertNotEqual(self.problems(), [])

    def test_the_default_branch_may_be_merged_in(self) -> None:
        self.commit("impl: the code", "src/x.py")
        self.commit("rules: reviewed on master", "tools/check_x.py", branch="master")
        self.git("checkout", "-q", "milestone/x")
        self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'master' into milestone/x", "master")
        self.assertEqual(self.problems(), [])

    def test_a_merge_that_changes_more_than_its_parents_is_rejected(self) -> None:
        self.commit("impl: the code", "src/x.py")
        self.commit("docs: on master", "README.md", branch="master")
        self.git("checkout", "-q", "milestone/x")
        self.git("merge", "-q", "--no-ff", "--no-commit", "master")
        # Amended into the merge: a change to the tools, which no parent has (ADR-0121).
        (self.repo / "tools").mkdir(exist_ok=True)
        (self.repo / "tools" / "check_x.py").write_text("accept everything\n")
        self.git("add", "tools/check_x.py")
        self.git("commit", "-q", "-m", "Merge branch 'master' into milestone/x")
        problems = self.problems()
        self.assertTrue(any("tools/check_x.py" in problem for problem in problems), problems)

    def test_a_merge_may_resolve_conflicts_outside_the_rules(self) -> None:
        self.commit("impl: the code", "src/x.py")
        self.commit("impl: on master too", "src/x.py", branch="master")
        self.git("checkout", "-q", "milestone/x")
        self.git("merge", "-q", "master", check=False)
        (self.repo / "src" / "x.py").write_text("resolved\n")
        self.git("add", "src/x.py")
        self.git("commit", "-q", "-m", "Merge branch 'master' into milestone/x")
        self.assertEqual(self.problems(), [])

    def test_a_commit_without_parents_is_rejected(self) -> None:
        self.git("checkout", "-q", "--orphan", "orphan")
        self.git("rm", "-q", "-r", "--cached", ".", check=False)
        self.commit("impl: from nowhere", "tools/check_x.py", branch="orphan")
        self.git("checkout", "-q", "milestone/x")
        self.git("merge", "-q", "--allow-unrelated-histories", "-m", "Merge branch 'master'", "orphan")
        problems = self.problems()
        self.assertTrue(any("no parent" in problem for problem in problems), problems)

    def test_other_merges_are_rejected(self) -> None:
        self.git("checkout", "-q", "-b", "side", "milestone/x")
        self.commit("impl: the code", "src/x.py", branch="side")
        self.git("checkout", "-q", "milestone/x")
        self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'side'", "side")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("a merge may only bring", problems[0])


if __name__ == "__main__":
    unittest.main()
