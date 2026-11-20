"""Ollama servers, and prompts a server cut to fit its window (MOD-018, MOD-019, ADR-0093).

The model the tests serve answers as an Ollama server under `/ollama`, with
every model it has answered with loaded with a 4096-token window, and
reports the prompt tokens a test asks for with `prompt-tokens:N`
(tests/support/model.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from tests.support.accounts import Account, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import OLLAMA_CONTEXT_LENGTH, OLLAMA_VERSION
from tests.support.runs import Event, create_conversation, messages, start_run, wait_for_run
from tests.support.server import Server

# The window of a connection to your own server unless set (ADR-0073).
DEFAULT_CONTEXT_WINDOW = 8192
# The window an admin gives the Ollama connection, larger than the one the server runs with.
CONNECTION_WINDOW = 32768


@dataclass(frozen=True)
class Household:
    member: Account
    token: str
    model: HouseholdModel
    ollama_id: str


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> Household:
    member = create_account(database, create_tenant(database))
    model = default_model.connect(member.tenant_id)
    with server.client(model.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "Ollama",
                "kind": "openai",
                "base_url": model.endpoint.ollama_url,
                "location": "local",
                "context_window": CONNECTION_WINDOW,
            },
        )
    assert response.status_code == 201, response.text
    return Household(member, login(server, member), model, body(response)["id"])


def _on_ollama(server: Server, household: Household, model: str = "test-model") -> str:
    """A conversation of the member on a model of the Ollama connection."""
    conversation = create_conversation(server, household.token)["id"]
    with server.client(household.token) as client:
        response = client.patch(
            f"/conversations/{conversation}", json={"model": {"connection_id": household.ollama_id, "model": model}}
        )
    assert response.status_code == 200, response.text
    return conversation


def _option(server: Server, token: str, connection_id: str, model: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/models")
    assert response.status_code == 200, response.text
    (option,) = [
        item for item in body(response)["items"] if item["connection_id"] == connection_id and item["model"] == model
    ]
    return option


def _usage(events: list[Event]) -> list[dict[str, Any]]:
    return [
        event.data["value"] for event in events if event.type == "CUSTOM" and event.data.get("name") == "sibillo.usage"
    ]


def _connection(server: Server, token: str, connection_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/tenant/connections")
    assert response.status_code == 200, response.text
    (connection,) = [item for item in body(response)["items"] if item["id"] == connection_id]
    return connection


@pytest.mark.spec("MOD-018")
def test_a_prompt_that_reached_the_window_fails_the_run(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)["id"]
    text = f"prompt-tokens:{DEFAULT_CONTEXT_WINDOW - 1}"
    run_id, events = start_run(server, household.token, conversation, text)
    run = wait_for_run(server, household.token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "model.context_exceeded"
    assert events[-1].type == "RUN_ERROR"
    assert events[-1].data.get("code") == "model.context_exceeded"
    # The answer to the cut prompt is not kept.
    history = str(messages(server, household.token, conversation)["items"])
    assert f"Echo: {text}" not in history


@pytest.mark.spec("MOD-018")
def test_a_prompt_that_fits_the_window_is_answered(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)["id"]
    run_id, _ = start_run(server, household.token, conversation, f"prompt-tokens:{DEFAULT_CONTEXT_WINDOW - 2}")
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"


@pytest.mark.spec("MOD-019")
def test_an_ollama_server_is_recognized(server: Server, household: Household) -> None:
    ollama = _connection(server, household.model.admin_token, household.ollama_id)
    assert ollama["server"] == {"product": "ollama", "version": OLLAMA_VERSION}
    # Any other server is not.
    other = _connection(server, household.model.admin_token, household.model.connection_id)
    assert other["server"] is None


@pytest.mark.spec("MOD-019", "MOD-014", "CNV-013")
def test_ollama_says_which_models_call_tools_and_reason(server: Server, household: Household) -> None:
    capable = _option(server, household.token, household.ollama_id, "test-model")
    assert (capable["tools"], capable["reasoning"]) == (True, True)
    assert _option(server, household.token, household.ollama_id, "small-notools")["tools"] is False
    assert _option(server, household.token, household.ollama_id, "plain-nothink")["reasoning"] is False


@pytest.mark.spec("MOD-019", "MOD-007")
def test_the_window_ollama_serves_is_used_once_known(server: Server, household: Household) -> None:
    before = _option(server, household.token, household.ollama_id, "test-model")
    assert before["served_context_window"] is None
    assert before["context_window"] == CONNECTION_WINDOW
    conversation = _on_ollama(server, household)
    run_id, _ = start_run(server, household.token, conversation, "hello")
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    after = _option(server, household.token, household.ollama_id, "test-model")
    assert after["served_context_window"] == OLLAMA_CONTEXT_LENGTH
    assert after["context_window"] == OLLAMA_CONTEXT_LENGTH
    # The context meter shows the window the model is served with.
    run_id, events = start_run(server, household.token, conversation, "again")
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert {usage["context_window"] for usage in _usage(events)} == {OLLAMA_CONTEXT_LENGTH}


@pytest.mark.spec("MOD-018", "MOD-019")
def test_a_prompt_the_ollama_server_cut_fails_the_first_run(server: Server, household: Household) -> None:
    # Smaller than the connection's window, but it filled the one the server runs the model with.
    conversation = _on_ollama(server, household)
    run_id, _ = start_run(server, household.token, conversation, f"prompt-tokens:{OLLAMA_CONTEXT_LENGTH - 1}")
    run = wait_for_run(server, household.token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "model.context_exceeded"


@pytest.mark.spec("MOD-020")
def test_an_ollama_server_says_which_models_accept_images(server: Server, household: Household) -> None:
    assert _option(server, household.token, household.ollama_id, "test-model")["images"] is True
    assert _option(server, household.token, household.ollama_id, "small-notools")["images"] is False
    # What a recognized server says wins over what an admin says (ADR-0110).
    with server.client(household.model.admin_token) as client:
        response = client.patch(f"/tenant/connections/{household.ollama_id}", json={"image_models": ["small-notools"]})
        assert response.status_code == 200, response.text
    assert _option(server, household.token, household.ollama_id, "small-notools")["images"] is False
    assert _option(server, household.token, household.ollama_id, "test-model")["images"] is True
