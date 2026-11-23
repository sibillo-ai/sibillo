"""Tests for tools/check_pins.py (REPO-012)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.check_pins import check

from tests.tooling.marks import mark

DIGEST = "sha256:" + "a" * 64
DOCKERFILE = f"""# A build of two stages.
FROM python:3.13.9-slim-trixie@{DIGEST} AS base
RUN true

FROM base AS final
FROM sandbox-image AS sandbox
"""
COMPOSE = f"""name: sibillo
x-server: &server
  image: sibillo/server:local
  build:
    context: ..
    dockerfile: deploy/images/server/Dockerfile

services:
  api:
    <<: *server
  postgres:
    image: postgres:17.6@{DIGEST}
  engine:
    image: sibillo/engine:local
    build:
      context: ..
      additional_contexts:
        sandbox-image: service:sandbox
"""
PACKAGE = {"name": "web", "packageManager": "pnpm@12.14.0+sha512." + "b" * 128}
DEPENDABOT = """version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
  - package-ecosystem: uv
    directory: /
  - package-ecosystem: npm
    directory: /src/web
  - package-ecosystem: docker
    directories: [/deploy/images/*]
  - package-ecosystem: docker-compose
    directory: /deploy
"""


@mark.spec("REPO-012")
class CheckPinsTest(unittest.TestCase):
    def problems(
        self,
        dockerfile: str = DOCKERFILE,
        compose: str = COMPOSE,
        package: dict[str, str] | None = None,
        dependabot: str = DEPENDABOT,
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy" / "images" / "server").mkdir(parents=True)
            (root / "deploy" / "images" / "server" / "Dockerfile").write_text(dockerfile)
            (root / "deploy" / "compose.yaml").write_text(compose)
            (root / "src" / "web").mkdir(parents=True)
            (root / "src" / "web" / "package.json").write_text(json.dumps(PACKAGE if package is None else package))
            (root / ".github").mkdir()
            (root / ".github" / "dependabot.yml").write_text(dependabot)
            return check(root)

    def assertProblem(
        self,
        fragment: str,
        dockerfile: str = DOCKERFILE,
        compose: str = COMPOSE,
        package: dict[str, str] | None = None,
        dependabot: str = DEPENDABOT,
    ) -> None:
        found = self.problems(dockerfile, compose, package, dependabot)
        self.assertTrue(any(fragment in problem for problem in found), found)

    def test_pinned_files_pass(self) -> None:
        self.assertEqual(self.problems(), [])

    def test_a_base_image_by_tag_is_refused(self) -> None:
        self.assertProblem("python:3.13.9-slim-trixie", dockerfile=DOCKERFILE.replace(f"@{DIGEST}", ""))

    def test_a_platform_flag_does_not_hide_an_image(self) -> None:
        self.assertProblem("debian:13.2", dockerfile=DOCKERFILE + "FROM --platform=$BUILDPLATFORM debian:13.2\n")

    def test_an_unknown_bare_name_is_refused(self) -> None:
        # A name that is neither a stage nor a build context is an image of Docker Hub.
        self.assertProblem("alpine", dockerfile=DOCKERFILE + "FROM alpine\n")

    def test_a_pulled_image_by_tag_is_refused(self) -> None:
        self.assertProblem("postgres:17.6", compose=COMPOSE.replace(f"@{DIGEST}", ""))

    def test_built_images_need_no_digest(self) -> None:
        self.assertEqual(self.problems(compose=COMPOSE), [])

    def test_the_package_manager_carries_its_hash(self) -> None:
        self.assertProblem("packageManager", package={"name": "web", "packageManager": "pnpm@12.14.0"})

    def test_dependabot_watches_every_ecosystem(self) -> None:
        for ecosystem in ("uv", "npm", "docker"):
            with self.subTest(ecosystem=ecosystem):
                without = DEPENDABOT.replace(f"package-ecosystem: {ecosystem}\n", "package-ecosystem: other\n")
                self.assertProblem(ecosystem, dependabot=without)


if __name__ == "__main__":
    unittest.main()
