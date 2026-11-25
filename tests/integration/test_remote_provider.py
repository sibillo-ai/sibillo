"""OpenRouter, the first remote provider (MOD-001, MOD-006, ADR-0057, ADR-0069).

The model the tests serve answers as OpenRouter's documentation describes
under `/openrouter/api/v1` (tests/support/model.py); tests never reach
OpenRouter itself.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import pytest

from tests.support.accounts import Account, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.server import Server

ATTRIBUTION_HEADERS = ("http-referer", "x-title", "x-openrouter-title", "x-openrouter-categories")


@dataclass(frozen=True)
class OpenRouterModel:
    connection_id: str
    api_key: str


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def household(account: Account, default_model: HarnessModel) -> HouseholdModel:
    return default_model.connect(account.tenant_id)


@pytest.fixture
def token(server: Server, account: Account) -> str:
    return login(server, account)


@pytest.fixture
def openrouter(server: Server, household: HouseholdModel) -> OpenRouterModel:
    """An OpenRouter connection of the household, whose most used model is its default."""
    api_key = f"sk-or-v1-{secrets.token_hex(16)}"
    with server.client(household.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": household.endpoint.openrouter_url,
                "api_key": api_key,
            },
        )
        assert response.status_code == 201, response.text
        connection = body(response)
        default = {"connection_id": connection["id"], "model": "test/popular"}
        assert client.put("/tenant/default-model", json=default).status_code == 200
    return OpenRouterModel(connection["id"], api_key)


@pytest.mark.spec("MOD-001")
def test_tools_work_through_openrouter(server: Server, token: str, openrouter: OpenRouterModel) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "run:echo $((6*7))")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "Tool said:" in text_of(events)
    assert "42" in text_of(events)
