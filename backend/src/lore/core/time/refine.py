"""Refining a dimension's base unit (``time-model.md`` §3.1, #152): seconds → milliseconds,
every quantity the dimension stores in base units multiplied by an integer factor, in one
transaction (one changeset, origin ``refinement``).

What is rewritten, for the records whose time resolves in the dimension:

- time point and end specs of every slot in columns (each provider's dimension or timeline
  column), with their last good moments, and the ``entity_time_fields`` mirror;
- documents holding time points or base durations: entity fields and bodies (``timeRef``
  nodes), fact values, per-timeline notes; recurrence rules (an interval rule's ``every``, its
  limit and exclusions), their resolved anchors and series bounds;
- calendar definitions (the finest level's counts, absolute anchors, overlay periods) and their
  resolved anchors;
- the dimension's ``D`` and, when given, its base unit names; the rates of its correspondences
  and of worldline segments in it or measured by its clock.

Pending proposals about its calendars and series are dropped, and every moment is resolved again
(``rebuild_time``). Calendar dates, calendar durations and precisions don't change: a ``base``
precision point is now exact to the finer unit.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select

from lore.chronology.refine import (
    refine_definition,
    refine_json,
    refine_moments,
    refine_rate,
    refine_rule,
)
from lore.core.entities.models import Entity
from lore.core.errors import InvalidInputError, NotFoundError
from lore.core.history import recorder
from lore.core.history.recorder import REFINEMENT
from lore.core.time.cache import CALENDARS, SERIES, WINDOWS
from lore.core.time.check import rebuild_time
from lore.core.time.fields import ENTITY_FIELD
from lore.core.time.models import (
    Calendar,
    Correspondence,
    Dimension,
    EntityTimeField,
    EntityTimelineNote,
    Event,
    Proposal,
    Timeline,
    WorldlineSegment,
)
from lore.core.time.slots import SlotProvider, SlotRegistry
from lore.core.time.specs import dump_spec
from lore.core.time.status import TimeStatus

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

MIN_FACTOR = 2
MAX_FACTOR = 10**18
_GOOD = (TimeStatus.OK.value, TimeStatus.TRASHED_REF.value)


@dataclass
class RefineReport:
    dimension_id: str
    factor: int
    duration: int
    """The new ``D``."""
    rewritten: dict[str, int] = field(default_factory=dict)
    """Rows rewritten per table."""
    slots: int = 0
    """Slots resolved again (the whole vault)."""
    problems_before: int = 0
    problems_after: int = 0
    """Slots of the vault that don't resolve, before and after."""


def refine_base_unit(
    context: VaultContext,
    dimension_id: str,
    factor: int,
    base_unit: dict[str, str] | None = None,
) -> RefineReport:
    """Multiply the dimension's base-unit quantities by ``factor`` (``>= 2``) and resolve every
    moment again. ``base_unit`` (``{singular, plural, abbr}``) renames the unit."""
    session = context.session
    dimension = session.get(Dimension, dimension_id)
    if dimension is None:
        raise NotFoundError(f"No dimension {dimension_id}.")
    if not MIN_FACTOR <= factor <= MAX_FACTOR:
        raise InvalidInputError(
            f"The factor must be a whole number from {MIN_FACTOR} to {MAX_FACTOR}."
        )
    history = recorder.context(session)
    history.origin = REFINEMENT
    history.summary = _summary(session, dimension, factor, base_unit)
    report = RefineReport(dimension_id, factor, dimension.duration * factor)
    report.problems_before = _problems(session)
    registry: SlotRegistry = context.registry.slot_registry()

    def count(table: str, rows: int) -> None:
        if rows:
            report.rewritten[table] = report.rewritten.get(table, 0) + rows

    for provider in registry.providers:
        table: Any = provider.model
        count(table.__table__.name, _column_slots(session, provider, dimension_id, factor))
    count("entity_time_fields", _field_slots(context, registry, dimension_id, factor))
    for table_name, rows in _documents(session, dimension_id, factor).items():
        count(table_name, rows)
    count("correspondences", _correspondences(session, dimension_id, factor))
    count("worldline_segments", _segments(session, dimension_id, factor))
    dimension.duration = report.duration
    if base_unit is not None:
        dimension.base_unit = dict(base_unit)
    count("dimensions", 1)
    _drop_proposals(session, dimension_id)
    session.flush()
    for cache in (CALENDARS, WINDOWS, SERIES):
        cache.forget_vault(context.vault.id)
    report.slots = rebuild_time(context)
    session.flush()
    report.problems_after = _problems(session)
    return report


def _summary(
    session: Any, dimension: Dimension, factor: int, base_unit: dict[str, str] | None
) -> str:
    entity = session.get(Entity, dimension.entity_id)
    name = entity.name if entity is not None else "a dimension"
    old = dimension.base_unit.get("singular", "base unit")
    new = (base_unit or dimension.base_unit).get("plural", "base units")
    return f"Refined the base unit of {name}: 1 {old} is now {factor:,} {new}"


def _documents(session: Any, dimension_id: str, factor: int) -> dict[str, int]:
    """Recurrence rules and series bounds, entity fields and bodies, fact values, per-timeline
    notes and calendar definitions of the dimension."""
    rewritten: dict[str, int] = {}
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
    for event in session.scalars(select(Event).where(Event.timeline_id.in_(timelines))):
        if event.recurrence is None and event.original_start_t is None:
            continue
        if event.recurrence is not None:
            event.recurrence = refine_rule(event.recurrence, factor)
        if event.recurrence_resolved is not None:
            event.recurrence_resolved = refine_moments(event.recurrence_resolved, factor)
        for column in ("series_start_t", "series_end_t", "original_start_t"):
            value = getattr(event, column)
            if value is not None:
                setattr(event, column, value * factor)
        rewritten["events"] = rewritten.get("events", 0) + 1
    for entity in session.scalars(select(Entity).where(Entity.dimension_id == dimension_id)):
        fields, body = refine_json(entity.fields, factor), refine_json(entity.body, factor)
        if fields != entity.fields or body != entity.body:
            entity.fields, entity.body = fields, body
            rewritten["entities"] = rewritten.get("entities", 0) + 1
    rewritten["entity_facts"] = _fact_values(session, timelines, factor)
    for note in session.scalars(
        select(EntityTimelineNote).where(EntityTimelineNote.timeline_id.in_(timelines))
    ):
        body = refine_json(note.body, factor)
        if body != note.body:
            note.body = body
            rewritten["entity_timeline_notes"] = rewritten.get("entity_timeline_notes", 0) + 1
    for calendar in session.scalars(select(Calendar).where(Calendar.dimension_id == dimension_id)):
        calendar.definition = refine_definition(calendar.definition, factor)
        calendar.resolved_anchors = refine_moments(calendar.resolved_anchors, factor)
        calendar.definition_revision += 1
        rewritten["calendars"] = rewritten.get("calendars", 0) + 1
    return rewritten


def _drop_proposals(session: Any, dimension_id: str) -> None:
    """Pending calendar and recurrence proposals of the dimension were previewed in old units."""
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
    calendar_ids = select(Calendar.entity_id).where(Calendar.dimension_id == dimension_id)
    event_ids = select(Event.entity_id).where(Event.timeline_id.in_(timelines))
    session.execute(
        delete(Proposal).where(
            or_(Proposal.target_id.in_(calendar_ids), Proposal.target_id.in_(event_ids))
        )
    )


def _in_dimension(
    provider: SlotProvider, model: Any, dimension_column: str | None, dimension_id: str
) -> Any:
    column = dimension_column or provider.dimension_column
    if column is not None:
        return getattr(model, column) == dimension_id
    if provider.timeline_column is not None:
        timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
        return getattr(model, provider.timeline_column).in_(timelines)
    return None


def _column_slots(session: Any, provider: SlotProvider, dimension_id: str, factor: int) -> int:
    """The specs and last good moments of the provider's slots in columns."""
    model: Any = provider.model
    rewritten: set[Any] = set()
    for slot in provider._column_slots():
        assert slot.columns is not None
        spec_column, moment = slot.columns
        condition = _in_dimension(provider, model, slot.dimension_column, dimension_id)
        if condition is None:
            continue
        rows = session.scalars(
            select(model).where(
                condition, getattr(model, spec_column).is_not(None), *provider.where()
            )
        )
        for row in rows:
            spec = getattr(row, spec_column)
            if spec is None:  # JSON null
                continue
            setattr(row, spec_column, refine_json(dump_spec(spec), factor))
            t = getattr(row, moment)
            if t is not None:
                setattr(row, moment, t * factor)
            rewritten.add(getattr(row, provider.id_column))
    return len(rewritten)


def _field_slots(
    context: VaultContext, registry: SlotRegistry, dimension_id: str, factor: int
) -> int:
    """``entity_time_fields`` rows resolving in the dimension (an entity's own values: its home
    dimension; a fact's: its timeline's)."""
    session = context.session
    provider = registry.get(ENTITY_FIELD)
    if provider is None:
        return 0
    keys = provider.all_keys(session)
    loaded = registry.load(session, ENTITY_FIELD, keys)
    wanted = {
        (key.id, key.slot) for key, value in loaded.items() if value.dimension_id == dimension_id
    }
    rewritten = 0
    for row in session.scalars(select(EntityTimeField)):
        if (row.entity_id, row.field_key) not in wanted:
            continue
        row.spec = refine_json(dump_spec(row.spec), factor)
        if row.t is not None:
            row.t = row.t * factor
        rewritten += 1
    return rewritten


def _fact_values(session: Any, timelines: Any, factor: int) -> int:
    from lore.core.facts.models import EntityFact  # noqa: PLC0415 (import cycle)

    rewritten = 0
    for fact in session.scalars(select(EntityFact).where(EntityFact.timeline_id.in_(timelines))):
        value = refine_json(fact.value, factor)
        if value != fact.value:
            fact.value = value
            rewritten += 1
    return rewritten


def _correspondences(session: Any, dimension_id: str, factor: int) -> int:
    """Rates are B units per A unit: a finer A unit holds fewer of B's, a finer B more."""
    rewritten = 0
    for row in session.scalars(
        select(Correspondence).where(
            or_(
                Correspondence.dimension_a_id == dimension_id,
                Correspondence.dimension_b_id == dimension_id,
            )
        )
    ):
        a = row.dimension_a_id == dimension_id
        for column in ("rate_before", "rate_after"):
            rate = getattr(row, column)
            if rate is not None:
                setattr(
                    row, column, refine_rate(rate, 1, factor) if a else refine_rate(rate, factor)
                )
        rewritten += 1
    return rewritten


def _segments(session: Any, dimension_id: str, factor: int) -> int:
    """A segment's rate is subjective units (of the entity's personal clock dimension: its home
    dimension, else its first segment's) per unit of the segment's dimension."""
    first = (
        select(WorldlineSegment.entity_id, func.min(WorldlineSegment.seq).label("seq"))
        .group_by(WorldlineSegment.entity_id)
        .subquery()
    )
    first_dimension = dict(
        session.execute(
            select(WorldlineSegment.entity_id, WorldlineSegment.dimension_id).join(
                first,
                (first.c.entity_id == WorldlineSegment.entity_id)
                & (first.c.seq == WorldlineSegment.seq),
            )
        ).all()
    )
    homes = dict(session.execute(select(Entity.id, Entity.dimension_id).where(
        Entity.id.in_(select(WorldlineSegment.entity_id))
    )).all())  # fmt: skip
    rewritten = 0
    for row in session.scalars(select(WorldlineSegment)):
        clock = homes.get(row.entity_id) or first_dimension.get(row.entity_id)
        numerator = factor if clock == dimension_id else 1
        denominator = factor if row.dimension_id == dimension_id else 1
        if numerator == denominator:
            continue
        row.rate = refine_rate(row.rate, numerator, denominator)
        rewritten += 1
    return rewritten


def _problems(session: Any) -> int:
    """Event slots that don't resolve (the vault's most numerous time-bound records)."""
    found = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.time_status.is_not(None), Event.time_status.not_in(_GOOD))
    )
    return int(found or 0)


__all__ = ["REFINEMENT", "RefineReport", "refine_base_unit"]
