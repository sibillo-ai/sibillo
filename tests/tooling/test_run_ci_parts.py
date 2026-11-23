"""Tests for tools/run_ci_parts.py (REPO-011, ADR-0137)."""

from __future__ import annotations

import unittest

from tools.run_ci_parts import PART_DISK_GB, RESERVED_DISK_GB, WORKFLOW, jobs_for, parse_parts

from tests.tooling.marks import mark

MATRIX = """
jobs:
  tests:
    strategy:
      matrix:
        include:
          - part: core
            paths: >-
              tests/design tests/integration
              --ignore=tests/integration/test_runs_api.py
            # A comment between the keys.
            budget: 420
          - part: runs
            paths: tests/integration/test_runs_api.py
            budget: 240
    env:
      MAX_TEST_SECONDS: "30"
"""


@mark.spec("REPO-011")
class ParsePartsTest(unittest.TestCase):
    def test_folded_and_plain_paths_and_budgets(self) -> None:
        parts = parse_parts(MATRIX)
        self.assertEqual([part.name for part in parts], ["core", "runs"])
        self.assertEqual(
            parts[0].paths, ("tests/design", "tests/integration", "--ignore=tests/integration/test_runs_api.py")
        )
        self.assertEqual(parts[0].budget, 420)
        self.assertEqual(parts[1].paths, ("tests/integration/test_runs_api.py",))
        self.assertEqual(parts[1].budget, 240)

    def test_ci_s_own_matrix(self) -> None:
        parts = parse_parts(WORKFLOW.read_text(encoding="utf-8"))
        names = [part.name for part in parts]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("core", names)
        self.assertTrue(all(part.paths and part.budget > 0 for part in parts))
        # The parts name test paths, which the script hands to pytest.
        listed = [path for part in parts for path in part.paths if path.startswith("tests/")]
        self.assertTrue(listed)

    def test_no_matrix(self) -> None:
        with self.assertRaises(ValueError):
            parse_parts("jobs: {}\n")


@mark.spec("REPO-011")
class JobsTest(unittest.TestCase):
    def test_every_part_when_the_disk_holds_them(self) -> None:
        self.assertEqual(jobs_for(13, 500), 13)

    def test_no_more_than_the_disk_holds(self) -> None:
        self.assertEqual(jobs_for(13, RESERVED_DISK_GB + 4 * PART_DISK_GB), 4)

    def test_at_least_one(self) -> None:
        self.assertEqual(jobs_for(13, 1), 1)

    def test_what_was_asked_within_the_disk(self) -> None:
        self.assertEqual(jobs_for(13, 500, asked=3), 3)
        self.assertEqual(jobs_for(13, RESERVED_DISK_GB + 2 * PART_DISK_GB, asked=8), 2)


if __name__ == "__main__":
    unittest.main()
