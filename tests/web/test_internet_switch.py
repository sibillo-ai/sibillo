"""The switch of internet access, in a conversation's top bar and on the new-chat screen (UX-042, AGT-034, ADR-0115).

The model the tests serve calls the tool named in a message `tool:<name> <arguments>`, then answers
`Tool said: <result>` (tests/support/model.py). A search needs internet access.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.support.accounts import Account, create_account, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _search(query: str) -> str:
    return f"tool:web_search {json.dumps({'query': query})}"


def _switch(page: Page) -> Locator:
    return page.get_by_role("switch", name="Internet access")


def _answered(page: Page, query: str) -> None:
    expect(page.get_by_role("main")).to_contain_text(f"Result 0 about {query}", timeout=30_000)
    expect(page.get_by_label("Message")).to_be_visible(timeout=30_000)


@pytest.mark.spec("UX-042", "AGT-034", "UX-007")
def test_the_switch_gives_internet_access_and_shows_it(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    approval = page.get_by_role("region", name="Approval needed")
    # On the new-chat screen, off, saying what it lets the assistant do.
    switch = _switch(page)
    expect(switch).to_be_visible()
    expect(switch).not_to_be_checked()
    expect(switch).to_have_attribute("title", "Lets the assistant search the web, read pages and use the internet")
    assert accessibility_violations(page) == []
    # Turned on before the first message: the search asks nothing.
    switch.click()
    expect(switch).to_be_checked()
    _send(page, _search(f"first {mark}"))
    _answered(page, f"first {mark}")
    expect(approval).to_have_count(0)
    expect(switch).to_be_checked()
    # Turned off in the conversation's top bar: the next search asks.
    switch.click()
    expect(switch).not_to_be_checked()
    _send(page, _search(f"second {mark}"))
    expect(approval).to_be_visible(timeout=30_000)
    # Allowed for the turn: on while the turn goes on, off once it has ended.
    approval.get_by_role("button", name="Allow for this turn").click()
    _answered(page, f"second {mark}")
    expect(switch).not_to_be_checked(timeout=10_000)
    # A request that waits is answered by turning the switch on, as "Allow in this chat".
    _send(page, _search(f"third {mark}"))
    expect(approval).to_be_visible(timeout=30_000)
    switch.click()
    _answered(page, f"third {mark}")
    expect(approval).to_have_count(0)
    expect(switch).to_be_checked()
    # It stays on: the next search asks nothing either.
    _send(page, _search(f"fourth {mark}"))
    _answered(page, f"fourth {mark}")
    expect(approval).to_have_count(0)


@pytest.mark.spec("UX-042")
def test_the_switch_is_in_the_top_bar_of_a_phone(page: Page, member: Account, default_model: HarnessModel) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, member)
    _send(page, "hello")
    expect(page.get_by_role("main")).to_contain_text("Echo: hello", timeout=30_000)
    switch = _switch(page)
    expect(switch).to_be_visible()
    box = switch.bounding_box()
    assert box is not None
    # At the top of the screen, within it.
    assert box["y"] < 140
    assert box["x"] + box["width"] <= 390
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-042", "AGT-002")
def test_a_user_denied_internet_access_has_no_switch(
    page: Page, server: Server, database: Database, member: Account, default_model: HarnessModel
) -> None:
    admin = login(server, create_account(database, member.tenant_id, "tenant_admin"))
    with server.client(admin) as client:
        response = client.put(
            f"/tenant/users/{member.id}/tool-permissions",
            json={"tools": {}, "classes": {"external_communication": "deny"}},
        )
    assert response.status_code == 200, response.text
    sign_in(page, member)
    expect(page.get_by_label("Message")).to_be_visible()
    expect(_switch(page)).to_have_count(0)
    _send(page, "hello")
    expect(page.get_by_role("main")).to_contain_text("Echo: hello", timeout=30_000)
    expect(_switch(page)).to_have_count(0)


@pytest.mark.parametrize("answer", ["Allow in this chat", "Allow for this turn"])
@pytest.mark.spec("UX-042", "AGT-034")
def test_the_switch_turns_on_as_soon_as_the_request_is_allowed(
    page: Page, member: Account, default_model: HarnessModel, answer: str
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    wait = json.dumps({"command": "sleep 5", "description": "Wait a little"})
    _send(page, f"chain:web_search {json.dumps({'query': f'slow {mark}'})} >>> run_command {wait}")
    approval = page.get_by_role("region", name="Approval needed")
    expect(approval).to_be_visible(timeout=30_000)
    switch = _switch(page)
    expect(switch).not_to_be_checked()
    approval.get_by_role("button", name=answer).click()
    # On at once, while the turn still goes on.
    expect(switch).to_be_checked(timeout=2_000)
    expect(page.get_by_role("button", name="Stop")).to_be_visible()
    _answered(page, f"slow {mark}")
    if answer == "Allow in this chat":
        expect(switch).to_be_checked()
    else:
        expect(switch).not_to_be_checked(timeout=10_000)
