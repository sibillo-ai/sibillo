"""The household's members in the settings, their budgets and usage (UX-044, UX-045, AUTH-013, AUTH-014, MOD-004,
MOD-021, ADR-0144, ADR-0145)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, body, create_account, login
from tests.support.database import Database, uuid7
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _signs_in(server: Server, username: str, password: str) -> int:
    with server.client() as client:
        return client.post(
            "/auth/login", json={"username": username, "password": password, "device_name": "check"}
        ).status_code


def _members(page: Page) -> None:
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Household").get_by_role("button", name="Members").click()


def _spent(database: Database, account: Account, *, cost: str = "0", tokens: int = 0) -> None:
    """Usage arranged in the cost ledger: a cost on a remote model, or tokens of a local one."""
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO usage_ledger (id, tenant_id, owner_id, purpose, provider, model, input_tokens, cost, currency,"
            " price_source, created_at) VALUES (%s, %s, %s, 'run', 'test', 'test-model', %s, %s, 'USD', %s, now())",
            (uuid7(), account.tenant_id, account.id, tokens, Decimal(cost), "free" if tokens else "provider"),
        )


@pytest.mark.spec("UX-044", "AUTH-002", "AUTH-013", "AUTH-014", "UX-007")
def test_an_admin_adds_a_member_resets_their_password_and_deletes_them(
    page: Page, server: Server, admin: Account
) -> None:
    sign_in(page, admin)
    _members(page)
    members = page.get_by_role("region", name="Members")
    username, first = f"new-{uuid7()}", f"first password {uuid7()}"
    members.get_by_role("button", name="Add a member").click()
    adding = page.get_by_role("dialog", name="Add a member")
    adding.get_by_label("Username").fill(username)
    adding.get_by_label("Name", exact=True).fill("Giulia")
    adding.get_by_label("Initial password").fill(first)
    adding.get_by_role("button", name="Add", exact=True).click()
    row = members.get_by_role("listitem").filter(has_text=username)
    expect(row).to_contain_text("Giulia")
    assert _signs_in(server, username, first) == 201

    row.get_by_role("button", name=f"Manage {username}").click()
    member = page.get_by_role("region", name="Giulia")
    assert accessibility_violations(page) == []
    second = f"second password {uuid7()}"
    member.get_by_role("button", name="Give a new initial password").click()
    resetting = page.get_by_role("dialog", name="Give Giulia a new initial password")
    resetting.get_by_label("New initial password").fill(second)
    resetting.get_by_role("button", name="Set password").click()
    expect(resetting).to_be_hidden()
    assert _signs_in(server, username, first) == 401
    assert _signs_in(server, username, second) == 201

    # An enabled account is not deleted, and the page says why.
    delete = member.get_by_role("button", name="Delete account")
    expect(delete).to_be_disabled()
    expect(member).to_contain_text("Disable the account to delete it")
    member.get_by_role("button", name="Disable account").click()
    expect(member.get_by_role("button", name="Enable account")).to_be_visible()
    assert _signs_in(server, username, second) == 401
    delete.click()
    confirm = page.get_by_role("alertdialog", name="Delete Giulia?")
    expect(confirm).to_contain_text("for good")
    confirm.get_by_role("button", name="Delete account").click()
    expect(page.get_by_role("region", name="Members").get_by_role("listitem").filter(has_text=username)).to_have_count(
        0
    )
    with server.client(login(server, admin)) as client:
        listed = [user["username"] for user in body(client.get("/tenant/users"))["items"]]
    assert username not in listed


@pytest.mark.spec("UX-044")
def test_an_admin_is_offered_nothing_the_api_refuses_on_their_own_account(page: Page, admin: Account) -> None:
    sign_in(page, admin)
    _members(page)
    page.get_by_role("region", name="Members").get_by_role("button", name=f"Manage {admin.username}").click()
    own = page.get_by_role("region", name="Test user")
    expect(own.get_by_role("heading", name="Budget")).to_be_visible()
    for name in ("Disable account", "Delete account", "Give a new initial password"):
        expect(own.get_by_role("button", name=name)).to_have_count(0)
    expect(own.get_by_label("Role")).to_have_count(0)


@pytest.mark.spec("UX-045", "MOD-004", "MOD-021", "UX-007")
def test_an_admin_sets_a_members_budget_and_sees_its_share(
    page: Page, server: Server, database: Database, admin: Account
) -> None:
    member = create_account(database, admin.tenant_id)
    _spent(database, member, cost="2.5")
    sign_in(page, admin)
    _members(page)
    page.get_by_role("region", name="Members").get_by_role("button", name=f"Manage {member.username}").click()
    region = page.get_by_role("region", name="Test user")
    region.get_by_label("Cost limit (USD)").fill("5")
    region.get_by_label("Cost limit period").select_option("week")
    region.get_by_role("button", name="Save budget").click()
    expect(region.get_by_role("status")).to_contain_text("Budget saved")
    with server.client(login(server, admin)) as client:
        budget = body(client.get(f"/tenant/users/{member.id}/budget"))
    assert {key: budget["cost"][key] for key in ("amount", "currency", "period")} == {
        "amount": "5",
        "currency": "USD",
        "period": "week",
    }
    assert budget["cost"]["time_zone"]
    assert budget["tokens"] is None
    usage = region.get_by_role("group", name="Usage")
    expect(usage).to_contain_text("50% of this week's cost limit")
    expect(usage).to_contain_text("2.5")
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-045", "MOD-004")
def test_a_member_is_warned_near_their_limit_and_told_when_it_is_used_up(
    page: Page, server: Server, database: Database, member: Account
) -> None:
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO budgets (tenant_id, user_id, kind, amount, currency, period, time_zone, updated_at)"
            " VALUES (%s, %s, 'tokens', 1000, NULL, 'day', 'UTC', now())",
            (member.tenant_id, member.id),
        )
    _spent(database, member, tokens=900)
    sign_in(page, member)
    expect(page.get_by_role("status").filter(has_text="90% of today's token limit")).to_be_visible()
    _spent(database, member, tokens=100)
    page.get_by_label("Message").fill("Hello")
    page.get_by_label("Message").press("Enter")
    expect(page.get_by_role("alert").filter(has_text="used up")).to_be_visible()
    page.get_by_role("link", name="Settings").click()
    page.get_by_role("navigation", name="Settings sections").get_by_role("button", name="Usage").click()
    expect(page.get_by_role("group", name="Usage")).to_contain_text("100% of today's token limit")
