"""A user's files are kept apart per tenant, user and conversation (TEN-008, ADR-0105).

The sandbox driver keeps a conversation's workspace, its disk and the skills
given to its sandbox in Docker volumes. Their names are built from the
tenant, the user and the conversation alone, which every operation of the
driver takes from its path, and only as UUIDs. That two sandboxes do not see
each other's files is checked on running sandboxes by SBX-001's tests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi._compat import ModelField
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from sibillo_sandboxd.app import CopyRequest, create_app
from sibillo_sandboxd.config import load_configuration
from sibillo_sandboxd.policy import SandboxId

IDENTIFIERS = ("tenant_id", "user_id", "conversation_id")


def _driver_routes() -> list[APIRoute]:
    configuration = load_configuration(
        {
            "SIBILLO_SANDBOXD_TOKEN": "t" * 43,
            "SIBILLO_SANDBOX_IMAGE": "sibillo-test/unused:none",
            "SIBILLO_NETGUARD_SOCKET": "/nonexistent/guard.sock",
        }
    )
    return [route for route in create_app(configuration).routes if isinstance(route, APIRoute)]


def _path_params(dependant: Dependant) -> list[ModelField]:
    """The path parameters of an operation and of everything it depends on."""
    return [*dependant.path_params, *(p for d in dependant.dependencies for p in _path_params(d))]


def _storage_names(sandbox: SandboxId) -> dict[str, str]:
    return {
        "container": sandbox.container,
        "workspace": sandbox.volume,
        "disk": sandbox.disk_volume,
        "skills": sandbox.skills_volume,
    }


@pytest.mark.spec("TEN-008")
def test_storage_is_named_from_the_tenant_the_user_and_the_conversation() -> None:
    sandbox = SandboxId(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    suffix = f"-{sandbox.tenant_id}-{sandbox.user_id}-{sandbox.conversation_id}"
    for kind, name in _storage_names(sandbox).items():
        assert name.endswith(suffix), f"{kind}: {name}"
        assert name.removesuffix(suffix) in {"sibillo-sandbox", "sibillo-workspace", "sibillo-disk", "sibillo-skills"}


@pytest.mark.spec("TEN-008")
@pytest.mark.parametrize("other", ["tenant", "user", "conversation"])
def test_storage_differs_when_any_identifier_differs(other: str) -> None:
    tenant, user, conversation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner = SandboxId(tenant, user, conversation)
    changed = SandboxId(
        uuid.uuid4() if other == "tenant" else tenant,
        uuid.uuid4() if other == "user" else user,
        uuid.uuid4() if other == "conversation" else conversation,
    )
    mine, theirs = _storage_names(owner), _storage_names(changed)
    assert set(mine.values()).isdisjoint(theirs.values())


@pytest.mark.spec("TEN-008")
def test_every_sandbox_operation_takes_its_storage_from_uuids_in_its_path() -> None:
    routes = [route for route in _driver_routes() if "/sandboxes/" in route.path]
    assert routes, "the driver has no sandbox operations"
    for route in routes:
        assert route.path.startswith("/v1/sandboxes/{tenant_id}/{user_id}/{conversation_id}/"), route.path
        parameters = {param.name: param for param in _path_params(route.dependant)}
        assert set(parameters) == set(IDENTIFIERS), f"{route.path}: {sorted(parameters)}"
        for name in IDENTIFIERS:
            assert parameters[name].field_info.annotation is uuid.UUID, f"{route.path}: {name}"


@pytest.mark.spec("TEN-008")
def test_a_copy_names_only_a_conversation_of_the_same_tenant_and_user() -> None:
    # A fork copies the workspace of another conversation; the request cannot
    # name another tenant or user, so the source is in the same partition.
    assert set(CopyRequest.model_fields) == {"from_conversation_id"}
    assert CopyRequest.model_fields["from_conversation_id"].annotation is uuid.UUID
