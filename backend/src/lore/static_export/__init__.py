"""Static export (``visibility-and-sharing.md`` §8, ADR 0016): a published snapshot as plain files
that any static HTTP server can host, read by the SPA's ``StaticDataSource``.

The export answers the reader read surface (§6) from **recorded responses**: the builder starts
the app read-only over the snapshot, in process, and records what readers get from its GET
routes, so the files hold exactly what a read-only server would answer (the same visibility
policy, the same shapes). A response for path ``/api/v1/<route>`` is written to
``data/<route>.json``; reads with free parameters (a prefix, a cursor moment, a window) are
recorded once in full and answered in the browser from that file.

Entity reads (#374) are an index the browser lists from and a shard of recorded answers per
entity (``entities.py``).

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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from lore import __version__
from lore.app import create_app
from lore.config import Settings
from lore.core.errors import LoreError
from lore.core.modules import ModuleSpec
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.visibility import READER
from lore.static_export.asgi import Recorder, start_worker, workers
from lore.static_export.entities import EntityExport
from lore.static_export.modules import ModuleExport
from lore.static_export.search import search_index
from lore.static_export.time import TimeExport
from lore.static_export.windows import WindowExport

FORMAT_VERSION = 1
MANIFEST_NAME = "static.json"
DATA_DIR = "data"
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


async def _record(
    app: FastAPI, vault_id: str, recorder: Recorder
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Every file under ``data/``: the JSON ones (by path without ``.json``) and the copied
    downloads (by path)."""
    async with app.router.lifespan_context(app):
        files = {route.partition("?")[0]: await recorder.get(route) for route in _routes(vault_id)}
        entities = EntityExport(app, recorder, vault_id)
        files.update(await entities.files())
        files.update(
            await TimeExport(recorder, vault_id).files(
                entities.timelines, entities.summaries, entities.moments
            )
        )
        opened = app.state.vaults.open(vault_id)
        with opened.sessions() as session:
            context = VaultContext(opened, session, app.state.registry)
            windows = WindowExport(recorder, vault_id)
            files.update(await windows.files(context, entities.timelines))
            files[f"vaults/{vault_id}/static/search"] = search_index(
                session, app.state.registry, entities.timelines
            )
        module_files, binaries = await ModuleExport(recorder, vault_id).record(
            app.state.registry.modules,
            entities.summaries,
            entities.timelines,
            entities.moments,
            windows.event_moments,
        )
        files.update(module_files)
        with opened.sessions() as session:
            files.update(_module_data(VaultContext(opened, session, app.state.registry), vault_id,
                                      entities.moments))  # fmt: skip
    return files, binaries


def _module_data(
    context: VaultContext, vault_id: str, moments: dict[tuple[str, str], list[int]]
) -> dict[str, Any]:
    """The data the browser computes module views from (``ModuleSpec.static_data``), for the
    modules on in the vault: by timeline, every moment a record can change at."""
    by_timeline: dict[str, set[int]] = {}
    for (_entity, timeline), found in moments.items():
        by_timeline.setdefault(timeline, {0}).update(found)
    ordered = {timeline: sorted(found) for timeline, found in by_timeline.items()}
    enabled = set(enabled_modules(context.session, context.registry))
    files: dict[str, Any] = {}
    for module in context.registry.modules:
        if module.static_data is None or module.id not in enabled:
            continue
        for name, data in module.static_data(context, READER, ordered).items():
            files[f"vaults/{vault_id}/static/m/{module.id}/{name}"] = data
    return files


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
        # A pool of worker processes for the default modules (tests pass their own, which
        # workers couldn't rebuild): the reads are independent.
        size = workers() if modules is None else 1
        if size > 1:
            with ProcessPoolExecutor(size, initializer=start_worker, initargs=(settings,)) as pool:
                recorder = Recorder(app, pool, size)
                files, binaries = asyncio.run(_record(app, info.id, recorder))
        else:
            files, binaries = asyncio.run(_record(app, info.id, Recorder(app)))
    finally:
        app.state.vaults.close()

    shutil.copytree(spa_dir, out, dirs_exist_ok=True)
    _mark_index(out / "index.html", info.id)
    for route, response in files.items():
        target = out / data_path(route)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    for path, body in binaries.items():
        target = out / DATA_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
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
    return StaticExportInfo(path=out, vault_id=info.id, files=len(files) + len(binaries))
