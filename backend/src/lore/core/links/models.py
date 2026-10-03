"""``links`` and ``link_type_defs`` (``data-model.md`` §6.1-§6.2)."""

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import (
    Base,
    IdMixin,
    RevisionMixin,
    SoftDeleteMixin,
    TimestampsMixin,
    VisibilityMixin,
)
from lore.core.db.types import SortableBigInt

RESTRICT = "RESTRICT"


class Link(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    """A typed edge between two entities. Symmetric types are stored once with
    ``source_id < target_id``. The time columns are used from M3/M7; a link with no validity
    bounds is timeless (``timeline_id`` NULL)."""

    __tablename__ = "links"

    link_type: Mapped[str] = mapped_column(String)  # registry key, e.g. core.participant
    source_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    role: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    # Timelines are entities (kind timeline); the timelines extension table arrives with M3.
    timeline_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    overrides_id: Mapped[str | None] = mapped_column(ForeignKey("links.id", ondelete=RESTRICT))
    valid_from_spec: Mapped[Any | None] = mapped_column(JSON)
    valid_from_t: Mapped[int | None] = mapped_column(SortableBigInt)
    valid_to_spec: Mapped[Any | None] = mapped_column(JSON)
    valid_to_t: Mapped[int | None] = mapped_column(SortableBigInt)
    time_status: Mapped[str | None] = mapped_column(String)
    sort_key: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_links_source_id_link_type", "source_id", "link_type"),
        Index("ix_links_target_id_link_type", "target_id", "link_type"),
        Index("ix_links_link_type", "link_type"),
        Index("ix_links_timeline_id_valid_from_t", "timeline_id", "valid_from_t"),
    )


class CustomLinkType(RevisionMixin, TimestampsMixin, Base):
    """A user-defined link type (``custom.<slug>``). Core and module link types are registered in
    code; the registry merges both."""

    __tablename__ = "link_type_defs"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    inverse_label: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    # A list of kind keys, or "*" for any kind.
    source_kinds: Mapped[Any] = mapped_column(JSON, default="*", server_default=text("'\"*\"'"))
    target_kinds: Mapped[Any] = mapped_column(JSON, default="*", server_default=text("'\"*\"'"))
    symmetric: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    temporal: Mapped[str] = mapped_column(  # never | optional | required
        String, default="optional", server_default=text("'optional'")
    )
    unique_policy: Mapped[str] = mapped_column(  # none | per_pair | per_pair_per_period
        String, default="none", server_default=text("'none'")
    )
    max_targets_per_source: Mapped[int | None] = mapped_column(Integer)
    max_sources_per_target: Mapped[int | None] = mapped_column(Integer)
    data_schema: Mapped[Any | None] = mapped_column(JSON)  # JSON Schema for links.data
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
