"""Recording the app's answers in process (no server, no socket): an ASGI GET as readers make it."""

import asyncio
import json
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.types import Message

from lore.core.errors import LoreError

API_PREFIX = "/api/v1/"
# Reads in flight at once. One: routes are sync and CPU-bound, so threads only add GIL contention
# (the tiny world exported in 48 s with one, 60 s with four).
CONCURRENCY = 1


class RecordingError(LoreError):
    code = "static_export_failed"
    status = 409
    title = "Static export failed"


def route_with(route: str, params: dict[str, Any] | None = None) -> str:
    """``route`` with a query (``None`` values left out, lists repeated)."""
    pairs = [(k, v) for k, v in (params or {}).items() if v is not None]
    return f"{route}?{urlencode(pairs, doseq=True)}" if pairs else route


class Recorder:
    """GETs against the app, ``CONCURRENCY`` at a time."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.limit = asyncio.Semaphore(CONCURRENCY)
        self.requests = 0

    async def answer(self, route: str) -> tuple[int, Any]:
        """The status and JSON body of ``GET /api/v1/<route>``."""
        status, body, _type = await self.raw(route)
        return status, json.loads(body) if body else None

    async def raw(self, route: str) -> tuple[int, bytes, str]:
        """The status, body and content type of ``GET /api/v1/<route>`` (files)."""
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

        async with self.limit:
            await self.app(scope, receive, send)
        self.requests += 1
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
