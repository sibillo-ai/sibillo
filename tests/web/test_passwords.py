"""Passwords in the web client: replacing an initial one, and changing one's own (AUTH-011, AUTH-012, ADR-0105)."""

from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, body, login
from tests.support.database import uuid7
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _sign_in_with_the_form(page: Page, username: str, password: str) -> None:
    page.goto("/")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()


def _created_by(server: Server, admin: Account) -> Account:
    """A member created by the admin through the API, with an initial password."""
    username, password = f"new-{uuid7()}", f"initial password {uuid7()}"
    with server.client(login(server, admin)) as client:
        created = client.post(
            "/tenant/users",
            json={"username": username, "display_name": "New member", "password": password, "role": "member"},
        )
    assert created.status_code == 201, created.text
    return Account(uuid.UUID(body(created)["id"]), admin.tenant_id, username, password, "member", False)


def _signs_in(server: Server, username: str, password: str) -> int:
    with server.client() as client:
        return client.post(
            "/auth/login", json={"username": username, "password": password, "device_name": "check"}
        ).status_code


@pytest.mark.spec("AUTH-012", "UX-007")
def test_a_new_member_chooses_their_password_before_anything_else(page: Page, server: Server, admin: Account) -> None:
    member = _created_by(server, admin)
    _sign_in_with_the_form(page, member.username, member.password)
    expect(page.get_by_role("heading", name="Choose your password")).to_be_visible()
    # Nothing of the app is shown until the password is changed.
    expect(page.get_by_label("Message")).to_have_count(0)
    assert accessibility_violations(page) == []
    new = f"my own password {uuid7()}"
    page.get_by_label("Current password").fill(member.password)
    page.get_by_label("New password", exact=True).fill(new)
    page.get_by_label("Repeat the new password").fill(new)
    page.get_by_role("button", name="Change password").click()
    page.get_by_label("Message").wait_for()
    assert _signs_in(server, member.username, member.password) == 401
    assert _signs_in(server, member.username, new) == 201


@pytest.mark.spec("AUTH-012")
def test_a_new_member_can_sign_out_instead(page: Page, server: Server, admin: Account) -> None:
    member = _created_by(server, admin)
    _sign_in_with_the_form(page, member.username, member.password)
    expect(page.get_by_role("heading", name="Choose your password")).to_be_visible()
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()


@pytest.mark.spec("AUTH-012")
def test_a_wrong_current_password_is_said(page: Page, server: Server, admin: Account) -> None:
    member = _created_by(server, admin)
    _sign_in_with_the_form(page, member.username, member.password)
    new = f"my own password {uuid7()}"
    page.get_by_label("Current password").fill("not the password")
    page.get_by_label("New password", exact=True).fill(new)
    page.get_by_label("Repeat the new password").fill(new)
    page.get_by_role("button", name="Change password").click()
    expect(page.get_by_role("alert")).to_contain_text("current password is wrong")
    expect(page.get_by_role("heading", name="Choose your password")).to_be_visible()


@pytest.mark.spec("AUTH-011", "UX-007")
def test_users_change_their_password_in_the_security_settings(page: Page, server: Server, member: Account) -> None:
    sign_in(page, member)
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Yours").get_by_role("button", name="Security").click()
    password = page.get_by_role("region", name="Password")
    new = f"my own password {uuid7()}"
    password.get_by_label("Current password").fill(member.password)
    password.get_by_label("New password", exact=True).fill(new)
    # Two different new passwords are caught before anything is sent.
    password.get_by_label("Repeat the new password").fill(f"{new} and more")
    password.get_by_role("button", name="Change password").click()
    expect(password.get_by_role("alert")).to_contain_text("do not match")
    assert _signs_in(server, member.username, member.password) == 201
    password.get_by_label("Repeat the new password").fill(new)
    assert accessibility_violations(page) == []
    password.get_by_role("button", name="Change password").click()
    expect(page.get_by_role("status")).to_contain_text("Password changed")
    # The current session stays.
    expect(password.get_by_label("Current password")).to_have_value("")
    assert _signs_in(server, member.username, member.password) == 401
    assert _signs_in(server, member.username, new) == 201
