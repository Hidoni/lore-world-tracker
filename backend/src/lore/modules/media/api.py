"""The media module's public API for other modules (``modules.md`` §2: import only ``api.py``).

A module that shows media in its own records (maps: a location's map image) records the use with
``reference`` and drops it with ``unreference``, under its own context (``map``, ``note``): those
contexts aren't touched when the entity's body, fields, cover or gallery change. The item is then
visible to readers who see the entity, unless ``visibility`` says otherwise, and it isn't
collected as unused."""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lore.core.db.base import Visibility
from lore.core.errors import InvalidInputError
from lore.modules.media.models import MediaItem, MediaRef
from lore.modules.media.refs import DERIVED

RESERVED = frozenset(DERIVED)


def _context(context: str) -> str:
    if context in RESERVED or context.startswith("field:") or not context:
        raise ValueError(f"context {context!r} belongs to the media module")
    return context


def reference(
    session: Session,
    media_id: str,
    entity_id: str,
    context: str,
    visibility: Visibility = "public",
) -> None:
    """Record that ``entity_id`` uses ``media_id`` in ``context`` (idempotent; a new level
    replaces the old one). An unknown item is refused (``422``, path ``media_id``)."""
    _context(context)
    if session.get(MediaItem, media_id) is None:
        raise InvalidInputError(
            "No such media item.",
            errors=[
                {"path": "media_id", "code": "invalid_value", "message": "No such media item."}
            ],
        )
    row = session.get(MediaRef, (media_id, entity_id, context))
    if row is None:
        session.add(MediaRef(media_id=media_id, entity_id=entity_id, context=context,
                             visibility=visibility))  # fmt: skip
    else:
        row.visibility = visibility
    session.flush()


def unreference(
    session: Session, entity_id: str, context: str, media_id: str | None = None
) -> None:
    """Drop the entity's references in ``context`` (only to ``media_id`` when given)."""
    _context(context)
    statement = delete(MediaRef).where(MediaRef.entity_id == entity_id, MediaRef.context == context)
    if media_id is not None:
        statement = statement.where(MediaRef.media_id == media_id)
    session.execute(statement)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    mime: str
    width: int | None
    height: int | None
    trashed: bool


def info(session: Session, media_id: str) -> MediaInfo | None:
    """What another module needs to know of an item (``None``: no such item)."""
    row = session.get(MediaItem, media_id)
    if row is None:
        return None
    return MediaInfo(row.id, row.mime, row.width, row.height, row.deleted_at is not None)


def exists(session: Session, media_id: str) -> bool:
    """Whether the item exists and isn't in the trash."""
    return (
        session.scalar(
            select(MediaItem.id).where(MediaItem.id == media_id, MediaItem.deleted_at.is_(None))
        )
        is not None
    )


__all__ = ["MediaInfo", "exists", "info", "reference", "unreference"]
