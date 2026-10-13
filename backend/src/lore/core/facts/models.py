"""``entity_facts`` (``data-model.md`` §6.3): field values that hold for a period of a timeline
(``time-model.md`` §10.2), existence (``core.exists``, §10.4) and names over time
(``core.name``). Their validity bounds are time slots (record type ``fact``)."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
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
from lore.core.time.specs import moment_column, spec_column, status_column
from lore.core.time.timeline_view import TimeBound, register_time_bound

RESTRICT = "RESTRICT"


class EntityFact(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    """A value of an entity's temporal field in one timeline, valid in ``[valid_from,
    valid_to)`` (a missing bound is open). ``overrides_id`` (a branch's override of a fact)
    arrives with M9."""

    __tablename__ = "entity_facts"

    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    field_key: Mapped[str] = mapped_column(String)
    value: Mapped[Any] = mapped_column(JSON)
    timeline_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    overrides_id: Mapped[str | None] = mapped_column(
        ForeignKey("entity_facts.id", ondelete=RESTRICT)
    )
    valid_from_spec: Mapped[TimePoint | None] = spec_column()
    valid_from_t: Mapped[int | None] = moment_column()
    valid_to_spec: Mapped[TimePoint | None] = spec_column()
    valid_to_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    note: Mapped[str | None] = mapped_column(String)
    sort_key: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_entity_facts_entity_field", "entity_id", "field_key"),
        Index("ix_entity_facts_timeline_valid_from", "timeline_id", "valid_from_t"),
        Index("ix_entity_facts_source_event_id", "source_event_id"),
    )


# A fact without a bound is valid from (or until) the end of time (time-model.md §10.1).
register_time_bound(
    TimeBound(EntityFact, start="valid_from_t", end="valid_to_t", open_start=True, open_end=True)
)
