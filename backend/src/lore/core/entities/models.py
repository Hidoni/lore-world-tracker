"""``entities``, ``entity_aliases``, ``tags``, ``entity_tags`` (``data-model.md`` §3.1-§3.2)."""

import re
import unicodedata
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from lore.core.db.base import (
    Base,
    IdMixin,
    RevisionMixin,
    SoftDeleteMixin,
    TimestampsMixin,
    VisibilityMixin,
)


def fold_text(text: str) -> str:
    """Text compared ignoring case and accents: accents removed (NFKD, combining marks dropped),
    re-composed (NFC) and case-folded. "Élan" and "elan" fold alike."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return unicodedata.normalize("NFC", stripped).casefold()


_DIGITS = re.compile(r"[0-9]+")
MAX_NUMBER_DIGITS = 999


def _pad_number(match: re.Match[str]) -> str:
    digits = match.group().lstrip("0")[:MAX_NUMBER_DIGITS] or "0"
    return f"{len(digits):03d}{digits}"


def entity_sort_name(name: str) -> str:
    """The key names sort by (decided 2026-10-04): case and accents ignored, and numbers by value
    ("Chapter 2" before "Chapter 10"): each run of ASCII digits becomes its digit count (3 digits)
    followed by the digits without leading zeros. Compared as binary text."""
    return _DIGITS.sub(_pad_number, fold_text(name))


# Authored data: deleting a referenced row is refused (services delete children explicitly).
RESTRICT = "RESTRICT"
EMPTY_OBJECT = text("'{}'")


class Entity(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "entities"

    kind: Mapped[str] = mapped_column(String)
    # NULL: multiversal (D10), or the row is itself a dimension.
    dimension_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    # Branch-only entity marker (time-model.md §4.6); NULL = visible in every timeline.
    origin_timeline_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    name: Mapped[str] = mapped_column(String)
    sort_name: Mapped[str] = mapped_column(String)  # entity_sort_name(name), kept in sync
    slug: Mapped[str] = mapped_column(String)  # cosmetic, not unique
    summary: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    body: Mapped[Any | None] = mapped_column(JSON)
    body_schema_version: Mapped[int | None] = mapped_column(Integer)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=EMPTY_OBJECT)
    field_visibility: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=EMPTY_OBJECT
    )
    icon: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    # Soft reference owned by the media module: no FK (core never depends on modules).
    cover_media_id: Mapped[str | None] = mapped_column(String)
    sort_key: Mapped[str | None] = mapped_column(String)  # fractional index among siblings

    __table_args__ = (
        Index("ix_entities_kind", "kind"),
        Index("ix_entities_dimension_id_kind", "dimension_id", "kind"),
        Index("ix_entities_parent_id", "parent_id"),
        Index("ix_entities_origin_timeline_id", "origin_timeline_id"),
        Index("ix_entities_deleted_at", "deleted_at"),
        Index("ix_entities_kind_sort_name", "kind", "sort_name"),
        # Narrow copy of what visibility and timeline filters read: per-row joins from
        # time-bound tables (the timeline window, #51) stay index-only.
        Index(
            "ix_entities_visibility",
            "id",
            "kind",
            "deleted_at",
            "visibility",
            "dimension_id",
            "origin_timeline_id",
        ),
        Index("ix_entities_parent_id_sort_name", "parent_id", "sort_name"),
    )

    @validates("name")
    def _set_sort_name(self, _key: str, name: str) -> str:
        self.sort_name = entity_sort_name(name)
        return name


class EntityAlias(IdMixin, VisibilityMixin, Base):
    __tablename__ = "entity_aliases"

    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    alias: Mapped[str] = mapped_column(String)
    # alias | title | former_name | translation | nickname (validated by the service)
    alias_kind: Mapped[str] = mapped_column(String, default="alias", server_default=text("'alias'"))
    sort_key: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_entity_aliases_entity_id", "entity_id"),
        Index("ix_entity_aliases_alias", "alias"),
    )


def tag_name_key(name: str) -> str:
    """The case-insensitive identity of a tag name: Unicode-normalized (NFC) and case-folded.

    Done in Python because SQLite's ``lower()`` only folds ASCII ("Élan" and "élan" would both
    pass a ``lower(name)`` index).
    """
    return unicodedata.normalize("NFC", name).casefold()


class Tag(IdMixin, Base):
    """Tag names are unique ignoring case: ``name_key`` (kept in sync with ``name``) is unique."""

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String)
    name_key: Mapped[str] = mapped_column(String, unique=True)
    color: Mapped[str | None] = mapped_column(String)

    @validates("name")
    def _set_name_key(self, _key: str, name: str) -> str:
        self.name_key = tag_name_key(name)
        return name


class EntityTag(Base):
    __tablename__ = "entity_tags"

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete=RESTRICT), primary_key=True)
