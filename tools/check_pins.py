"""Check that images and tools are pinned by digest (REPO-012, ADR-0121).

Usage: python3 tools/check_pins.py [--root PATH]

Fails when:

- a `FROM` of a Dockerfile in deploy/images/ names an image without a digest,
  unless it names a stage of the same file or a build context of the compose
  file;
- an `image:` of deploy/compose.yaml names an image without a digest, unless
  the same block builds it;
- the web app's `packageManager` carries no hash;
- Dependabot does not watch the actions, uv, npm and Docker.

Read line by line, without a YAML library, like the other tools.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE)
IMAGE = re.compile(r"^(\s*)image:\s*['\"]?([^'\"\s#]+)")
CONTEXT = re.compile(r"^\s+([\w.-]+):\s*(?:service:|docker-image://|\S)")
PACKAGE_MANAGER = re.compile(r"^[a-z]+@\d+\.\d+\.\d+\+sha(?:256|512)\.[0-9a-f]+$")
ECOSYSTEMS = ("github-actions", "uv", "npm", "docker")


def build_contexts(compose: list[str]) -> set[str]:
    """The names of the build contexts that the compose file gives its builds."""
    names: set[str] = set()
    inside: int | None = None
    for line in compose:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if inside is not None and stripped and indent <= inside:
            inside = None
        if stripped.startswith("additional_contexts:"):
            inside = indent
            continue
        if inside is not None:
            match = CONTEXT.match(line)
            if match:
                names.add(match.group(1))
    return names


def dockerfile_problems(path: Path, where: str, contexts: set[str]) -> list[str]:
    found: list[str] = []
    stages: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = FROM.match(line)
        if not match:
            continue
        image, alias = match.group(1), match.group(2)
        if not DIGEST.search(image) and image not in stages and image not in contexts:
            found.append(f"{where}:{number}: {image} is not pinned to a digest (REPO-012)")
        if alias:
            stages.add(alias)
    return found


def compose_problems(compose: list[str], where: str) -> list[str]:
    """An `image:` is pinned, or built in its own block: the lines around it at its indentation or deeper."""
    found: list[str] = []
    for index, line in enumerate(compose):
        match = IMAGE.match(line)
        if not match or DIGEST.search(match.group(2)):
            continue
        indent = len(match.group(1))
        start = index
        while start > 0 and (not compose[start - 1].strip() or _indent(compose[start - 1]) >= indent):
            start -= 1
        end = index
        while end + 1 < len(compose) and (not compose[end + 1].strip() or _indent(compose[end + 1]) >= indent):
            end += 1
        block = compose[start : end + 1]
        if not any(_indent(other) == indent and other.strip().startswith("build:") for other in block):
            found.append(f"{where}:{index + 1}: {match.group(2)} is not pinned to a digest (REPO-012)")
    return found


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def check(root: Path) -> list[str]:
    found: list[str] = []
    compose_path = root / "deploy" / "compose.yaml"
    compose = compose_path.read_text(encoding="utf-8").splitlines() if compose_path.exists() else []
    contexts = build_contexts(compose)
    for path in sorted((root / "deploy" / "images").glob("*/Dockerfile")):
        found += dockerfile_problems(path, path.relative_to(root).as_posix(), contexts)
    found += compose_problems(compose, "deploy/compose.yaml")
    package = root / "src" / "web" / "package.json"
    if package.exists():
        manager = json.loads(package.read_text(encoding="utf-8")).get("packageManager", "")
        if not PACKAGE_MANAGER.match(str(manager)):
            found.append(f"src/web/package.json: packageManager {manager!r} carries no hash (REPO-012)")
    dependabot = root / ".github" / "dependabot.yml"
    watched = (
        set(re.findall(r"package-ecosystem:\s*['\"]?([\w-]+)", dependabot.read_text(encoding="utf-8")))
        if (dependabot.exists())
        else set[str]()
    )
    found += [
        f".github/dependabot.yml: Dependabot does not watch {ecosystem} (REPO-012)"
        for ecosystem in ECOSYSTEMS
        if ecosystem not in watched
    ]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    found = check(args.root.resolve())
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if found:
        return 1
    print("Pins OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
