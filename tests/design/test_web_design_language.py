"""The web client's screens are built from design tokens and shared components (UX-037, ADR-0111)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support.database import ROOT

SOURCES = ROOT / "src" / "web" / "src"
SHARED = SOURCES / "ui"
STYLES = SOURCES / "styles.css"

# The sixteen color roles, each with a light and a dark value.
COLOR_ROLES = (
    "canvas",
    "sunken",
    "surface",
    "raised",
    "line",
    "line-strong",
    "ink",
    "ink-2",
    "ink-3",
    "hover",
    "scrim",
    "accent",
    "accent-soft",
    "ok",
    "warn",
    "danger",
)

# A native control, or one of the primitives the shared components wrap.
NATIVE_CONTROL = re.compile(r"<(button|input|textarea|select)\b")
PRIMITIVES = re.compile(r"from \"@radix-ui/")
# A utility with a value of its own, such as `text-[13.5px]`; a variant such as `aria-[current=page]:` is not one.
ARBITRARY_VALUE = re.compile(r"(?<![\w-])[a-z][\w-]*-\[[^\]\s]+\](?!:)")
# A color written out, in any notation.
COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z-])|\b(?:rgba?|hsla?|oklch)\(")
# Utilities of Tailwind's own scales that are not design tokens: sizes of text other than the six roles,
# weights other than 400, 500 and 600, radii other than the four, and its shadows.
OFF_SCALE = re.compile(
    r"(?<![\w-])(?:"
    r"text-(?:xs|sm|base|lg|xl|[2-9]xl)"
    r"|font-(?:thin|extralight|light|bold|extrabold|black)"
    r"|rounded(?:-[trblse]{1,2})?(?:-(?:xs|xl|[2-4]xl))?"
    r"|shadow(?:-(?:2xs|xs|sm|md|lg|xl|2xl|inner))?"
    r")(?![\w-])"
)
# Padding, margin and gap outside the seven steps of space: 4, 8, 12, 16, 24, 32 and 48.
OFF_GRID = re.compile(
    r"(?<![\w-])-?(?:[pm][xytblrse]?|gap(?:-[xy])?|space-[xy])-(?!(?:0|px|1|2|3|4|6|8|12|auto)(?![\w.-]))[\d.]+(?![\w-])"
)
# Only what is inside a string can be a class.
STRING = re.compile(r"\"([^\"\n]*)\"|`([^`]*)`")


def _files(*suffixes: str) -> list[Path]:
    return sorted(path for path in SOURCES.rglob("*") if path.suffix in suffixes)


def _screens() -> list[Path]:
    """The client's components that are not shared components."""
    return [path for path in _files(".tsx") if SHARED not in path.parents]


def _found(paths: list[Path], pattern: re.Pattern[str], *, in_strings: bool = False) -> list[str]:
    found: list[str] = []
    for path in paths:
        text = path.read_text()
        parts = [first or second for first, second in STRING.findall(text)] if in_strings else [text]
        found += [f"{path.relative_to(ROOT)}: {match.group(0)}" for part in parts for match in pattern.finditer(part)]
    return found


@pytest.mark.spec("UX-037")
def test_the_shared_components_exist() -> None:
    assert sorted(SHARED.glob("*.tsx")), "the web client has no shared components in src/web/src/ui"


@pytest.mark.spec("UX-037")
def test_every_color_role_has_a_light_and_a_dark_value() -> None:
    styles = STYLES.read_text()
    missing = [role for role in COLOR_ROLES if len(re.findall(rf"^\s*--{role}:", styles, re.MULTILINE)) < 2]
    assert missing == []


@pytest.mark.spec("UX-037")
def test_screens_have_no_native_controls() -> None:
    assert _screens(), "the web client's components moved"
    assert _found(_screens(), NATIVE_CONTROL) == []


@pytest.mark.spec("UX-037")
def test_screens_do_not_use_the_primitives_directly() -> None:
    assert _found(_screens(), PRIMITIVES) == []


@pytest.mark.spec("UX-037")
def test_screens_use_no_value_of_their_own() -> None:
    assert _found(_screens(), ARBITRARY_VALUE, in_strings=True) == []


@pytest.mark.spec("UX-037")
def test_screens_stay_on_the_grid_of_space() -> None:
    assert _found(_screens(), OFF_GRID, in_strings=True) == []


@pytest.mark.spec("UX-037")
def test_no_component_uses_a_scale_that_is_not_a_token() -> None:
    assert _found(_files(".tsx"), OFF_SCALE, in_strings=True) == []


@pytest.mark.spec("UX-037")
def test_colors_are_written_only_in_the_tokens() -> None:
    assert _found(_files(".ts", ".tsx"), COLOR) == []
