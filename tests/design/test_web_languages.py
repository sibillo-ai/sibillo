"""The web client's interface in every language (I18N-002, I18N-005, I18N-006, ADR-0135).

These tests read the translation resources and the app's sources. The plural
forms each language's rules name come from the platform, so the unit tests in
tests/web/unit check them.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import cast

import pytest

from tests.support.database import ROOT

WEB = ROOT / "src" / "web"
SOURCES = WEB / "src"
LOCALES = SOURCES / "locales"
LANGUAGES = LOCALES / "languages.json"
RECORDED = LOCALES / "sources.json"
# Every plural category of CLDR, as i18next names its suffixes.
PLURAL = re.compile(r"^(?P<base>.+)_(?P<form>zero|one|two|few|many|other)$")
PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*(?:,[^}]*)?\}\}")
# The app's code, without the generated API types and the resources.
CODE_SUFFIXES = (".ts", ".tsx")


def _flat(tree: dict[str, object], prefix: str = "") -> dict[str, str]:
    """Every text of a resource by its key; the items of a list, such as the quotes, by their index."""
    flat: dict[str, str] = {}
    for name, value in tree.items():
        path = f"{prefix}{name}"
        if isinstance(value, list):
            items = cast(list[object], value)
            flat |= _flat({str(index): item for index, item in enumerate(items)}, f"{path}.")
        elif isinstance(value, dict):
            flat |= _flat(cast(dict[str, object], value), f"{path}.")
        else:
            assert isinstance(value, str), f"{path} is not a text"
            flat[path] = value
    return flat


def _resource(tag: str) -> dict[str, str]:
    return _flat(json.loads((LOCALES / f"{tag}.json").read_text()))


def _languages() -> tuple[list[str], list[str]]:
    data = json.loads(LANGUAGES.read_text())
    return list(data["languages"]), list(data["reviewed"])


def _english() -> dict[str, str]:
    return _resource("en")


def _plural_bases(english: dict[str, str]) -> set[str]:
    return {match["base"] for key in english if (match := PLURAL.match(key)) and match["form"] == "other"}


def _english_of(key: str, english: dict[str, str], bases: set[str]) -> str | None:
    """The English text a key translates: its own, or every plural form of its key's."""
    if key in english and not ((match := PLURAL.match(key)) and match["base"] in bases):
        return english[key]
    match = PLURAL.match(key)
    if match is None or match["base"] not in bases:
        return None
    forms = sorted(name for name in english if (m := PLURAL.match(name)) and m["base"] == match["base"])
    return "\n".join(english[name] for name in forms)


def _source(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _code() -> list[Path]:
    return sorted(
        path
        for path in SOURCES.rglob("*")
        if path.suffix in CODE_SUFFIXES and "locales" not in path.parts and path.name != "schema.d.ts"
    )


def _translated() -> list[str]:
    languages, _ = _languages()
    return [tag for tag in languages if tag != "en"]


@pytest.mark.spec("I18N-002")
def test_every_language_of_the_list_has_a_translation() -> None:
    languages, reviewed = _languages()
    assert len(languages) == len(set(languages))
    # The list the preferred language is chosen from, which ADR-0103 made.
    assert {"en", "it", "ar", "he", "fa", "ur", "pt", "pt-BR", "zh-Hans", "zh-Hant"} <= set(languages)
    assert {"en", "it"} <= set(reviewed) <= set(languages)
    files = {path.stem for path in LOCALES.glob("*.json")} - {"languages", "sources"}
    assert files == set(languages)
    # The client reads the list from the resource, not from a copy.
    assert "locales/languages.json" in (SOURCES / "languages.ts").read_text()


@pytest.mark.spec("I18N-002")
def test_english_plural_keys_have_no_form_of_their_own() -> None:
    english = _english()
    for base in _plural_bases(english):
        assert base not in english, f"{base} has plural forms and a text of its own"
        assert f"{base}_one" in english, f"{base} has no singular"


@pytest.mark.spec("I18N-002")
def test_translations_hold_only_keys_english_has() -> None:
    english = _english()
    bases = _plural_bases(english)
    unknown = {
        tag: sorted(key for key in _resource(tag) if _english_of(key, english, bases) is None) for tag in _translated()
    }
    assert {tag: keys for tag, keys in unknown.items() if keys} == {}


@pytest.mark.spec("I18N-002")
def test_reviewed_translations_are_complete() -> None:
    english = _english()
    bases = _plural_bases(english)
    _, reviewed = _languages()
    plain = {key for key in english if not ((m := PLURAL.match(key)) and m["base"] in bases)}
    missing: dict[str, list[str]] = {}
    for tag in reviewed:
        keys = set(_resource(tag))
        lacking = sorted(plain - keys) + sorted(f"{base}_other" for base in bases if f"{base}_other" not in keys)
        if lacking:
            missing[tag] = lacking
    assert missing == {}


@pytest.mark.spec("I18N-002")
def test_no_translation_is_stale() -> None:
    english = _english()
    bases = _plural_bases(english)
    recorded: dict[str, dict[str, str]] = json.loads(RECORDED.read_text())
    assert "en" not in recorded
    problems: list[str] = []
    for tag in _translated():
        sources = recorded.get(tag, {})
        resource = _resource(tag)
        problems += [f"{tag}: {key} has no recorded source" for key in sorted(set(resource) - set(sources))]
        problems += [f"{tag}: {key} is recorded but not translated" for key in sorted(set(sources) - set(resource))]
        for key in sorted(set(resource) & set(sources)):
            text = _english_of(key, english, bases)
            if text is not None and sources[key] != _source(text):
                problems.append(f"{tag}: {key} was translated from another English text")
    assert problems == []


@pytest.mark.spec("I18N-002")
def test_translations_keep_the_placeholders_of_english() -> None:
    english = _english()
    bases = _plural_bases(english)
    problems: list[str] = []
    for tag in _translated():
        for key, text in _resource(tag).items():
            plural = PLURAL.match(key)
            if plural and plural["base"] in bases:
                wanted = set(PLACEHOLDER.findall(english[f"{plural['base']}_other"]))
                # A plural form may leave the count out, as "un file" does.
                ok = set(PLACEHOLDER.findall(text)) | {"count"} >= wanted and set(PLACEHOLDER.findall(text)) <= wanted
            elif key in english:
                ok = set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(english[key]))
            else:
                continue
            if not ok or not text.strip():
                problems.append(f"{tag}: {key}")
    assert problems == []


@pytest.mark.spec("I18N-002")
def test_a_script_translates_and_prunes() -> None:
    scripts = json.loads((WEB / "package.json").read_text())["scripts"]
    assert "translate" in scripts


# Tailwind utilities that name a physical side, and their logical twins (`ms-`, `ps-`, `start-`, `text-start` …).
# Spacing and insets need a value (`pl` alone is the Polish tag, `left` a word); borders and corners do not.
PHYSICAL_UTILITY = re.compile(
    r"^-?(?:ml|mr|pl|pr|left|right|scroll-ml|scroll-mr|scroll-pl|scroll-pr)-.+$"
    r"|^(?:border-l|border-r|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br)(?:-.+)?$"
    r"|^(?:text-left|text-right|float-left|float-right|clear-left|clear-right)$"
)
STRING = re.compile(r"\"([^\"\n]*)\"|'([^'\n]*)'|`([^`]*)`")
PHYSICAL_PROPERTY = re.compile(
    r"^\s*(?:margin|padding|border|scroll-margin|scroll-padding)-(?:left|right)[\w-]*\s*:|^\s*(?:left|right)\s*:"
    r"|text-align\s*:\s*(?:left|right)|float\s*:\s*(?:left|right)|border-(?:top|bottom)-(?:left|right)-radius",
)
STYLE_KEY = re.compile(r"\b(?:margin|padding|border)(?:Left|Right)\b")
DIRECTIONAL_ICON = re.compile(r"<(?:Chevron|Arrow|ArrowBig|Move|Corner\w*)(?:Left|Right)\b[^>]*>")


@pytest.mark.spec("I18N-005")
def test_classes_name_no_physical_side() -> None:
    found = [
        f"{path.relative_to(ROOT)}: {token}"
        for path in _code()
        for match in STRING.finditer(path.read_text())
        for token in (match.group(1) or match.group(2) or match.group(3) or "").split()
        if PHYSICAL_UTILITY.match(token.rsplit(":", 1)[-1].lstrip("!"))
    ]
    assert found == []


@pytest.mark.spec("I18N-005")
def test_styles_use_logical_properties() -> None:
    found: list[str] = []
    for path in sorted(SOURCES.rglob("*.css")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            # The safe areas of a screen are physical: a notch is on the left whatever the language.
            if PHYSICAL_PROPERTY.search(line) and "safe-area-inset" not in line:
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    found += [
        f"{path.relative_to(ROOT)}: {m.group(0)}" for path in _code() for m in STYLE_KEY.finditer(path.read_text())
    ]
    assert found == []


@pytest.mark.spec("I18N-005")
def test_icons_that_point_a_direction_mirror() -> None:
    found = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path in _code()
        for match in DIRECTIONAL_ICON.finditer(path.read_text())
        if "rtl:" not in match.group(0)
    ]
    assert found == []


# A number or a date formatted by hand, or by the platform in a default or fixed locale.
BY_HAND = re.compile(r"\.(?:toFixed|toPrecision)\(")
DEFAULT_LOCALE = re.compile(
    r"\.toLocale(?:Date|Time)?String\(\s*(?:\)|undefined|[\"'`\[])"
    r"|\bIntl\.(?:\w+)\(\s*(?:\)|undefined|[\"'`])(?!\.resolvedOptions\(\)\.timeZone)"
)
# A t() call whose options carry a count: its key must have plural forms.
COUNTED = re.compile(r"\bt\(\s*\"([\w.]+)\"\s*,\s*\{([^{}]*)\}")
# The code choosing a text by comparing a count to 1.
COMPARED_TO_ONE = re.compile(r"[!=]==?\s*[\"']?1[\"']?\s*\?\s*t\(")


@pytest.mark.spec("I18N-006")
def test_numbers_are_not_formatted_by_hand() -> None:
    found = [f"{path.relative_to(ROOT)}: {m.group(0)}" for path in _code() for m in BY_HAND.finditer(path.read_text())]
    assert found == []


@pytest.mark.spec("I18N-006")
def test_the_platform_formats_in_the_interface_language() -> None:
    found = [
        f"{path.relative_to(ROOT)}: {m.group(0)}" for path in _code() for m in DEFAULT_LOCALE.finditer(path.read_text())
    ]
    assert found == []


@pytest.mark.spec("I18N-006")
def test_counts_choose_plural_forms() -> None:
    english = _english()
    bases = _plural_bases(english)
    not_plural = sorted(
        {
            f"{path.relative_to(ROOT)}: {m.group(1)}"
            for path in _code()
            for m in COUNTED.finditer(path.read_text())
            if re.search(r"\bcount\b", m.group(2)) and m.group(1) not in bases
        }
    )
    compared = [
        f"{path.relative_to(ROOT)}: {m.group(0)}"
        for path in _code()
        for m in COMPARED_TO_ONE.finditer(path.read_text())
    ]
    assert not_plural == []
    assert compared == []
