"""The lexicon table (``docs/modules/languages.md``, Tables): one row per lexicon entry of a
language, with an optional attestation period (time slots ``valid_from``/``valid_to``)."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.chronology.schema import TimePoint
from lore.core.db.base import (
    Base,
    IdMixin,
    RevisionMixin,
    SoftDeleteMixin,
    TimestampsMixin,
    VisibilityMixin,
)
from lore.core.time import (
    TimeBound,
    moment_column,
    register_time_bound,
    spec_column,
    status_column,
)

RESTRICT = "RESTRICT"


class LexiconEntry(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    """A word or phrase of a language. ``collation_key`` sorts it by the language's own
    alphabet (``lore.modules.languages.collation``); it is recomputed when the order changes."""

    __tablename__ = "languages_lexicon_entries"

    language_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    headword: Mapped[str] = mapped_column(String)
    romanization: Mapped[str | None] = mapped_column(String)
    pronunciation: Mapped[str | None] = mapped_column(String)
    part_of_speech: Mapped[str | None] = mapped_column(String)
    definitions: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    etymology: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    notes: Mapped[Any | None] = mapped_column(JSON)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    collation_key: Mapped[str] = mapped_column(String)
    timeline_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    valid_from_spec: Mapped[TimePoint | None] = spec_column()
    valid_from_t: Mapped[int | None] = moment_column()
    valid_to_spec: Mapped[TimePoint | None] = spec_column()
    valid_to_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()
    sort_key: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_languages_lexicon_entries_language_collation", "language_id", "collation_key"),
        Index("ix_languages_lexicon_entries_language_headword", "language_id", "headword"),
        Index("ix_languages_lexicon_entries_language_pos", "language_id", "part_of_speech"),
        Index("ix_languages_lexicon_entries_timeline_id", "timeline_id"),
    )


# Attestation periods are open-ended when a bound is missing (a word still in use).
register_time_bound(
    TimeBound(LexiconEntry, start="valid_from_t", end="valid_to_t", open_start=True, open_end=True)
)
