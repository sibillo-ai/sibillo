"""A run's steps in compact lines (UX-043, ADR-0140).

The model the tests serve calls the command tool with `run:<command>`, several commands in one answer with
`runs:<command> ||| …`, reasons and calls a command with `think-run:<command>`, and calls a tool by name with
`tool:<name> <arguments>` (tests/support/model.py).
"""

from __future__ import annotations

import itertools
import json
import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in

# The highest a step's line may be where the pointer is fine, with a pixel to spare.
LINE_HEIGHT = 37


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _answered(page: Page) -> None:
    expect(page.get_by_role("main")).to_contain_text("Tool said:", timeout=30_000)


@pytest.mark.spec("UX-043")
def test_reasoning_and_calls_are_one_block_of_lines(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, f"think-run:echo seen-{uuid4().hex[:6]}")
    _answered(page)
    main = page.get_by_role("main")
    summaries = main.locator("summary")
    # Reasoning, the command, reasoning about its result: three lines, one under the other, without space between.
    expect(summaries).to_have_count(3)
    boxes = [summaries.nth(index).bounding_box() for index in range(3)]
    assert all(box is not None for box in boxes)
    for box in boxes:
        assert box is not None
        assert box["height"] <= LINE_HEIGHT, box
    for upper, lower in itertools.pairwise(boxes):
        assert upper is not None
        assert lower is not None
        assert abs(lower["y"] - (upper["y"] + upper["height"])) <= 1.5, (upper, lower)
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-043")
def test_a_long_argument_never_cuts_the_label(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    command = "echo " + "-".join(f"segment{index}" for index in range(60))
    _send(page, f"tool:run_command {json.dumps({'command': command, 'description': 'Counting segments'})}")
    _answered(page)
    summary = page.locator("summary", has_text="Counting segments")
    label = summary.get_by_text(re.compile("Counting segments"))
    # The label in full: nothing of it is hidden, whatever room the argument would take.
    assert label.evaluate("(element) => element.scrollWidth <= element.clientWidth")
    expect(summary).to_contain_text("echo segment0")


@pytest.mark.spec("UX-043")
def test_an_opened_step_names_its_tool_and_how_long_it_took(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    _send(page, "run:sleep 1; echo opened-step")
    _answered(page)
    summary = page.locator("summary", has_text="Sandbox command")
    expect(summary).not_to_contain_text("run_command")
    summary.click()
    details = page.locator("details[open]")
    expect(details).to_contain_text("run_command")
    expect(details).to_contain_text("opened-step")
    expect(details).to_contain_text(re.compile(r"\d+(\.\d)?\s?s\b"))
    # Also from the history, which keeps how long it took.
    page.reload()
    page.locator("summary", has_text="Sandbox command").click()
    expect(page.locator("details[open]")).to_contain_text(re.compile(r"\d+(\.\d)?\s?s\b"), timeout=30_000)


@pytest.mark.spec("UX-043")
def test_a_long_block_folds_once_the_answer_ends(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, "runs:echo one ||| echo two ||| echo three ||| echo four ||| echo five")
    _answered(page)
    main = page.get_by_role("main")
    # One line, which says how many steps and what they were.
    fold = main.locator("summary", has_text=re.compile(r"5 steps"))
    expect(fold).to_be_visible()
    expect(fold).to_contain_text("Sandbox command")
    # The fold's line alone is in view; opened, the five steps under it.
    expect(main.locator("summary:visible", has_text="Sandbox command")).to_have_count(1)
    fold.click()
    expect(main.locator("summary:visible", has_text="Sandbox command")).to_have_count(6)
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-043")
def test_loading_the_browser_is_told_as_the_browsers(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, f"tool:load_capability {json.dumps({'id': 'browser'})}")
    _answered(page)
    main = page.get_by_role("main")
    expect(main.locator("summary", has_text="Opened the browser")).to_be_visible()
    expect(main).not_to_contain_text("Using a skill")
