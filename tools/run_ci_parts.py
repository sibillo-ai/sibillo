"""Run every check of CI on this machine, the test parts in parallel (REPO-011, ADR-0059, ADR-0137).

Usage: python3 tools/run_ci_parts.py [--parts NAME ...] [--jobs N] [--strict-time] [--logs DIR]

CI runs its test parts on runners of their own, at the same time; one pytest
session for the whole suite runs them one after another. This script reads
the parts from `.github/workflows/ci.yml`, builds the images and the web app
once, as CI does, hands them to every part (`TEST_SANDBOX_IMAGE`,
`TEST_ENGINE_IMAGE`, `TEST_NETGUARD_IMAGE`, `TEST_WEB_BUILD`), and runs the
parts in parallel, each in a pytest session of its own, beside a lane of the
lint, type, spec and tooling checks. Each session starts its own database,
sandbox engine, network guard and servers, under names and ports of its own
(specs/contracts/test-harness.md).

The end-to-end parts are left out: they install a deployment, and remove the
images a local deployment runs from. CI runs them.

Times on one machine running every part at once are longer than on CI's
runners, so a part over its budget, or a test over the limit, is reported
without failing, unless `--strict-time` is given. A failing test or check
always fails the run.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
WEB = ROOT / "src" / "web"
MAX_TEST_SECONDS = 30
# What one part's session keeps on Docker's disk at most, its engine holding the sandbox image, and what is
# left free whatever runs (ADR-0137).
PART_DISK_GB = 3
RESERVED_DISK_GB = 5
BUILD_TIMEOUT_SECONDS = 1800
# Parts that install a deployment: never on a developer's machine (ADR-0133).
END_TO_END = "tests/e2e"
# The checks of CI's lint and tooling jobs, in the order CI runs them.
CHECKS: tuple[tuple[str, ...], ...] = (
    ("python3", "tools/check_specs.py"),
    ("python3", "-m", "unittest", "discover", "-s", "tests/tooling", "-t", "."),
    ("python3", "tools/check_workflows.py"),
    ("python3", "tools/check_pins.py"),
    ("python3", "tools/check_traceability.py"),
    ("uv", "run", "--locked", "ruff", "format", "--check"),
    ("uv", "run", "--locked", "ruff", "check"),
    ("uv", "run", "--locked", "pyright"),
)


@dataclass(frozen=True)
class Part:
    name: str
    paths: tuple[str, ...]
    budget: int


@dataclass
class Outcome:
    name: str
    passed: bool
    seconds: float
    log: Path
    note: str = ""
    timing: list[str] = field(default_factory=list[str])


def _value(text: str) -> str:
    return text.split(" #", 1)[0].strip().strip('"')


def parse_parts(workflow: str) -> list[Part]:
    """The test parts of the `tests` job's matrix, as `part`, `paths` (a folded block or one line) and `budget`."""
    lines = workflow.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == "include:")
    except StopIteration:
        raise ValueError("the workflow has no matrix of parts") from None
    entries: list[dict[str, str]] = []
    index = start + 1
    item_indent: int | None = None
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if item_indent is None:
            item_indent = indent
        if indent < item_indent:
            break
        if stripped.startswith("- "):
            entries.append({})
            stripped = stripped[2:]
            indent += 2
        key, _, rest = stripped.partition(":")
        rest = rest.strip()
        if rest in (">-", ">", "|", "|-"):
            block: list[str] = []
            index += 1
            while index < len(lines):
                inner = lines[index]
                if inner.strip() and len(inner) - len(inner.lstrip()) <= indent:
                    break
                block.append(inner.strip())
                index += 1
            entries[-1][key.strip()] = " ".join(part for part in block if part)
            continue
        entries[-1][key.strip()] = _value(rest)
        index += 1
    return [Part(entry["part"], tuple(entry["paths"].split()), int(entry["budget"])) for entry in entries]


def _run(
    command: tuple[str, ...] | list[str], log: Path, environment: dict[str, str] | None = None
) -> tuple[bool, float]:
    started = time.monotonic()
    with log.open("ab") as output:
        output.write(f"$ {' '.join(command)}\n".encode())
        output.flush()
        result = subprocess.run(
            list(command), cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, env=environment, check=False
        )
    return result.returncode == 0, time.monotonic() - started


def _build_images(suffix: str, log: Path) -> dict[str, str]:
    """The sandbox, engine and network guard images, built once, as CI builds them (ADR-0059, ADR-0114)."""
    images = {name: f"sibillo-test/{name}:parts-{suffix}" for name in ("sandbox", "engine", "netguard")}
    for name in ("sandbox", "netguard", "engine"):
        options = (
            ["--builder", "default", "--build-context", f"sandbox-image=docker-image://{images['sandbox']}"]
            if name == "engine"
            else []
        )
        command = [
            "docker", "build", "--quiet", "--tag", images[name],
            "--file", str(ROOT / "deploy" / "images" / name / "Dockerfile"), *options, str(ROOT),
        ]  # fmt: skip
        passed, _ = _run(command, log)
        if not passed:
            raise RuntimeError(f"the {name} image did not build; see {log}")
    return images


def _build_web(directory: Path, log: Path) -> Path:
    """The web app, installed from its lock file, unit-tested and built, then copied aside for every part."""
    corepack = shutil.which("corepack")
    if corepack is None:
        raise RuntimeError("the web parts need Node.js with corepack")
    environment = os.environ | {"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    for args in (("install", "--frozen-lockfile"), ("test",), ("build",)):
        started = time.monotonic()
        with log.open("ab") as output:
            result = subprocess.run(
                [corepack, "pnpm", *args],
                cwd=WEB,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError(f"pnpm {' '.join(args)} failed after {time.monotonic() - started:.0f} s; see {log}")
    built = directory / "web"
    shutil.copytree(WEB / "dist", built)
    return built


def _docker_free_gb() -> float:
    """Free space where Docker keeps its data, which the sessions' engines fill."""
    found = subprocess.run(
        ["docker", "info", "--format", "{{.DockerRootDir}}"], capture_output=True, text=True, check=False
    )
    root = Path(found.stdout.strip() or "/")
    try:
        return shutil.disk_usage(root).free / 1024**3
    except OSError:
        return shutil.disk_usage("/").free / 1024**3


def jobs_for(parts: int, free_gb: float, asked: int = 0) -> int:
    """How many parts run at once: as many as asked, or all, within what the disk holds, and at least one."""
    fits = max(1, int((free_gb - RESERVED_DISK_GB) // PART_DISK_GB))
    return max(1, min(asked or parts, parts, fits))


def _run_part(part: Part, logs: Path, environment: dict[str, str]) -> Outcome:
    paths = [path for path in part.paths if not path.startswith("tests/") or (ROOT / path.split("::")[0]).exists()]
    log, report = logs / f"{part.name}.log", logs / f"{part.name}.xml"
    command = [
        "uv", "run", "--locked", "pytest", *paths, "-p", "no:cacheprovider",
        f"--junitxml={report}", "-o", "junit_duration_report=call",
    ]  # fmt: skip
    passed, seconds = _run(command, log, environment)
    timing: list[str] = []
    if report.exists():
        durations = subprocess.run(
            [
                sys.executable,
                "tools/check_test_durations.py",
                "--junit",
                str(report),
                "--max-test-seconds",
                str(MAX_TEST_SECONDS),
                "--max-session-seconds",
                str(part.budget),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if durations.returncode != 0:
            timing = [line for line in durations.stdout.splitlines() if line.strip()][:3]
    tail = log.read_text(errors="replace").strip().splitlines()[-1:] if log.exists() else []
    return Outcome(part.name, passed, seconds, log, tail[0] if tail else "", timing)


def _run_checks(logs: Path) -> Outcome:
    log = logs / "checks.log"
    started = time.monotonic()
    failed = [" ".join(command) for command in CHECKS if not _run(command, log)[0]]
    note = "all passed" if not failed else "failed: " + "; ".join(failed)
    return Outcome("checks", not failed, time.monotonic() - started, log, note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", nargs="*", help="only these parts, by name (default: every part but end-to-end)")
    parser.add_argument(
        "--jobs", type=int, default=0, help="parts at once (default: all of them, as many as Docker's disk holds)"
    )
    parser.add_argument("--strict-time", action="store_true", help="fail on a part over its budget or a slow test")
    parser.add_argument("--no-checks", action="store_true", help="only the test parts")
    parser.add_argument("--logs", type=Path, help="where to keep logs and reports (default: a new temporary folder)")
    args = parser.parse_args(argv)

    parts = parse_parts(WORKFLOW.read_text(encoding="utf-8"))
    names = {part.name for part in parts}
    unknown = sorted(set(args.parts or ()) - names)
    if unknown:
        parser.error(f"no such part: {', '.join(unknown)}; the parts are {', '.join(sorted(names))}")
    left_out = [part.name for part in parts if all(path.startswith(END_TO_END) for path in part.paths)]
    chosen = [part for part in parts if part.name not in left_out and (not args.parts or part.name in args.parts)]
    logs = args.logs or Path(tempfile.mkdtemp(prefix="sibillo-ci-parts-"))
    logs.mkdir(parents=True, exist_ok=True)
    print(f"Logs and reports: {logs}")
    if left_out:
        print(f"Left out, as CI alone runs them: {', '.join(left_out)}")

    suffix = secrets.token_hex(4)
    started = time.monotonic()
    images: dict[str, str] = {}
    try:
        print("Building the images and the web app, once for every part …", flush=True)
        environment = dict(os.environ)
        needs_web = any(name.startswith("web") for name in (part.name for part in chosen))
        with ThreadPoolExecutor(max_workers=2) as pool:
            building = pool.submit(_build_images, suffix, logs / "build.log")
            web = pool.submit(_build_web, logs, logs / "web-build.log") if needs_web else None
            images = building.result()
            if web is not None:
                environment["TEST_WEB_BUILD"] = str(web.result())
        environment |= {
            "TEST_SANDBOX_IMAGE": images["sandbox"],
            "TEST_ENGINE_IMAGE": images["engine"],
            "TEST_NETGUARD_IMAGE": images["netguard"],
        }
        print(f"Built in {time.monotonic() - started:.0f} s; running {len(chosen)} parts …", flush=True)
        free = _docker_free_gb()
        jobs = jobs_for(len(chosen), free, args.jobs)
        if jobs < (args.jobs or len(chosen)):
            print(f"{free:.0f} GB free for Docker: {jobs} parts at a time, about {PART_DISK_GB} GB each.", flush=True)
        if free < RESERVED_DISK_GB + PART_DISK_GB:
            raise RuntimeError(f"only {free:.0f} GB free for Docker: one part needs about {PART_DISK_GB} GB more")
        # The checks run beside the parts, in a lane of their own.
        with ThreadPoolExecutor(max_workers=1) as lane, ThreadPoolExecutor(max_workers=jobs) as pool:
            checks = None if args.no_checks else lane.submit(_run_checks, logs)
            futures = [pool.submit(_run_part, part, logs, environment) for part in chosen]
            outcomes = [future.result() for future in futures]
            if checks is not None:
                outcomes.append(checks.result())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if images:
            subprocess.run(["docker", "image", "rm", *images.values()], capture_output=True, check=False)

    budgets = {part.name: part.budget for part in chosen}
    failed = False
    print()
    print(f"{'part':<14} {'result':<8} {'seconds':>8} {'budget':>7}  summary")
    for outcome in outcomes:
        budget = budgets.get(outcome.name)
        slow = bool(outcome.timing)
        failed = failed or not outcome.passed or (args.strict_time and slow)
        result = "passed" if outcome.passed else "FAILED"
        print(f"{outcome.name:<14} {result:<8} {outcome.seconds:>8.0f} {budget or '':>7}  {outcome.note}")
        for line in outcome.timing:
            print(f"{'':<14} {'time':<8} {'':>8} {'':>7}  {line.strip()}")
    print(f"\nEverything took {time.monotonic() - started:.0f} s.")
    if any(outcome.timing for outcome in outcomes) and not args.strict_time:
        print("Times over CI's limits are reported only: this machine ran every part at once.")
    if failed:
        print(f"Failed: see the logs in {logs}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
