"""The media module's tables (``docs/modules/media.md``, Tables).

- ``media_items``: one row per stored file (``sha256`` unique: the same bytes are one item).
  Recorded by history, so trashing and editing can be undone; the file itself stays on disk until
  the item is purged.
- ``media_refs`` (derived): who uses an item, rebuilt whenever an owning context is saved
  (``lore.modules.media.refs``). ``visibility`` is the least restrictive level the item has in
  that context (an image in a private block of a public body is private there).
- ``media_gallery``: an entity's gallery, ordered by ``sort_key``.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import (
    VISIBILITIES,
    Base,
    IdMixin,
    RevisionMixin,
    SoftDeleteMixin,
    TimestampsMixin,
    Visibility,
    VisibilityMixin,
)
from lore.core.db.types import UTCDateTime

CASCADE = "CASCADE"


class MediaItem(IdMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "media_items"

    sha256: Mapped[str] = mapped_column(String, unique=True)
    filename: Mapped[str] = mapped_column(String)  # the uploaded name: display only
    mime: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    alt: Mapped[str] = mapped_column(String, default="", server_default="")
    caption: Mapped[str] = mapped_column(String, default="", server_default="")
    # When the daily collection first found it unused (no refs); cleared once it is used again.
    unused_since: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MediaRef(Base):
    __tablename__ = "media_refs"

    media_id: Mapped[str] = mapped_column(
        ForeignKey("media_items.id", ondelete=CASCADE), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=CASCADE), primary_key=True
    )
    context: Mapped[str] = mapped_column(String, primary_key=True)
    visibility: Mapped[Visibility] = mapped_column(
        String,
        CheckConstraint(
            "visibility IN (" + ", ".join(f"'{v}'" for v in VISIBILITIES) + ")",
            name="visibility",
        ),
    )

    __table_args__ = (Index("ix_media_refs_entity_id", "entity_id"),)


class MediaGalleryItem(
    IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base
):
    __tablename__ = "media_gallery"

    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=CASCADE))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.id", ondelete=CASCADE))
    caption: Mapped[str] = mapped_column(String, default="", server_default="")
    sort_key: Mapped[str] = mapped_column(String)

    __table_args__ = (
        Index("ix_media_gallery_entity_sort", "entity_id", "sort_key"),
        Index("ix_media_gallery_media_id", "media_id"),
    )
