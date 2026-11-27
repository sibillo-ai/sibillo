"""Going from one conversation to another in the list, and the titles they show there (CNV-006, CNV-015, UX-001).

The model the tests serve answers `Echo: <message>`, and `slow:N` streams N
pieces of text, half a second apart (tests/support/model.py).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.web.conftest import sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


@pytest.mark.spec("CNV-015", "UX-001")
def test_a_run_in_progress_stays_in_its_own_conversation(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    main = page.get_by_role("main")
    nav = page.get_by_role("navigation", name="Conversations")
    _send(page, f"earlier {mark}")
    expect(main).to_contain_text(f"Echo: earlier {mark}", timeout=30_000)
    earlier = urlsplit(page.url).path
    # Another chat, whose answer is still being written when the user goes back to the first one.
    page.goto("/")
    _send(page, "slow:20")
    expect(main).to_contain_text("piece 1", timeout=30_000)
    running = urlsplit(page.url).path
    nav.locator(f'a[href="{earlier}"]').click()
    expect(page).to_have_url(re.compile(f"{re.escape(earlier)}$"))
    expect(main).to_contain_text(f"Echo: earlier {mark}")
    expect(main).not_to_contain_text("piece")
    expect(main).not_to_contain_text("slow:20")
    # Back in the chat that is answered, the answer goes on where it is (CNV-015).
    nav.locator(f'a[href="{running}"]').click()
    expect(main).to_contain_text("piece 3", timeout=15_000)
    expect(main).not_to_contain_text(f"earlier {mark}")
    page.get_by_role("button", name="Stop").click()
    expect(page.get_by_role("status")).to_contain_text("Stopped.", timeout=15_000)


@pytest.mark.spec("CNV-006", "API-008", "UX-039")
def test_a_title_that_comes_after_the_answer_still_shows(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    main = page.get_by_role("main")
    nav = page.get_by_role("navigation", name="Conversations")
    # The title takes longer than the answer, which does not wait for it (ADR-0146).
    _send(page, f"slow-title:4 ||| later {mark}")
    expect(main).to_contain_text(f"Echo: later {mark}", timeout=30_000)
    expect(page.get_by_role("button", name="Send")).to_be_visible()
    here = urlsplit(page.url).path
    expect(nav.locator(f'a[href="{here}"]')).to_contain_text("New conversation")
    # The stream of changes names it once it is stored, in the list and in the top bar.
    expect(nav.locator(f'a[href="{here}"]')).to_contain_text("Write a title", timeout=15_000)
    expect(main).to_contain_text("Write a title")
