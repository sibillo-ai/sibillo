"""Remote MCP servers in the web client (UX-029, AGT-018, AGT-028 to AGT-031, ADR-0099, ADR-0100).

The servers are the tests' own (tests/support/mcp.py). The model the tests serve calls a server's tool
when a message is `tool:<prefix>__<tool> <arguments>` (tests/support/model.py).
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.support.accounts import Account, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.mcp import McpServer, McpService
from tests.support.server import Server, free_port
from tests.web.conftest import accessibility_violations, sign_in


def _add(server: Server, token: str, mcp: McpServer, *, base_url: str | None = None) -> dict[str, Any]:
    request = {"name": f"Home {mcp.id}", "prefix": f"h{secrets.token_hex(3)}", "url": mcp.url, "auth": mcp.auth}
    with server.client(token) as client:
        if base_url is not None:
            client.base_url = base_url
        response = client.post("/tenant/mcp-servers", json=request)
    assert response.status_code == 201, response.text
    return body(response)


def _ready(server: Server, admin: Account, mcp: McpServer) -> dict[str, Any]:
    """A server of the admin's household, with every tool accepted."""
    token = login(server, admin)
    added = _add(server, token, mcp)
    with server.client(token) as client:
        if mcp.auth == "token":
            client.put(f"/mcp-servers/{added['id']}/credential", json={"token": mcp.new_token()})
            added = body(client.post(f"/tenant/mcp-servers/{added['id']}/refresh"))
        response = client.put(
            f"/tenant/mcp-servers/{added['id']}/accepted-tools",
            json={"tools": [{"name": item["name"], "digest": item["digest"]} for item in added["tools"]]},
        )
    assert response.status_code == 200, response.text
    return body(response)


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


@pytest.mark.spec("UX-029", "AGT-028", "UX-007")
def test_an_admin_adds_a_server_and_reviews_its_tools(
    page: Page, server: Server, admin: Account, mcp_service: McpService
) -> None:
    mcp = mcp_service.new()
    sign_in(page, admin)
    page.goto("/settings?section=mcp-servers")
    page.get_by_role("button", name="Add a server").click()
    dialog = page.get_by_role("dialog")
    name = f"Home {mcp.id}"
    dialog.get_by_label("Name", exact=True).fill(name)
    dialog.get_by_label("Prefix").fill(f"h{secrets.token_hex(3)}")
    dialog.get_by_label("Address").fill(mcp.url)
    dialog.get_by_label("Sign-in").select_option("none")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Add", exact=True).click()
    main = page.get_by_role("main")
    expect(main).to_contain_text(name, timeout=30_000)
    page.get_by_role("button", name=f"Review the tools of {name}").click()
    review = page.get_by_role("dialog", name=f"Tools of {name}")
    # Every field the model would read.
    expect(review).to_contain_text("Turn on")
    expect(review).to_contain_text("Turns on a light.")
    expect(review).to_contain_text('"entity"')
    review.get_by_role("checkbox", name="Accept Turn on").check()
    assert accessibility_violations(page) == []
    review.get_by_role("button", name="Save").click()
    expect(review).to_have_count(0)
    with server.client(login(server, admin)) as client:
        (added,) = [item for item in body(client.get("/tenant/mcp-servers"))["items"] if item["name"] == name]
    assert {item["name"]: item["status"] for item in added["tools"]} == {
        "turn_on": "accepted",
        "turn_off": "not_accepted",
    }
    # A tool that changes is shown as changed.
    mcp.change("turn_on", description="Turns on a light and unlocks the door.")
    page.get_by_role("button", name=f"Refresh {name}").click()
    page.get_by_role("button", name=f"Review the tools of {name}").click()
    review = page.get_by_role("dialog", name=f"Tools of {name}")
    expect(review).to_contain_text("Changed")
    expect(review).to_contain_text("unlocks the door")


@pytest.mark.spec("UX-029", "AGT-029", "AGT-030", "UX-007")
def test_a_member_connects_a_token_and_switches_the_server(
    page: Page, server: Server, database: Database, admin: Account, mcp_service: McpService
) -> None:
    mcp = mcp_service.new(auth="token")
    added = _ready(server, admin, mcp)
    member = create_account(database, admin.tenant_id)
    sign_in(page, member)
    page.goto("/settings?section=services")
    service = page.get_by_role("region", name=added["name"])
    expect(service).to_contain_text("Not connected")
    expect(service).to_contain_text("least")
    service.get_by_label("Token").fill(mcp.new_token())
    service.get_by_role("button", name="Connect").click()
    expect(service).to_contain_text("Connected", timeout=30_000)
    assert accessibility_violations(page) == []
    # The server is among the tool switches, as one group with its tools.
    page.goto("/settings?section=assistant")
    group = page.get_by_role("checkbox", name=added["name"])
    expect(group).to_be_checked()
    expect(page.get_by_role("main")).to_contain_text("Turn on")
    group.uncheck()
    expect(group).not_to_be_checked()
    token = login(server, member)
    deadline = time.monotonic() + 10
    while True:
        with server.client(token) as client:
            off = body(client.get("/me/settings"))["disabled_servers"]
        if off == [added["id"]] or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert off == [added["id"]]


@pytest.mark.spec("UX-029", "AGT-018")
def test_a_call_shows_its_server_and_host_before_it_runs(
    page: Page, server: Server, admin: Account, mcp_service: McpService
) -> None:
    mcp = mcp_service.new()
    added = _ready(server, admin, mcp)
    sign_in(page, admin)
    _send(page, f"tool:{added['prefix']}__turn_on {json.dumps({'entity': 'light.hall'})}")
    approval = page.get_by_role("region", name="Approval needed")
    expect(approval).to_be_visible(timeout=30_000)
    expect(approval).to_contain_text(added["name"])
    expect(approval).to_contain_text("127.0.0.1")
    expect(approval).to_contain_text("light.hall")
    expect(approval.get_by_role("button")).to_have_text(["Deny", "Allow once"])
    approval.get_by_role("button", name="Allow once").click()
    main = page.get_by_role("main")
    expect(main).to_contain_text("turn_on done with", timeout=30_000)
    expect(main).to_contain_text(added["name"])


@pytest.fixture
def signing_origin(server: Server, web_build: Any) -> Iterator[tuple[str, str]]:
    """An API serving the app at an origin of its own, which is also its public origin (ADR-0100).

    Its public origin, which browsers open, and the address of its API, for the tests' own requests.
    """
    port = free_port()
    origin = f"http://localhost:{port}"
    api, address = server.start_twin_api(port=port, SIBILLO_WEB_ROOT=str(web_build), SIBILLO_PUBLIC_ORIGIN=origin)
    yield origin, f"{address}/v1"
    api.close()


@pytest.mark.spec("UX-029", "AGT-031")
def test_a_member_signs_in_to_a_service_and_comes_back(
    browser: Browser,
    server: Server,
    database: Database,
    default_model: HarnessModel,
    mcp_service: McpService,
    signing_origin: tuple[str, str],
) -> None:
    origin, api = signing_origin
    admin = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    default_model.connect(admin.tenant_id)
    mcp = mcp_service.new(auth="oauth")
    added = _add(server, login(server, admin), mcp, base_url=api)
    member = create_account(database, admin.tenant_id)
    context = browser.new_context(base_url=origin)
    page = context.new_page()
    page.set_default_timeout(15_000)
    try:
        sign_in(page, member)
        page.goto("/settings?section=services")
        service = page.get_by_role("region", name=added["name"])
        expect(service).to_contain_text("Not connected")
        service.get_by_role("button", name="Sign in").click()
        # The service's sign-in page redirects at once, back to the app, which completes the sign-in.
        page.wait_for_url("**/settings?section=services**", timeout=30_000)
        expect(page.get_by_role("region", name=added["name"])).to_contain_text("Connected", timeout=30_000)
    finally:
        context.close()
    assert [request["grant_type"] for request in mcp.token_requests] == ["authorization_code"]
