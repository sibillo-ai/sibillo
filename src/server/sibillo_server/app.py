"""The ASGI application of the public API (API-001)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sibillo_server import (
    accounts,
    admin,
    auth,
    budgets,
    changes,
    connections,
    conversations,
    costs,
    egress,
    folders,
    health,
    mcp_servers,
    memory,
    notifications,
    passkeys,
    permissions,
    runs,
    settings,
    sign_in,
    skills,
    speech,
    tasks,
    web,
    workspace,
)
from sibillo_server.body_limits import BodyLimits
from sibillo_server.config import ApiConfiguration
from sibillo_server.database import create_engine
from sibillo_server.durable import create_client
from sibillo_server.errors import install_error_handlers
from sibillo_server.security_headers import SecurityHeaders

API_PREFIX = "/v1"


def create_app(configuration: ApiConfiguration) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(configuration.database_url)
        app.state.engine = engine
        durable = create_client(configuration.database_url)
        app.state.durable = durable
        # The stream of the user's changes (API-008, ADR-0108).
        listener = changes.Listener(configuration.database_url)
        listener.start()
        app.state.changes = listener
        try:
            yield
        finally:
            await listener.stop()
            durable.destroy()
            await engine.dispose()

    app = FastAPI(
        title="Sibillo public API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.configuration = configuration
    app.include_router(sign_in.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(passkeys.router, prefix=API_PREFIX)
    app.include_router(notifications.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(memory.router, prefix=API_PREFIX)
    app.include_router(skills.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(accounts.router, prefix=API_PREFIX)
    app.include_router(budgets.router, prefix=API_PREFIX)
    app.include_router(connections.router, prefix=API_PREFIX)
    app.include_router(mcp_servers.router, prefix=API_PREFIX)
    app.include_router(conversations.router, prefix=API_PREFIX)
    app.include_router(folders.router, prefix=API_PREFIX)
    app.include_router(costs.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(permissions.router, prefix=API_PREFIX)
    app.include_router(egress.router, prefix=API_PREFIX)
    app.include_router(speech.router, prefix=API_PREFIX)
    app.include_router(tasks.router, prefix=API_PREFIX)
    app.include_router(changes.router, prefix=API_PREFIX)
    app.include_router(workspace.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    if configuration.web_root.is_dir():
        # After the API's routes, so that the app never hides an operation (ADR-0067).
        app.include_router(web.router(configuration.web_root))
    install_error_handlers(app)
    # Outermost, so that a body over its limit is refused before any route or session check (API-009, ADR-0119).
    app.add_middleware(BodyLimits, prefix=API_PREFIX)
    # Outside the body limits, so that their answers carry the headers too (AUTH-005, ADR-0131).
    https = (configuration.public_origin or "").startswith("https://")
    app.add_middleware(SecurityHeaders, prefix=API_PREFIX, https=https)
    return app
