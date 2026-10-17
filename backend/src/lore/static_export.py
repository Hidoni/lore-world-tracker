"""Static export (``visibility-and-sharing.md`` §8, ADR 0016): a published snapshot as plain files
that any static HTTP server can host, read by the SPA's ``StaticDataSource``.

The export answers the reader read surface (§6) from **recorded responses**: the builder starts
the app read-only over the snapshot, in process, and records what readers get from its GET
routes, so the files hold exactly what a read-only server would answer (the same visibility
policy, the same shapes). A response for path ``/api/v1/<route>`` is written to
``data/<route>.json``; reads with free parameters (a prefix, a cursor moment, a window) are
recorded once in full and answered in the browser from that file.

The output folder holds the SPA build (its ``index.html`` marked for static mode: hash routing,
the static data source), ``static.json`` (the manifest: chunk format, vault, app version) and
``data/``. Building from anything but a published snapshot is refused: private data must not
exist in the source, not merely be filtered on the way out.
"""

import asyncio
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.types import Message

from lore import __version__
from lore.app import create_app
from lore.config import Settings
from lore.core.errors import LoreError
from lore.core.modules import ModuleSpec

FORMAT_VERSION = 1
MANIFEST_NAME = "static.json"
DATA_DIR = "data"
API_PREFIX = "/api/v1/"
# The tag `index.html` carries in a static export (read by the SPA before it starts).
STATIC_MARKER = '<meta name="lore-static" content="data/" />'
BASE_TAG = re.compile(r'<base href="/"\s*/?>')


class StaticExportError(LoreError):
    code = "static_export_failed"
    status = 409
    title = "Static export failed"


@dataclass(frozen=True)
class StaticExportInfo:
    path: Path
    vault_id: str
    files: int


def _routes(vault_id: str) -> list[str]:
    """The reads recorded, as API paths (with their query, where a read has free parameters and
    the browser filters the full answer)."""
    base = f"vaults/{vault_id}"
    return [
        "meta",
        "vaults",
        base,
        f"{base}/settings",
        f"{base}/registry",
        f"{base}/link-types",
        f"{base}/calendars/presets",
        f"{base}/tags?limit=1000",
    ]


def data_path(route: str) -> str:
    """Where the response for an API route (``vaults/x/registry``, without ``/api/v1/`` and
    without its query) is written, relative to the export folder."""
    return f"{DATA_DIR}/{route}.json"


async def _get(app: FastAPI, route: str) -> Any:
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
    body = bytearray()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    await app(scope, receive, send)
    if status != 200:  # noqa: PLR2004
        raise StaticExportError(f"GET {API_PREFIX}{route} answered {status}: {body.decode()}")
    return json.loads(body)


async def _record(app: FastAPI, routes: Sequence[str]) -> dict[str, Any]:
    async with app.router.lifespan_context(app):
        return {route: await _get(app, route) for route in routes}


def _mark_index(index: Path, vault_id: str) -> None:
    """Static mode for the SPA: the marker tag and a relative base, so the export works from any
    folder of any host."""
    html = index.read_text(encoding="utf-8")
    html, based = BASE_TAG.subn('<base href="./" />', html, count=1)
    if not based:
        raise StaticExportError(f'{index} has no <base href="/">: not a Lore SPA build')
    marker = STATIC_MARKER.replace("/>", f'data-vault="{vault_id}" />')
    index.write_text(html.replace("</head>", f"    {marker}\n  </head>", 1), encoding="utf-8")


def export_static(
    data_dir: Path,
    vault: str,
    out: Path,
    spa_dir: Path,
    *,
    modules: Sequence[ModuleSpec] | None = None,
    now: datetime | None = None,
) -> StaticExportInfo:
    """Export the published snapshot ``vault`` (id or folder name) of the data directory
    ``data_dir`` into the folder ``out`` (created; it must be empty or missing), with the SPA
    build ``spa_dir``. ``modules`` defaults to every module (tests pass their own)."""
    if not (spa_dir / "index.html").is_file():
        raise StaticExportError(f"{spa_dir} holds no SPA build (index.html)")
    if out.exists() and any(out.iterdir()):
        raise StaticExportError(f"{out} is not empty")
    settings = Settings(data_dir=data_dir, read_only=True, exposed_vaults=[vault])
    app = create_app(settings, modules)
    try:
        info = app.state.vaults.resolve(vault)
        if not info.manifest.published:
            raise StaticExportError(
                f"{info.name} is not a published snapshot: publish it first (lore vault "
                "publish) and export the snapshot"
            )
        responses = asyncio.run(_record(app, _routes(info.id)))
    finally:
        app.state.vaults.close()

    shutil.copytree(spa_dir, out, dirs_exist_ok=True)
    _mark_index(out / "index.html", info.id)
    for route, response in responses.items():
        target = out / data_path(route.partition("?")[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    manifest = {
        "format": FORMAT_VERSION,
        "vault_id": info.id,
        "vault_name": info.name,
        "app_version": __version__,
        "published_at": info.manifest.published_at.isoformat()
        if info.manifest.published_at
        else None,
        "exported_at": (now or datetime.now(UTC)).isoformat(),
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    return StaticExportInfo(path=out, vault_id=info.id, files=len(responses))
