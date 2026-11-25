"""The API and the worker in the test process, in threads of their own (ADR-0139).

They serve the same HTTP interface as the processes of `tests.support.server`, on a free port, so that
a test of the agent tier reads as one of the infrastructure tier; what they save is the start of
two processes and of the sandbox engine, not a layer of the system.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping

import uvicorn

from sibillo_server.app import create_app
from sibillo_server.config import load_api_configuration, load_worker_configuration

STOP_TIMEOUT_SECONDS = 10


class InProcessApi:
    """The API, served by uvicorn in a thread."""

    command = "api"

    def __init__(self, environment: Mapping[str, str]) -> None:
        configuration = load_api_configuration(environment)
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(configuration),
                host=configuration.http_host,
                port=configuration.http_port,
                proxy_headers=False,
                server_header=False,
                log_level="warning",
            )
        )
        self._thread = threading.Thread(target=self._server.run, name="api", daemon=True)
        self._thread.start()

    def output(self) -> str:
        return ""

    def exited(self) -> int | None:
        return None if self._thread.is_alive() else 1

    def close(self) -> None:
        self._server.should_exit = True
        self._thread.join(STOP_TIMEOUT_SECONDS)


class InProcessWorker:
    """The worker, with its durable execution engine, in a thread with an event loop of its own."""

    command = "worker"

    def __init__(self, environment: Mapping[str, str]) -> None:
        # Imported here: only the worker registers workflows with DBOS.
        from sibillo_server.worker import configure_worker, serve

        configuration = load_worker_configuration(environment)
        self._error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        started = threading.Event()

        def work() -> None:
            async def main() -> None:
                self._loop = asyncio.get_running_loop()
                self._stop = asyncio.Event()
                started.set()
                await serve(configuration, self._stop)

            try:
                configure_worker(configuration)
                asyncio.run(main())
            except BaseException as error:
                self._error = error
                started.set()

        self._thread = threading.Thread(target=work, name="worker", daemon=True)
        self._thread.start()
        started.wait(STOP_TIMEOUT_SECONDS)

    def output(self) -> str:
        return repr(self._error)

    def exited(self) -> int | None:
        return None if self._thread.is_alive() else 1

    def close(self) -> None:
        from dbos import DBOS

        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(STOP_TIMEOUT_SECONDS)
        DBOS.destroy()
