"""A vault's static site (``visibility-and-sharing.md`` §8): its latest published snapshot exported
with ``lore.static_export`` into the publish directory, beside the snapshot, for any static host.

The exporter comes from the app (``app.state.static_exporter``, set by ``lore.app``): it starts an
app over the snapshot with every module, which core may not import."""

import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from lore.core.errors import ConflictError
from lore.core.vaults.manager import VaultInfo
from lore.core.vaults.publish import last_published

STATIC = "static"
MANIFEST = "static.json"

# (data dir, vault id or folder, output folder, SPA build): ``lore.static_export.export_static``.
type Exporter = Callable[[Path, str, Path, Path], object]


class NoSnapshotError(ConflictError):
    code = "static_export_failed"
    title = "Static export failed"


def static_site(publish_dir: Path, info: VaultInfo) -> Path:
    """Where the vault's static site goes: ``<publish dir>/static/<vault folder>/``."""
    return publish_dir / STATIC / info.folder


def site_exported_at(site: Path) -> datetime | None:
    """When the site in ``site`` was exported (``None``: there is none)."""
    try:
        manifest = json.loads((site / MANIFEST).read_text(encoding="utf-8"))
        return datetime.fromisoformat(manifest["exported_at"])
    except OSError, ValueError, KeyError, TypeError:
        return None


def export_site(publish_dir: Path, info: VaultInfo, spa_dir: Path, exporter: Exporter) -> Path:
    """Export the vault's latest snapshot as its static site, replacing the previous one only
    once the new one is complete."""
    if last_published(publish_dir, info) is None:
        raise NoSnapshotError("Publish a snapshot first: the static site is made from it.")
    site = static_site(publish_dir, info)
    building = site.with_name(f".{site.name}.building")
    shutil.rmtree(building, ignore_errors=True)
    exporter(publish_dir, info.folder, building, spa_dir)
    previous = site.with_name(f".{site.name}.previous")
    shutil.rmtree(previous, ignore_errors=True)
    if site.exists():
        site.rename(previous)
    building.rename(site)
    shutil.rmtree(previous, ignore_errors=True)
    return site
