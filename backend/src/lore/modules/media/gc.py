"""Collecting unused media (``docs/modules/media.md``, GC): a daily task per open vault
(``ModuleSpec.maintenance_tasks``).

1. Items without references (no ``media_refs`` row: not in a body, field, cover, gallery or
   another module's context) get ``unused_since``; items in use lose it. These marks aren't
   history.
2. Items unused for ``trash_after_days`` (default 30) move to the trash, as one changeset that
   can be undone.
3. Items in the trash for ``purge_after_days`` (default 30) that are still unused are deleted
   with their files. Never without the trash first, and not undoable: the files are gone.

The delays come from the module's stored settings (``{"trash_after_days": …,
"purge_after_days": …}``)."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, exists, select, update
from sqlalchemy.orm import Session

from lore.core.history import recorder
from lore.core.modules.spec import VaultContext
from lore.core.vaults.meta import get_meta
from lore.modules.media import storage
from lore.modules.media.models import MediaItem, MediaRef

MODULE = "media"
DEFAULT_DAYS = 30


def _days(context: VaultContext, key: str) -> int:
    settings = get_meta(context.session, "settings")
    module: Any = {}
    if isinstance(settings, dict):
        module = (settings.get("modules", {}).get(MODULE) or {}).get("settings") or {}
    value = module.get(key, DEFAULT_DAYS) if isinstance(module, dict) else DEFAULT_DAYS
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else (DEFAULT_DAYS)
    )


def _used() -> Any:
    return exists(select(MediaRef.media_id).where(MediaRef.media_id == MediaItem.id))


def _remove_after_commit(session: Session, vault_path: Any, hashes: list[str]) -> None:
    """Delete the files once the rows are gone for good (a rolled-back purge keeps them)."""

    def remove(_session: Session) -> None:
        for sha256 in hashes:
            storage.remove(vault_path, sha256)

    event.listen(session, "after_commit", remove, once=True)


def collect(context: VaultContext, now: datetime) -> dict[str, int]:
    """One collection; returns how many items were marked, trashed and purged."""
    session = context.session
    trash_before = now - timedelta(days=_days(context, "trash_after_days"))
    purge_before = now - timedelta(days=_days(context, "purge_after_days"))
    counts = {"marked": 0, "trashed": 0, "purged": 0}
    with recorder.discarded(session):
        session.execute(
            update(MediaItem)
            .where(MediaItem.unused_since.is_not(None), _used())
            .values(unused_since=None)
        )
        fresh = list(
            session.scalars(
                select(MediaItem.id).where(
                    MediaItem.unused_since.is_(None), MediaItem.deleted_at.is_(None), ~_used()
                )
            )
        )
        if fresh:
            session.execute(
                update(MediaItem).where(MediaItem.id.in_(fresh)).values(unused_since=now)
            )
        counts["marked"] = len(fresh)
        purged = list(
            session.execute(
                select(MediaItem.id, MediaItem.sha256).where(
                    MediaItem.deleted_at.is_not(None),
                    MediaItem.deleted_at <= purge_before,
                    ~_used(),
                )
            )
        )
        if purged:
            session.execute(delete(MediaItem).where(MediaItem.id.in_([i for i, _ in purged])))
            _remove_after_commit(session, context.vault.info.path, [h for _, h in purged])
        counts["purged"] = len(purged)
        session.flush()
    unused = list(
        session.scalars(
            select(MediaItem).where(
                MediaItem.deleted_at.is_(None),
                MediaItem.unused_since.is_not(None),
                MediaItem.unused_since <= trash_before,
                ~_used(),
            )
        )
    )
    for item in unused:
        item.deleted_at = now
    if unused:
        recorder.describe(session, f"Moved {len(unused)} unused media items to the trash")
        session.flush()
    counts["trashed"] = len(unused)
    return counts


def collect_task(context: VaultContext, now: datetime) -> None:
    collect(context, now)


__all__ = ["collect", "collect_task"]
