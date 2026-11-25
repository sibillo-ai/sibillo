"""Fixtures of the agent tier (ADR-0139, ADR-0141): the API and the worker in this process, a fake sandbox driver."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.support.database import Database
from tests.support.fake_sandboxes import FakeDriver, start_fake_driver
from tests.support.fixtures import database as database
from tests.support.fixtures import default_model as default_model
from tests.support.fixtures import harness_model as harness_model
from tests.support.fixtures import mcp_service as mcp_service
from tests.support.fixtures import model_server as model_server
from tests.support.fixtures import push_service as push_service
from tests.support.fixtures import search_service as search_service
from tests.support.fixtures import world as world
from tests.support.push import PushService
from tests.support.search import SearchServer
from tests.support.server import Server, start_server


@pytest.fixture(scope="session")
def sandboxes() -> Iterator[FakeDriver]:
    driver = start_fake_driver()
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def server(
    request: pytest.FixtureRequest,
    database: Database,
    sandboxes: FakeDriver,
    search_service: SearchServer,
    push_service: PushService,
) -> Server:
    return start_server(
        request.config,
        database,
        (sandboxes.url, sandboxes.token),
        search_service.url,
        (push_service.address, push_service.certificate_authority),
        inprocess=True,
    )
