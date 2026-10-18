"""Recording the app's answers in process (no server, no socket): an ASGI GET as readers make it.

Routes are sync and CPU-bound, so threads only add GIL contention: reads run one at a time in
this process, or in a pool of worker processes, each with its own read-only app over the same
snapshot (``start_worker``; ``LORE_EXPORT_WORKERS``, default the CPU count up to 8).
"""

import asyncio
import json
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.types import Message

from lore.core.errors import LoreError

if TYPE_CHECKING:
    from lore.config import Settings

API_PREFIX = "/api/v1/"
MAX_WORKERS = 8


def workers() -> int:
    """How many processes record at once (``LORE_EXPORT_WORKERS``)."""
    configured = os.environ.get("LORE_EXPORT_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, min(MAX_WORKERS, os.cpu_count() or 1))


class RecordingError(LoreError):
    code = "static_export_failed"
    status = 409
    title = "Static export failed"


def route_with(route: str, params: dict[str, Any] | None = None) -> str:
    """``route`` with a query (``None`` values left out, lists repeated)."""
    pairs = [(k, v) for k, v in (params or {}).items() if v is not None]
    return f"{route}?{urlencode(pairs, doseq=True)}" if pairs else route


class Recorder:
    """GETs against the app: in this process, or in ``pool`` (``size`` workers started with
    ``start_worker``)."""

    def __init__(
        self, app: FastAPI, pool: ProcessPoolExecutor | None = None, size: int = 1
    ) -> None:
        self.app = app
        self.pool = pool
        # In flight at once: one in process; with a pool, enough to keep every worker busy.
        self.limit = asyncio.Semaphore(1 if pool is None else 2 * size)
        self.requests = 0

    async def answer(self, route: str) -> tuple[int, Any]:
        """The status and JSON body of ``GET /api/v1/<route>``."""
        status, body, _type = await self.raw(route)
        return status, json.loads(body) if body else None

    async def raw(self, route: str) -> tuple[int, bytes, str]:
        """The status, body and content type of ``GET /api/v1/<route>`` (files)."""
        async with self.limit:
            if self.pool is None:
                found = await self.local(route)
            else:
                loop = asyncio.get_running_loop()
                found = await loop.run_in_executor(self.pool, _worker_raw, route)
        self.requests += 1
        return found

    async def local(self, route: str) -> tuple[int, bytes, str]:
        """``raw`` in this process."""
        path, _, query = route.partition("?")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": API_PREFIX + path,
            "raw_path": (API_PREFIX + path).encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
            "server": ("localhost", 80),
        }
        status = 0
        content_type = ""
        body = bytearray()

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-type":
                        content_type = value.decode("latin-1")
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))

        await self.app(scope, receive, send)
        return status, bytes(body), content_type

    async def get(self, route: str) -> Any:
        """The answer of a read readers must get (anything but ``200`` fails the export)."""
        status, answer = await self.answer(route)
        if status != 200:  # noqa: PLR2004
            raise RecordingError(f"GET {API_PREFIX}{route} answered {status}: {answer}")
        return answer

    async def pages(self, route: str, params: dict[str, Any]) -> list[Any]:
        """Every item of a paged list (``items`` + ``next_cursor``)."""
        items: list[Any] = []
        cursor = None
        while True:
            page = await self.get(route_with(route, {**params, "cursor": cursor}))
            items += page["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                return items


# --- worker processes ----------------------------------------------------------------------------

_worker: tuple[asyncio.AbstractEventLoop, Recorder, AbstractAsyncContextManager[Any]] | None = None


def start_worker(settings: Settings) -> None:
    """A pool worker's initializer: its own app over the snapshot, started (lifespan) once."""
    global _worker  # noqa: PLW0603 (one app per worker process)
    from lore.app import create_app  # noqa: PLC0415 (the app imports this package)

    app = create_app(settings)
    loop = asyncio.new_event_loop()
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    _worker = (loop, Recorder(app), lifespan)


def _worker_raw(route: str) -> tuple[int, bytes, str]:
    assert _worker is not None, "start_worker didn't run"
    loop, recorder, _lifespan = _worker
    return loop.run_until_complete(recorder.local(route))
