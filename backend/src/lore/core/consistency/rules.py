"""Core's consistency rules (``consistency.md`` §6).

Every rule has an incremental ``check(ctx, subjects)``, which returns all of its findings that
involve one of the subject entities, and a set-based ``scan(ctx)``. Rules comparing time points
use ``lore.core.consistency.compare`` (stored moments select the candidates in SQL; extents decide
definite or possible). Trashed entities have no findings.

- Hard rules from stored time statuses (``time-model.md`` §6): ``core.time.out_of_bounds``,
  ``core.time.cycle``, ``core.time.invalid_date`` (also a slot whose calendar doesn't compile),
  ``core.time.unresolved_anchor``; ``core.time.end_before_start`` from stored moments;
  ``core.calendar.invalid``; ``core.parent.cycle`` (one finding per cycle, every member a
  subject) and ``core.parent.not_allowed`` (kind or dimension).
- ``core.recurrence.invalid_rule`` (error, configurable): a series' rule no longer evaluates.
- ``core.time.anchor_to_trashed``, ``core.event.subevent_outside_parent`` (the child's span
  within its parent event's, series parents aside), ``core.event.effect_before_cause``
  (``core.causes`` in one dimension: the effect may not start before the cause): warnings.
- ``core.event.duplicate_name_same_time`` (off): two events of a timeline with the same name
  (ignoring case and accents) overlapping in time; possible when one start is circa.
"""

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import String, and_, func, or_, select, type_coerce
from sqlalchemy.orm import aliased

from lore.core.consistency.compare import DEFINITE, POSSIBLE, violates_order, worst
from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.db import Unindexed, unindexed
from lore.core.entities.models import Entity
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.models import Calendar, Event
from lore.core.time.series import check_rule, row_context, series_using
from lore.core.time.slots import SlotProvider
from lore.core.time.status import TimeStatus

EVENT = "event"
CORE_RECORD_TYPES = frozenset({"dimension", "timeline", EVENT, "calendar"})
_BATCH = 5000
TIME_RECORDS = (
    Trigger("record", EVENT),
    Trigger("record", "dimension"),
    Trigger("record", "timeline"),
)


def _chunks(ids: Iterable[str]) -> Iterator[list[str]]:
    wanted = sorted(set(ids))
    for start in range(0, len(wanted), _BATCH):
        yield wanted[start : start + _BATCH]


# --- slot statuses -------------------------------------------------------------------------------

_STATUS_LABELS = {
    TimeStatus.OUT_OF_BOUNDS: "lies outside the dimension's time",
    TimeStatus.CYCLE: "is part of an anchor cycle",
    TimeStatus.INVALID_DATE: "is no longer a valid date",
    TimeStatus.CALENDAR_ERROR: "uses a calendar that doesn't compile",
    TimeStatus.UNRESOLVED_REF: "is anchored to something that no longer exists",
    TimeStatus.TRASHED_REF: "is anchored to something in the trash",
}


def _status_providers(ctx: RuleContext) -> Iterator[tuple[SlotProvider, str, str]]:
    """Slot providers with a status column, their status column and their entity column."""
    for provider in ctx.registry.slot_registry().providers:
        model: Any = provider.model
        table = getattr(model, "__table__", None)
        columns = {slot.status_column for slot in provider.slots if slot.status_column}
        entity_column = (
            provider.id_column
            if provider.record_type in CORE_RECORD_TYPES
            else provider.entity_column
        )
        if table is None or entity_column is None or not ctx.has_table(table.name):
            continue
        for column in sorted(c for c in columns if c in table.columns):
            yield provider, column, entity_column


def _status_findings(
    ctx: RuleContext, rule_id: str, statuses: tuple[TimeStatus, ...], subjects: Iterable[str] | None
) -> Iterator[FindingDraft]:
    for provider, status_column, entity_column in _status_providers(ctx):
        model: Any = provider.model
        id_attr = getattr(model, provider.id_column)
        entity_attr = getattr(model, entity_column)
        status_attr = getattr(model, status_column)
        timeline_attr = (
            getattr(model, provider.timeline_column) if provider.timeline_column else None
        )
        columns = [id_attr, entity_attr, status_attr, Entity.name]
        if timeline_attr is not None:
            columns.append(timeline_attr)
        statement = (
            select(*columns)
            .join(Entity, Entity.id == entity_attr)
            .where(status_attr.in_([s.value for s in statuses]), Entity.deleted_at.is_(None))
        )
        batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
        for batch in batches:
            query = statement if batch is None else statement.where(entity_attr.in_(batch))
            for row in ctx.session.execute(query):
                record_id, entity_id, status, name = row[0], row[1], row[2], row[3]
                label = _STATUS_LABELS.get(TimeStatus(status), "doesn't resolve")
                yield FindingDraft(
                    rule_id,
                    (str(entity_id),),
                    f"The time of “{name}” {label}.",
                    discriminator=f"{provider.record_type}/{record_id}",
                    timeline_id=row[4] if timeline_attr is not None else None,
                    data={
                        "record_type": provider.record_type,
                        "record_id": str(record_id),
                        "status": status,
                    },
                )


def status_rule(
    rule_id: str,
    title: str,
    description: str,
    statuses: tuple[TimeStatus, ...],
    *,
    hard: bool = True,
) -> RuleDef:
    return RuleDef(
        id=rule_id,
        owner="core",
        title=title,
        description=description,
        category="structural" if hard else "narrative",
        default_severity="error" if hard else "warning",
        configurable=not hard,
        triggers=(Trigger("record", "*"),),
        check=lambda ctx, subjects: _status_findings(ctx, rule_id, statuses, subjects),
        scan=lambda ctx: _status_findings(ctx, rule_id, statuses, None),
    )


# --- ends before starts --------------------------------------------------------------------------


def _end_findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    rule_id = "core.time.end_before_start"
    for provider in ctx.registry.slot_registry().providers:
        model: Any = provider.model
        table = getattr(model, "__table__", None)
        entity_column = (
            provider.id_column
            if provider.record_type in CORE_RECORD_TYPES
            else provider.entity_column
        )
        if table is None or entity_column is None or not ctx.has_table(table.name):
            continue
        for slot in provider.slots:
            start = provider.slot(slot.start)
            if slot.spec != "end" or slot.columns is None or start is None or start.columns is None:
                continue
            end_attr = getattr(model, slot.columns[1])
            start_attr = getattr(model, start.columns[1])
            entity_attr = getattr(model, entity_column)
            statement = (
                select(getattr(model, provider.id_column), entity_attr, Entity.name)
                .join(Entity, Entity.id == entity_attr)
                .where(end_attr < start_attr, Entity.deleted_at.is_(None))
            )
            batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
            for batch in batches:
                query = statement if batch is None else statement.where(entity_attr.in_(batch))
                for record_id, entity_id, name in ctx.session.execute(query):
                    yield FindingDraft(
                        rule_id,
                        (str(entity_id),),
                        f"“{name}” ends before it starts.",
                        discriminator=f"{provider.record_type}/{record_id}/{slot.name}",
                    )


# --- calendars and parents -----------------------------------------------------------------------


def _calendar_findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    statement = (
        select(Calendar.entity_id, Entity.name)
        .join(Entity, Entity.id == Calendar.entity_id)
        .where(Calendar.compile_status != "ok", Entity.deleted_at.is_(None))
    )
    batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
    for batch in batches:
        query = statement if batch is None else statement.where(Calendar.entity_id.in_(batch))
        for calendar_id, name in ctx.session.execute(query):
            yield FindingDraft(
                "core.calendar.invalid",
                (calendar_id,),
                f"The calendar “{name}” no longer compiles.",
            )


def _parents(ctx: RuleContext) -> dict[str, str]:
    return dict(
        ctx.session.execute(  # type: ignore[arg-type]
            select(Entity.id, Entity.parent_id).where(Entity.parent_id.is_not(None))
        ).all()
    )


def _cycle_of(entity_id: str, parent_of: dict[str, str]) -> tuple[str, ...] | None:
    """The cycle the entity is on (its members from the entity on), if any."""
    path: list[str] = []
    seen: dict[str, int] = {}
    current: str | None = entity_id
    while current is not None and current not in seen:
        seen[current] = len(path)
        path.append(current)
        current = parent_of.get(current)
    if current is None or current != entity_id:
        return None
    return tuple(path)


def _cycle_drafts(
    cycles: Iterable[tuple[str, ...]], names: dict[str, str]
) -> Iterator[FindingDraft]:
    seen: set[frozenset[str]] = set()
    for cycle in cycles:
        members = frozenset(cycle)
        if members in seen:
            continue
        seen.add(members)
        listed = " → ".join(f"“{names.get(m, m)}”" for m in cycle)
        yield FindingDraft(
            "core.parent.cycle",
            tuple(sorted(members)),
            f"These entities are their own ancestors: {listed}.",
        )


def _names(ctx: RuleContext, ids: Iterable[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for batch in _chunks(ids):
        found: dict[str, str] = dict(
            ctx.session.execute(select(Entity.id, Entity.name).where(Entity.id.in_(batch))).all()
        )
        names.update(found)
    return names


def _ancestry(ctx: RuleContext, subjects: Iterable[str]) -> dict[str, str]:
    """The parents of the subjects and of their ancestors, level by level: a write is checked
    against the chains above what it touched, not against every entity's parent."""
    parent_of: dict[str, str] = {}
    looked_up: set[str] = set()
    frontier = set(subjects)
    while frontier:
        looked_up |= frontier
        found: dict[str, str] = {}
        for batch in _chunks(frontier):
            found.update(
                ctx.session.execute(  # type: ignore[arg-type]
                    select(Entity.id, Entity.parent_id).where(
                        Entity.id.in_(batch), Entity.parent_id.is_not(None)
                    )
                ).all()
            )
        parent_of.update(found)
        frontier = set(found.values()) - looked_up
    return parent_of


def _parent_cycle_check(ctx: RuleContext, subjects: frozenset[str]) -> Iterator[FindingDraft]:
    parent_of = _ancestry(ctx, subjects)
    cycles = [c for s in sorted(subjects) if (c := _cycle_of(s, parent_of)) is not None]
    yield from _cycle_drafts(cycles, _names(ctx, (m for c in cycles for m in c)))


def _parent_cycle_scan(ctx: RuleContext) -> Iterator[FindingDraft]:
    parent_of = _parents(ctx)
    done: set[str] = set()
    cycles = []
    for start in sorted(parent_of):
        if start in done:
            continue
        cycle = _cycle_of(start, parent_of)
        if cycle is not None:
            cycles.append(cycle)
            done.update(cycle)
    yield from _cycle_drafts(cycles, _names(ctx, done))


def _kinds(ctx: RuleContext) -> dict[str, tuple[str, ...]]:
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    enabled = enabled_modules(ctx.session, ctx.registry)
    return {k.key: k.definition.allowed_parents for k in ctx.registry.kinds_for(enabled)}


def _not_allowed(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    parent = aliased(Entity)
    statement = (
        select(
            Entity.id,
            Entity.name,
            Entity.kind,
            Entity.dimension_id,
            parent.name,
            parent.kind,
            parent.dimension_id,
        )
        .join(parent, parent.id == Entity.parent_id)
        .where(Entity.deleted_at.is_(None))
    )
    allowed = _kinds(ctx)
    batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
    for batch in batches:
        query = statement
        if batch is not None:  # the subjects as children, and their children
            query = query.where(or_(Entity.id.in_(batch), Entity.parent_id.in_(batch)))
        for (
            entity_id,
            name,
            kind,
            dimension,
            parent_name,
            parent_kind,
            parent_dimension,
        ) in ctx.session.execute(query):
            if kind not in allowed or parent_kind not in allowed:
                continue  # a disabled module's data is kept as it is
            if parent_kind not in allowed[kind]:
                message = f"“{name}” can't be placed under a {parent_kind} (“{parent_name}”)."
            elif not (
                dimension is None or parent_dimension is None or dimension == parent_dimension
            ):
                message = f"“{name}” is in another dimension than its parent “{parent_name}”."
            else:
                continue
            yield FindingDraft("core.parent.not_allowed", (entity_id,), message)


# --- recurrence rules ----------------------------------------------------------------------------


def _series_findings(ctx: RuleContext, rows: Iterable[Event]) -> Iterator[FindingDraft]:
    from lore.core.time.models import Timeline  # noqa: PLC0415

    for row in rows:
        entity = ctx.session.get(Entity, row.entity_id)
        timeline = ctx.session.get(Timeline, row.timeline_id)
        if entity is None or entity.deleted_at is not None or timeline is None:
            continue
        resolver = ctx.resolver(timeline.dimension_id)
        if resolver is None:
            continue
        found = row_context(resolver, row)
        problem = found if not isinstance(found, tuple) else check_rule(*found)
        if problem is not None and problem.code != "rule.unresolved":
            yield FindingDraft(
                "core.recurrence.invalid_rule",
                (row.entity_id,),
                f"The recurrence rule of “{entity.name}” no longer works: {problem.message}",
                data={"code": problem.code, "path": problem.path},
            )


def _series_rows(ctx: RuleContext, subjects: Iterable[str] | None) -> list[Event]:
    statement = select(Event).where(Event.recurrence.is_not(None), Event.overrides_id.is_(None))
    if subjects is None:
        return list(ctx.session.scalars(statement))
    ids = set(subjects)
    # Only a calendar has dependent series: series_using reads every series, so it runs once per
    # calendar among the subjects, not once per subject.
    calendars = ctx.session.scalars(
        select(Entity.id).where(Entity.id.in_(sorted(ids)), Entity.kind == "calendar")
    ).all()
    for calendar_id in calendars:
        ids.update(series_using(ctx.session, calendar_id))
    dimensions = ctx.session.scalars(
        select(Entity.id).where(Entity.id.in_(sorted(ids)), Entity.kind == "dimension")
    ).all()
    if dimensions:
        ids.update(
            ctx.session.scalars(
                select(Entity.id).where(Entity.dimension_id.in_(dimensions), Entity.kind == EVENT)
            )
        )
    rows: list[Event] = []
    for batch in _chunks(ids):
        rows += ctx.session.scalars(statement.where(Event.entity_id.in_(batch)))
    return rows


# --- event relations -----------------------------------------------------------------------------


def _event_columns() -> tuple[Any, Any, Any, Any]:
    child, parent = aliased(Event), aliased(Event)
    child_entity, parent_entity = aliased(Entity), aliased(Entity)
    return child, parent, child_entity, parent_entity


def _plain(table: Any, column: str) -> Any:
    """``column IS NULL`` as a condition SQLite won't pick an index for (nearly every row meets
    it: not in the trash, not an override, not a series)."""
    return unindexed(getattr(table, column)).is_(None)


def _once(ctx: RuleContext, statements: Iterable[Any]) -> list[Any]:
    """The rows of several statements about pairs (their first two columns), each pair once."""
    found: dict[tuple[str, str], Any] = {}
    for statement in statements:
        for row in ctx.session.execute(statement):
            found.setdefault((row[0], row[1]), row)
    return list(found.values())


type _Slot = tuple[str, str]  # event id, slot


class _Orders:
    """Required orders ``a ≤ b`` between event slots, checked together: the slots are loaded
    in sets (``RuleContext.preload``), and only those of the orders that their stored moments
    violate. Either kind of violation needs ``t(a) > t(b)`` (``compare.py``)."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self._wanted: dict[str, set[_Slot]] = {}

    def want(self, dimension_id: str, a: _Slot, a_t: int | None, b: _Slot, b_t: int | None) -> bool:
        """Note the slots of an order to check later; whether it can be violated at all."""
        if a_t is None or b_t is None or a_t <= b_t:
            return False
        self._wanted.setdefault(dimension_id, set()).update((a, b))
        return True

    def load(self) -> None:
        for dimension_id, slots in self._wanted.items():
            self.ctx.preload(dimension_id, EVENT, slots)
        self._wanted.clear()

    def violated(self, dimension_id: str, a: _Slot, b: _Slot) -> Any:
        """How certainly ``a ≤ b`` is violated."""
        first = self.ctx.point(dimension_id, EVENT, *a)
        second = self.ctx.point(dimension_id, EVENT, *b)
        if first is None or second is None:
            return None
        return violates_order(first, second)


def _subevent_findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    child, parent, child_entity, parent_entity = _event_columns()
    statement = (
        select(
            child.entity_id,
            parent.entity_id,
            child_entity.name,
            parent_entity.name,
            child_entity.dimension_id,
            child.timeline_id,
            child.start_t,
            child.end_t,
            parent.start_t,
            parent.end_t,
        )
        .join(child_entity, child_entity.id == child.entity_id)
        .join(parent_entity, parent_entity.id == child_entity.parent_id)
        .join(parent, and_(parent.entity_id == parent_entity.id, _plain(parent, "overrides_id")))
        .where(
            # What nearly every row meets is kept from picking an index: a check must go from
            # its subjects (ids, parent ids) to the rest.
            _plain(child, "overrides_id"),
            _plain(child_entity, "deleted_at"),
            _plain(parent_entity, "deleted_at"),
            unindexed(parent_entity.kind) == EVENT,
            _plain(parent, "recurrence"),
            # Either violation needs a later moment (compare.py): the candidates.
            or_(child.start_t < parent.start_t, child.end_t > parent.end_t),
        )
    )
    batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
    for batch in batches:
        # The subjects as children, then as parents: each through its index (as one condition,
        # SQLite reads every event to check a single one).
        sides = (
            [statement]
            if batch is None
            else [
                statement.where(child.entity_id.in_(batch)),
                statement.where(child_entity.parent_id.in_(batch)),
            ]
        )
        orders = _Orders(ctx)
        candidates = []
        for row in _once(ctx, sides):
            child_id, parent_id, _name, _parent_name, dimension_id, _timeline_id = row[:6]
            child_start, child_end, parent_start, parent_end = row[6:]
            if dimension_id is None:
                continue
            starts = ((parent_id, "start"), (child_id, "start"))
            ends = ((child_id, "end"), (parent_id, "end"))
            checked = [
                order
                for order, a_t, b_t in ((starts, parent_start, child_start),
                                        (ends, child_end, parent_end))
                if orders.want(dimension_id, order[0], a_t, order[1], b_t)
            ]  # fmt: skip
            candidates.append((row, checked))
        orders.load()
        for row, checked in candidates:
            child_id, parent_id, name, parent_name, dimension_id, timeline_id = row[:6]
            certainty = worst(*(orders.violated(dimension_id, a, b) for a, b in checked))
            if certainty is not None:
                yield FindingDraft(
                    "core.event.subevent_outside_parent",
                    (child_id, parent_id),
                    f"“{name}” lies outside its parent event “{parent_name}”.",
                    certainty=certainty,
                    timeline_id=timeline_id,
                )


def _causality_scan() -> Any:
    """Every candidate, from one pass over the events: the live home rows are set aside
    (materialized) with their starts and each ``core.causes`` link looks its two ends up there,
    instead of in two tables each (a large world has 100k such links, #235)."""
    started = (
        select(
            Event.entity_id.label("id"),
            Event.timeline_id.label("timeline_id"),
            Event.start_t.label("start_t"),
            Entity.name.label("name"),
            Entity.dimension_id.label("dimension_id"),
        )
        .join(Entity, Entity.id == Event.entity_id)
        .where(Event.overrides_id.is_(None), Entity.deleted_at.is_(None))
        .cte("started_events")
        .prefix_with("MATERIALIZED")
    )
    cause, effect = started.alias("cause"), started.alias("effect")
    return (
        select(
            Link.source_id,
            Link.target_id,
            cause.c.name,
            effect.c.name,
            cause.c.dimension_id,
            effect.c.timeline_id,
            cause.c.start_t,
            effect.c.start_t,
        )
        .join(cause, cause.c.id == Link.source_id)
        .join(effect, effect.c.id == Link.target_id)
        .where(
            Link.link_type == "core.causes",
            Link.deleted_at.is_(None),
            # Only the links join the two ends (never one end to every other of its dimension).
            unindexed(cause.c.dimension_id) == unindexed(effect.c.dimension_id),
            unindexed(effect.c.start_t) < unindexed(cause.c.start_t),
        )
    )


def _causality_findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    cause, effect, cause_entity, effect_entity = _event_columns()
    statement = (
        select(
            Link.source_id,
            Link.target_id,
            cause_entity.name,
            effect_entity.name,
            cause_entity.dimension_id,
            effect.timeline_id,
            cause.start_t,
            effect.start_t,
        )
        .join(cause_entity, cause_entity.id == Link.source_id)
        .join(effect_entity, effect_entity.id == Link.target_id)
        .join(cause, and_(cause.entity_id == Link.source_id, _plain(cause, "overrides_id")))
        .join(effect, and_(effect.entity_id == Link.target_id, _plain(effect, "overrides_id")))
        .where(
            Link.link_type == "core.causes",  # with the subject: (source, type), (target, type)
            _plain(Link, "deleted_at"),
            _plain(cause_entity, "deleted_at"),
            _plain(effect_entity, "deleted_at"),
            unindexed(cause_entity.dimension_id) == unindexed(effect_entity.dimension_id),
            effect.start_t < cause.start_t,
        )
    )
    batches: Iterable[list[str] | None] = [None] if subjects is None else _chunks(subjects)
    for batch in batches:
        sides = (
            [_causality_scan()]
            if batch is None
            else [
                statement.where(Link.source_id.in_(batch)),
                statement.where(Link.target_id.in_(batch)),
            ]
        )
        orders = _Orders(ctx)
        candidates = _once(ctx, sides)
        for cause_id, effect_id, *_names, dimension_id, _timeline, cause_t, effect_t in candidates:
            orders.want(dimension_id, (cause_id, "start"), cause_t, (effect_id, "start"), effect_t)
        orders.load()
        for (
            cause_id,
            effect_id,
            cause_name,
            effect_name,
            dimension_id,
            timeline_id,
            _cause_t,
            _effect_t,
        ) in candidates:
            certainty = orders.violated(dimension_id, (cause_id, "start"), (effect_id, "start"))
            if certainty is not None:
                yield FindingDraft(
                    "core.event.effect_before_cause",
                    (effect_id, cause_id),
                    f"“{effect_name}” starts before its cause “{cause_name}”.",
                    certainty=certainty,
                    timeline_id=timeline_id,
                )


def _overlap(a: Any, b: Any) -> Any:
    """``time-model.md`` §2.1 overlap of two event rows (instants included)."""
    a_instant, b_instant = a.start_t == a.end_t, b.start_t == b.end_t
    return or_(
        and_(a.start_t < b.end_t, b.start_t < a.end_t),
        and_(a_instant, b.start_t <= a.start_t, a.start_t < b.end_t),
        and_(b_instant, a.start_t <= b.start_t, b.start_t < a.end_t),
        and_(a_instant, b_instant, a.start_t == b.start_t),
    )


def _duplicate_drafts(rows: Iterable[Any]) -> Iterator[FindingDraft]:
    """Findings of ``(event, other event, name, timeline, circa, circa)`` rows, once per pair."""
    seen: set[tuple[str, str]] = set()
    for a_id, b_id, name, timeline_id, a_circa, b_circa in rows:
        pair = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        if pair in seen:
            continue
        seen.add(pair)
        yield FindingDraft(
            "core.event.duplicate_name_same_time",
            pair,
            f"Two events named “{name}” overlap in time.",
            certainty=POSSIBLE if a_circa or b_circa else DEFINITE,
            timeline_id=timeline_id,
        )


def _circa(row: Any) -> Any:
    """Whether an event row's start is circa (from the stored document)."""
    return func.coalesce(func.json_extract(type_coerce(row.start_spec, String), "$.approximate"), 0)


def _duplicate_scan(ctx: RuleContext) -> Iterator[FindingDraft]:
    """Every pair, from one pass over the events: the live, non-recurring home rows are set
    aside (materialized) with their names and joined to themselves on timeline and name. Joining
    the tables themselves fetched a million rows one by one on a large world (#235)."""
    named = (
        select(
            Event.entity_id.label("id"),
            Event.timeline_id.label("timeline_id"),
            Entity.sort_name.label("sort_name"),
            Entity.name.label("name"),
            Event.start_t.label("start_t"),
            Event.end_t.label("end_t"),
            _circa(Event).label("circa"),
        )
        .join(Entity, Entity.id == Event.entity_id)
        .where(
            Event.overrides_id.is_(None),
            Event.recurrence.is_(None),
            Entity.deleted_at.is_(None),
        )
        .cte("named_events")
        .prefix_with("MATERIALIZED")
    )
    first, second = named.alias("a"), named.alias("b")
    statement = select(
        first.c.id, second.c.id, first.c.name, first.c.timeline_id, first.c.circa, second.c.circa
    ).join_from(
        first,
        second,
        and_(
            second.c.timeline_id == first.c.timeline_id,
            second.c.sort_name == first.c.sort_name,
            second.c.id > first.c.id,
            _overlap(first.c, second.c),
        ),
    )
    yield from _duplicate_drafts(ctx.session.execute(statement))


def _duplicate_findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    if subjects is None:
        yield from _duplicate_scan(ctx)
        return
    first, second, first_entity, second_entity = _event_columns()
    # From a subject to the events of the same name, through the (kind, name) index, and only
    # then to their rows: the other event's columns are kept from picking an index, or SQLite
    # walks half the timeline for each subject.
    other = Unindexed(second)
    statement = (
        select(
            first.entity_id,
            second.entity_id,
            first_entity.name,
            first.timeline_id,
            _circa(first),
            _circa(second),
        )
        .join(first_entity, first_entity.id == first.entity_id)
        .join(
            second_entity,
            and_(
                second_entity.kind == EVENT,
                second_entity.sort_name == first_entity.sort_name,
                second_entity.id != first_entity.id,
            ),
        )
        .join(second, second.entity_id == second_entity.id)
        .where(
            first.overrides_id.is_(None),
            other.overrides_id.is_(None),
            first.recurrence.is_(None),
            other.recurrence.is_(None),
            first_entity.deleted_at.is_(None),
            second_entity.deleted_at.is_(None),
            other.timeline_id == first.timeline_id,
            _overlap(first, other),
        )
    )
    rows: list[Any] = []
    for batch in _chunks(subjects):
        rows += ctx.session.execute(statement.where(first.entity_id.in_(batch))).all()
    yield from _duplicate_drafts(rows)


# --- the catalog ---------------------------------------------------------------------------------


def _rule(
    rule_id: str,
    title: str,
    description: str,
    finder: Any,
    *,
    triggers: tuple[Trigger, ...],
    severity: str = "error",
    configurable: bool = False,
    category: str = "structural",
) -> RuleDef:
    return RuleDef(
        id=rule_id,
        owner="core",
        title=title,
        description=description,
        category=category,  # type: ignore[arg-type]
        default_severity=severity,  # type: ignore[arg-type]
        configurable=configurable,
        triggers=triggers,
        check=finder,
        scan=lambda ctx: finder(ctx, None),
    )


CORE_RULES: tuple[RuleDef, ...] = (
    status_rule(
        "core.time.out_of_bounds",
        "Time outside the dimension",
        "A resolved moment lies before the inception or after the end of its dimension. Change "
        "the date, or the dimension's duration.",
        (TimeStatus.OUT_OF_BOUNDS,),
    ),
    _rule(
        "core.time.end_before_start",
        "Ends before it starts",
        "A record's end lies before its start. Change one of them.",
        _end_findings,
        triggers=(Trigger("record", "*"),),
    ),
    status_rule(
        "core.time.cycle",
        "Anchor cycle",
        "Time points are anchored to each other in a loop. Anchor one of them elsewhere.",
        (TimeStatus.CYCLE,),
    ),
    status_rule(
        "core.time.invalid_date",
        "Invalid date",
        "A date typed in a calendar no longer exists in it (after a calendar change), or its "
        "calendar doesn't compile. Pick a valid date or pin the moment.",
        (TimeStatus.INVALID_DATE, TimeStatus.CALENDAR_ERROR),
    ),
    status_rule(
        "core.time.unresolved_anchor",
        "Unresolved anchor",
        "A time point is anchored to something that no longer exists. Anchor it elsewhere.",
        (TimeStatus.UNRESOLVED_REF,),
    ),
    _rule(
        "core.calendar.invalid",
        "Calendar doesn't compile",
        "A calendar's definition no longer compiles with its anchors' moments. Fix the "
        "definition or what its anchors point at.",
        _calendar_findings,
        triggers=(Trigger("record", "calendar"),),
    ),
    _rule(
        "core.parent.cycle",
        "Parent cycle",
        "Entities are their own ancestors. Move one of them elsewhere.",
        lambda ctx, subjects: (
            _parent_cycle_scan(ctx) if subjects is None else _parent_cycle_check(ctx, subjects)
        ),
        triggers=(Trigger("record", "*"),),
    ),
    _rule(
        "core.parent.not_allowed",
        "Parent not allowed",
        "An entity's parent is of a kind it can't be placed under, or in another dimension. "
        "Move it.",
        _not_allowed,
        triggers=(Trigger("record", "*"),),
    ),
    _rule(
        "core.recurrence.invalid_rule",
        "Invalid recurrence rule",
        "A recurring event's rule no longer evaluates, usually after a calendar change (a month "
        "or level it names is gone). Edit the rule.",
        lambda ctx, subjects: _series_findings(ctx, _series_rows(ctx, subjects)),
        triggers=(*TIME_RECORDS, Trigger("record", "calendar")),
        configurable=True,
    ),
    status_rule(
        "core.time.anchor_to_trashed",
        "Anchored to the trash",
        "A time point is anchored to a record in the trash. It still resolves; restore the "
        "record, or anchor the time point elsewhere before purging it.",
        (TimeStatus.TRASHED_REF,),
        hard=False,
    ),
    _rule(
        "core.event.subevent_outside_parent",
        "Sub-event outside its parent",
        "A sub-event's span isn't within its parent event's span.",
        _subevent_findings,
        triggers=(Trigger("record", EVENT),),
        severity="warning",
        configurable=True,
        category="narrative",
    ),
    _rule(
        "core.event.effect_before_cause",
        "Effect before cause",
        "An event starts before the event that causes it (same dimension).",
        _causality_findings,
        triggers=(Trigger("record", EVENT), Trigger("link_type", "core.causes")),
        severity="warning",
        configurable=True,
        category="narrative",
    ),
    _rule(
        "core.event.duplicate_name_same_time",
        "Duplicate event",
        "Two events of a timeline have the same name and overlap in time.",
        _duplicate_findings,
        triggers=(Trigger("record", EVENT),),
        severity="off",
        configurable=True,
        category="narrative",
    ),
)

__all__ = ["CORE_RULES"]
