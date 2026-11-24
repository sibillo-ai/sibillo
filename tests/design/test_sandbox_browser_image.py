"""The browser of the sandbox image: one pinned release, verified, without telemetry (SBX-026, ADR-0138)."""

from __future__ import annotations

import re

import pytest

from tests.support.database import ROOT

DOCKERFILE = ROOT / "deploy" / "images" / "sandbox" / "Dockerfile"


def _text() -> str:
    return DOCKERFILE.read_text()


@pytest.mark.spec("SBX-026")
def test_the_browser_comes_from_its_official_releases_pinned_and_verified() -> None:
    text = _text()
    assert "https://github.com/lightpanda-io/browser/releases/download/" in text
    # One release, named, with the checksum of each architecture's binary.
    assert re.search(r"^ARG LIGHTPANDA_RELEASE=\d+\.\d+\.\d+$", text, re.MULTILINE)
    assert re.search(r"^ARG LIGHTPANDA_SHA256_AMD64=[0-9a-f]{64}$", text, re.MULTILINE)
    assert re.search(r"^ARG LIGHTPANDA_SHA256_ARM64=[0-9a-f]{64}$", text, re.MULTILINE)
    assert re.search(r"sha256sum (-c|--check)", text)
    # Not a moving build.
    assert "nightly" not in text.lower()


@pytest.mark.spec("SBX-026")
def test_the_image_turns_the_browsers_telemetry_off() -> None:
    assert re.search(r"^ENV LIGHTPANDA_DISABLE_TELEMETRY=true$", _text(), re.MULTILINE)


@pytest.mark.spec("SBX-026")
def test_the_image_holds_no_other_browser() -> None:
    text = _text().lower()
    assert not re.search(r"chromium|google-chrome|chrome-headless|firefox|playwright install", text)
