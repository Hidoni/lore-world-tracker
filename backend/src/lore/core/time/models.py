"""Core time tables: ``dimensions``, ``timelines`` and ``calendars`` (entity extension tables,
``data-model.md`` §5.1-§5.3), ``events`` (§5.4) and ``time_dependencies`` (§5.5,
``time-model.md`` §7.1).

``time_dependencies`` holds the edges propagation walks. It is derived from the specs, but kept in
the same transaction as them (not recorded in history). Dependents and targets are polymorphic
(any registered record type), so it has no foreign keys.
"""

from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.chronology.schema import TimePoint
from lore.core.db.base import Base, IdMixin, TimestampsMixin
from lore.core.db.types import SortableBigInt
from lore.core.time.specs import EndSpecColumn, moment_column, spec_column, status_column

RESTRICT = "RESTRICT"


class Dimension(Base):
    """A dimension's time spec (kind ``dimension``, ``time-model.md`` §3). Its trash state and
    revision are the entity's."""

    __tablename__ = "dimensions"

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT), primary_key=True
    )
    base_unit: Mapped[dict[str, Any]] = mapped_column(JSON)  # {singular, plural, abbr}
    duration: Mapped[int] = mapped_column(SortableBigInt)  # D >= 1
    default_calendar_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    present_spec: Mapped[TimePoint | None] = spec_column()
    present_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()


class Timeline(Base):
    """A timeline (kind ``timeline``, ``time-model.md`` §4.1): the prime timeline of its dimension
    or a branch of ``parent_timeline_id`` at ``branch_point``."""

    __tablename__ = "timelines"

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT), primary_key=True
    )
    dimension_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    parent_timeline_id: Mapped[str | None] = mapped_column(
        ForeignKey("timelines.entity_id", ondelete=RESTRICT)
    )
    is_prime: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    branch_point_spec: Mapped[TimePoint | None] = spec_column()
    branch_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()

    __table_args__ = (
        Index(
            "uq_timelines_prime_dimension_id",
            "dimension_id",
            unique=True,
            sqlite_where=text("is_prime"),
        ),
        Index("ix_timelines_dimension_id", "dimension_id"),
        Index("ix_timelines_parent_timeline_id", "parent_timeline_id"),
    )


class Calendar(Base):
    """A calendar of a dimension (kind ``calendar``, ``chronology-engine.md`` §3-§4): its
    definition, the moments its non-local anchors resolved to (JSON pointer → moment string) and
    how its last compilation went."""

    __tablename__ = "calendars"

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT), primary_key=True
    )
    dimension_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    definition_revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    resolved_anchors: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    compile_status: Mapped[str] = mapped_column(String)  # ok | error
    compile_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )

    __table_args__ = (Index("ix_calendars_dimension_id", "dimension_id"),)


class Event(IdMixin, TimestampsMixin, Base):
    """An event's time-bound row (``time-model.md`` §9.1): the **home row** in the event's
    timeline, or (M9) an override row of a branch (``overrides_id`` = the home row). Its trash
    state is the entity's. ``revision`` counts the row's own changes (the entity's revision is
    what a PATCH checks)."""

    __tablename__ = "events"

    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    timeline_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    overrides_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete=RESTRICT))
    start_spec: Mapped[TimePoint] = spec_column(nullable=False)
    start_t: Mapped[int | None] = moment_column()
    end_spec: Mapped[Any] = spec_column(EndSpecColumn, nullable=False)
    end_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()
    importance: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    category: Mapped[str | None] = mapped_column(String)
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    series_start_t: Mapped[int | None] = moment_column()
    series_end_t: Mapped[int | None] = moment_column()
    series_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    occurrence_key: Mapped[str | None] = mapped_column(String)
    occurrence_state: Mapped[str | None] = mapped_column(String)  # referenced|modified|cancelled
    original_start_t: Mapped[int | None] = moment_column()
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    __table_args__ = (
        CheckConstraint("importance BETWEEN 1 AND 5", name="importance"),
        # Covers the window scan (lineage range on start, overlap on end, LOD by importance) and
        # the join to the entity, so 100k-event windows never touch the table (#51).
        Index(
            "ix_events_window",
            "timeline_id",
            "start_t",
            "end_t",
            "importance",
            "entity_id",
            "id",
        ),
        Index("ix_events_timeline_id_end_t", "timeline_id", "end_t"),
        Index(
            "ix_events_timeline_id_series_start_t",
            "timeline_id",
            "series_start_t",
            sqlite_where=text("recurrence IS NOT NULL"),
        ),
        Index(
            "uq_events_series_entity_id_occurrence_key_timeline_id",
            "series_entity_id",
            "occurrence_key",
            "timeline_id",
            unique=True,
            sqlite_where=text("series_entity_id IS NOT NULL"),
        ),
        Index("ix_events_entity_id", "entity_id"),
        Index("ix_events_overrides_id", "overrides_id"),
    )


class TimeDependency(Base):
    """``dependent`` slot → ``target``: a slot (``target_kind = 'slot'``), a calendar
    (``'calendar'``, ``target_calendar_id``) or a dimension's duration (``'dimension'``,
    ``target_id``)."""

    __tablename__ = "time_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dependent_type: Mapped[str] = mapped_column(String)
    dependent_id: Mapped[str] = mapped_column(String)
    dependent_slot: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str] = mapped_column(String)  # slot | calendar | dimension
    target_type: Mapped[str | None] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    target_slot: Mapped[str | None] = mapped_column(String)
    target_calendar_id: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_time_dependencies_dependent", "dependent_type", "dependent_id", "dependent_slot"),
        Index("ix_time_dependencies_target", "target_type", "target_id", "target_slot"),
        Index("ix_time_dependencies_target_calendar_id", "target_calendar_id"),
    )
