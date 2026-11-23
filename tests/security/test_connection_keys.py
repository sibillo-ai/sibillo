"""A connection's key is sent only to the address it was given for (MOD-008, MOD-002, ADR-0117).

Keys are write-only, so a tenant admin who never knew one must not be able to
read it by pointing the connection at a server of their own. The model the
tests serve answers at two addresses, its own and that of an Ollama server,
and records the headers of every request it receives.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.support.accounts import assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.server import Server


def _sent_with(model: HarnessModel, key: str) -> list[str]:
    """The paths of the requests the model's server received with the key."""
    return [request.path for request in model.endpoint.requests if request.authorization == f"Bearer {key}"]


@pytest.mark.spec("MOD-008", "MOD-002")
def test_a_new_address_alone_never_receives_the_stored_key(
    database: Database, server: Server, harness_model: HarnessModel
) -> None:
    tenant = create_tenant(database)
    # The instance admin adds the connection, with a key, at an address of the household.
    owner = create_account(database, tenant, "tenant_admin", instance_admin=True)
    key = f"sk-secret-{uuid4().hex}"
    connection = {
        "name": f"Server {uuid7()}",
        "kind": "openai",
        "base_url": harness_model.endpoint.url,
        "location": "local",
        "api_key": key,
    }
    with server.client(login(server, owner)) as client:
        response = client.post("/tenant/connections", json=connection)
    assert response.status_code == 201, response.text
    connection_id = body(response)["id"]
    path = f"/tenant/connections/{connection_id}"
    elsewhere = harness_model.endpoint.ollama_url
    # Moved without its key, by the admin who set it or by another: refused before any request is made.
    other = create_account(database, tenant, "tenant_admin", instance_admin=True)
    for admin in (owner, other):
        with server.client(login(server, admin)) as client:
            refused = assert_problem(client.patch(path, json={"base_url": elsewhere}), 422, "request.validation_failed")
        assert refused["errors"] == [{"location": "/api_key", "code": "required_with_new_address"}]
    assert [sent for sent in _sent_with(harness_model, key) if "/ollama/" in sent] == []
    with server.client(login(server, other)) as client:
        (kept,) = [item for item in body(client.get("/tenant/connections"))["items"] if item["id"] == connection_id]
        assert (kept["base_url"], kept["has_api_key"]) == (harness_model.endpoint.url, True)
        # The same address, with or without its trailing slash, is no new address: the key stays where it was.
        same = client.patch(path, json={"base_url": harness_model.endpoint.url + "/", "name": "Renamed"})
        assert same.status_code == 200, same.text
        assert body(same)["has_api_key"] is True
        # Moved with a new key, the new key is tested at the new address and saved.
        new_key = f"sk-new-{uuid4().hex}"
        moved = client.patch(path, json={"base_url": elsewhere, "api_key": new_key})
        assert moved.status_code == 200, moved.text
        assert (body(moved)["base_url"], body(moved)["has_api_key"]) == (elsewhere, True)
    assert any("/ollama/" in sent for sent in _sent_with(harness_model, new_key))
    # Moved back with the key removed: tested without any key.
    with server.client(login(server, other)) as client:
        back = client.patch(path, json={"base_url": harness_model.endpoint.url, "api_key": None})
        assert back.status_code == 200, back.text
        assert body(back)["has_api_key"] is False
    # The first key only ever reached the address it was given for.
    assert _sent_with(harness_model, key)
    assert [sent for sent in _sent_with(harness_model, key) if "/ollama/" in sent] == []
    assert [sent for sent in _sent_with(harness_model, new_key) if "/ollama/" not in sent] == []
