"""Passkeys in the web client (UX-026, AUTH-010, ADR-0094).

The app is opened at `http://localhost:PORT/`, the origin its API is given,
and Chromium's virtual authenticator answers the browser's WebAuthn prompts
(test-harness.md, "Web").
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.support.accounts import Account, body, create_account
from tests.support.database import Database
from tests.support.passkeys import arrange_passkey
from tests.support.server import Server, free_port
from tests.web.conftest import accessibility_violations, sign_in

# A platform authenticator that verifies its user, as a phone's fingerprint does.
VIRTUAL_AUTHENTICATOR = {
    "protocol": "ctap2",
    "transport": "internal",
    "hasResidentKey": True,
    "hasUserVerification": True,
    "isUserVerified": True,
    "automaticPresenceSimulation": True,
}
# The next WebAuthn prompt fails, as when the user cancels it.
CANCEL_NEXT_PROMPT = """() => {
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    navigator.credentials.get = get;
    return Promise.reject(new DOMException("The user cancelled.", "NotAllowedError"));
  };
}"""


@pytest.fixture(scope="module")
def passkey_origin(server: Server, web_build: Path) -> Iterator[str]:
    """The app, served at the origin its API checks passkeys against."""
    port = free_port()
    api, _ = server.start_twin_api(
        port=port, SIBILLO_WEB_ROOT=str(web_build), SIBILLO_PUBLIC_ORIGIN=f"http://localhost:{port}"
    )
    yield f"http://localhost:{port}"
    api.close()


@pytest.fixture
def passkey_page(browser: Browser, passkey_origin: str) -> Iterator[Page]:
    context = browser.new_context(base_url=passkey_origin)
    page = context.new_page()
    page.set_default_timeout(15_000)
    devtools = context.new_cdp_session(page)
    send = cast("Callable[[str, dict[str, Any] | None], dict[str, Any]]", devtools.send)  # pyright: ignore[reportUnknownMemberType]
    send("WebAuthn.enable", None)
    send("WebAuthn.addVirtualAuthenticator", {"options": VIRTUAL_AUTHENTICATOR})
    yield page
    context.close()


def _passkey_settings(page: Page) -> None:
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Yours").get_by_role("button", name="Security").click()


def _sign_in_with_the_form(page: Page, account: Account) -> None:
    page.goto("/")
    page.get_by_label("Username").fill(account.username)
    page.get_by_label("Password").fill(account.password)
    page.get_by_role("button", name="Sign in").click()


@pytest.mark.spec("UX-026", "AUTH-010", "UX-007")
def test_a_user_adds_a_passkey_and_signs_in_with_it(passkey_page: Page, member: Account) -> None:
    page = passkey_page
    sign_in(page, member)
    _passkey_settings(page)
    passkeys = page.get_by_role("region", name="Passkeys")
    expect(passkeys).to_contain_text("No passkeys yet")
    passkeys.get_by_role("button", name="Add a passkey").click()
    dialog = page.get_by_role("dialog", name="Add a passkey")
    dialog.get_by_label("Name").fill("My phone")
    dialog.get_by_label("Password").fill(member.password)
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Add", exact=True).click()
    expect(dialog).to_be_hidden()
    listed = passkeys.get_by_role("list", name="Passkeys").get_by_role("listitem")
    expect(listed).to_have_count(1)
    expect(listed).to_contain_text("My phone")
    expect(listed).to_contain_text("Never used")
    assert accessibility_violations(page) == []

    # Signing in now asks for the passkey after the password.
    page.context.clear_cookies()
    _sign_in_with_the_form(page, member)
    expect(page.get_by_role("heading", name="Use your passkey")).to_be_visible()
    assert accessibility_violations(page) == []
    page.get_by_role("button", name="Use a passkey").click()
    page.get_by_label("Message").wait_for()
    _passkey_settings(page)
    expect(passkeys.get_by_role("listitem")).not_to_contain_text("Never used")


@pytest.mark.spec("UX-026", "AUTH-010")
def test_a_cancelled_passkey_prompt_can_be_tried_again_or_left(passkey_page: Page, member: Account) -> None:
    page = passkey_page
    sign_in(page, member)
    _passkey_settings(page)
    passkeys = page.get_by_role("region", name="Passkeys")
    passkeys.get_by_role("button", name="Add a passkey").click()
    dialog = page.get_by_role("dialog", name="Add a passkey")
    dialog.get_by_label("Name").fill("Laptop")
    dialog.get_by_label("Password").fill(member.password)
    dialog.get_by_role("button", name="Add", exact=True).click()
    expect(passkeys.get_by_role("listitem")).to_have_count(1)

    page.context.clear_cookies()
    _sign_in_with_the_form(page, member)
    page.evaluate(CANCEL_NEXT_PROMPT)
    page.get_by_role("button", name="Use a passkey").click()
    expect(page.get_by_role("alert")).to_contain_text("passkey was not used")
    # Going back leads to the password.
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_label("Password")).to_be_visible()
    # And asking again works.
    page.get_by_label("Username").fill(member.username)
    page.get_by_label("Password").fill(member.password)
    page.get_by_role("button", name="Sign in").click()
    page.evaluate(CANCEL_NEXT_PROMPT)
    page.get_by_role("button", name="Use a passkey").click()
    expect(page.get_by_role("alert")).to_contain_text("passkey was not used")
    page.get_by_role("button", name="Use a passkey").click()
    page.get_by_label("Message").wait_for()


@pytest.mark.spec("UX-026", "AUTH-010")
def test_a_user_removes_a_passkey_with_their_password(passkey_page: Page, database: Database, member: Account) -> None:
    page = passkey_page
    sign_in(page, member)
    # A passkey added after this session began, as on another device; sessions stay open (ADR-0094).
    arrange_passkey(database, member, "Old phone")
    _passkey_settings(page)
    passkeys = page.get_by_role("region", name="Passkeys")
    passkeys.get_by_role("button", name="Remove Old phone").click()
    dialog = page.get_by_role("dialog", name="Remove Old phone")
    dialog.get_by_label("Password").fill("not the password")
    dialog.get_by_role("button", name="Remove", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Wrong password")
    dialog.get_by_label("Password").fill(member.password)
    dialog.get_by_role("button", name="Remove", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(passkeys).to_contain_text("No passkeys yet")


@pytest.mark.spec("UX-026", "AUTH-010", "UX-015", "UX-007")
def test_a_household_admin_removes_the_passkeys_of_a_member(
    passkey_page: Page, server: Server, database: Database, admin: Account
) -> None:
    page = passkey_page
    member = create_account(database, admin.tenant_id)
    arrange_passkey(database, member, "Phone")
    arrange_passkey(database, member, "Laptop")
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Household").get_by_role("button", name="Members").click()
    members = page.get_by_role("region", name="Members")
    row = members.get_by_role("listitem").filter(has_text=member.username)
    expect(row).to_contain_text("2 passkeys")
    expect(row).not_to_contain_text("Laptop")
    assert accessibility_violations(page) == []
    row.get_by_role("button", name=f"Remove the passkeys of {member.username}").click()
    confirm = page.get_by_role("alertdialog")
    expect(confirm).to_contain_text("password alone")
    confirm.get_by_role("button", name="Remove passkeys").click()
    expect(row).to_contain_text("No passkeys")
    with server.client() as api:
        response = api.post(
            "/auth/login", json={"username": member.username, "password": member.password, "device_name": "x"}
        )
    assert response.status_code == 201, response.text
    assert body(response)["user"]["id"] == str(member.id)


@pytest.fixture
def unavailable_page(browser: Browser, server: Server, web_build: Path) -> Iterator[Page]:
    """The app of an instance without `SIBILLO_PUBLIC_ORIGIN`."""
    api, origin = server.start_twin_api(SIBILLO_WEB_ROOT=str(web_build), without=("SIBILLO_PUBLIC_ORIGIN",))
    context = browser.new_context(base_url=origin)
    page = context.new_page()
    page.set_default_timeout(15_000)
    yield page
    context.close()
    api.close()


@pytest.mark.spec("UX-026", "AUTH-010")
def test_without_passkeys_the_app_says_who_can_enable_them(unavailable_page: Page, member: Account) -> None:
    page = unavailable_page
    sign_in(page, member)
    _passkey_settings(page)
    passkeys = page.get_by_role("region", name="Passkeys")
    expect(passkeys).to_contain_text(re.compile("not available", re.IGNORECASE))
    expect(passkeys).to_contain_text("instance admin")
    expect(passkeys.get_by_role("button", name="Add a passkey")).to_have_count(0)
