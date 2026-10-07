"""Recurring series (``recurrence.md`` §1, §2, §4, §5.5, §9; ``time-model.md`` §9.5).

An event whose ``events.recurrence`` holds a rule is a **series**. Occurrences are computed on
demand with ``lore.chronology.recurrence`` and never stored in bulk (R-REC-1, ADR-0009).

- **Rule slots.** The rule's time points are slots of the event (``time-model.md`` §6), so they
  can be anchored and propagate: ``recurrence_until`` (``limit.until``) and
  ``exclusion:<i>.from`` / ``exclusion:<i>.to``. Their resolved moments are stored in
  ``events.recurrence_resolved`` by JSON pointer into the rule (``/limit/until``,
  ``/exclusions/<i>/from``), which is the engine's ``RecurrenceContext.resolved``.
- **Calendar.** A calendar rule's calendar must be a calendar of the event's dimension. It is also
  the calendar of a calendar duration (the engines take one calendar): a series' calendar duration
  must use it (decided with #52), an interval rule's may use any calendar of the dimension.
- **Series bounds** (§5.5): ``series_start_t`` is the first occurrence's start and
  ``series_end_t`` the last occurrence's end (``D`` for ``never``); both are NULL when the series
  has no occurrence. They are refreshed by propagation (``refresh_series``) whenever the event's
  slots, the rule's calendar or the dimension's duration change.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.calendar.compile import ValidationError as RuleError
from lore.chronology.calendar.compiled import CompiledCalendar
from lore.chronology.recurrence import (
    Occurrence,
    RecurrenceContext,
    RecurrenceError,
    expand,
    occurrence,
    occurrence_number,
    series_bounds,
)
from lore.chronology.recurrence import validate_rule as engine_validate
from lore.chronology.schema import (
    CalendarDuration,
    CalendarRule,
    DurationEnd,
    EndSpec,
    IntervalRule,
    NeverLimit,
    RecurrenceRule,
    TimePoint,
    UntilLimit,
)
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import Event, Timeline
from lore.core.time.resolve import Resolution, Resolver
from lore.core.time.slots import SlotKey, SlotMoment, SlotUpdate, SlotValue, SpecUpdate
from lore.core.time.specs import dump_spec, parse_end_spec
from lore.core.time.status import TimeStatus
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

EVENT = "event"
UNTIL_SLOT = "recurrence_until"
UNTIL_POINTER = "/limit/until"
RULE_SLOT = "recurrence"
"""The slot name violations of the rule itself are reported under."""

type Rule = CalendarRule | IntervalRule
_RULE: TypeAdapter[Rule] = TypeAdapter(RecurrenceRule)


def parse_rule(document: Any) -> Rule:
    """A rule document (pydantic's ``ValidationError`` when it isn't one)."""
    return _RULE.validate_python(document)


def dump_rule(rule: Rule) -> dict[str, Any]:
    """The JSON document stored for a rule (defaults included, like specs)."""
    document: dict[str, Any] = _RULE.dump_python(rule, mode="json", by_alias=True)
    return document


# --- the rule's time points ----------------------------------------------------------------------


def rule_points(rule: Rule) -> dict[str, tuple[str, TimePoint]]:
    """Slot name → (JSON pointer into the rule, time point) of the rule's time points."""
    found: dict[str, tuple[str, TimePoint]] = {}
    if isinstance(rule.limit, UntilLimit):
        found[UNTIL_SLOT] = (UNTIL_POINTER, rule.limit.until)
    for i, exclusion in enumerate(rule.exclusions):
        found[f"exclusion:{i}.from"] = (f"/exclusions/{i}/from", exclusion.from_)
        found[f"exclusion:{i}.to"] = (f"/exclusions/{i}/to", exclusion.to)
    return found


def stored_rule(row: Event) -> Rule | None:
    return None if row.recurrence is None else parse_rule(row.recurrence)


def _points_of(row: Event) -> dict[str, tuple[str, TimePoint]]:
    rule = stored_rule(row)
    return {} if rule is None else rule_points(rule)


def _series_rows(session: Session, ids: Iterable[str]) -> dict[str, Event]:
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    rows = session.scalars(
        select(Event).where(Event.entity_id.in_(wanted), Event.overrides_id.is_(None))
    )
    return {row.entity_id: row for row in rows}


def load_rule_slots(session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    rows = _series_rows(session, (key.id for key in keys))
    timelines = {row.timeline_id for row in rows.values()}
    dimensions: dict[str, str] = dict(
        session.execute(
            select(Timeline.entity_id, Timeline.dimension_id).where(
                Timeline.entity_id.in_(sorted(timelines))
            )
        ).all()
    )
    trashed = set(
        session.scalars(
            select(Entity.id).where(Entity.id.in_(sorted(rows)), Entity.deleted_at.is_not(None))
        )
    )
    result: dict[SlotKey, SlotValue] = {}
    for key in keys:
        row = rows.get(key.id)
        found = None if row is None else _points_of(row).get(key.slot)
        if row is None or found is None:
            continue
        pointer, point = found
        t = (row.recurrence_resolved or {}).get(pointer)
        result[key] = SlotValue(
            spec=point,
            t=None if t is None else int(t),
            status=None if row.time_status is None else TimeStatus(row.time_status),
            trashed=key.id in trashed,
            dimension_id=dimensions.get(row.timeline_id),
        )
    return result


def write_rule_slots(session: Session, updates: Sequence[SlotUpdate]) -> None:
    rows = _series_rows(session, (update.key.id for update in updates))
    for update in updates:
        row = rows.get(update.key.id)
        found = None if row is None else _points_of(row).get(update.key.slot)
        if row is None or found is None:
            continue
        resolved = dict(row.recurrence_resolved or {})
        if update.t is None:
            resolved.pop(found[0], None)
        else:
            resolved[found[0]] = str(update.t)
        row.recurrence_resolved = resolved
        row.time_status = update.status.value


def write_rule_specs(session: Session, updates: Sequence[SpecUpdate]) -> None:
    """New specs for the rule's time points (anchor freezing): the rule document changes."""
    rows = _series_rows(session, (update.key.id for update in updates))
    for update in updates:
        row = rows.get(update.key.id)
        found = None if row is None else _points_of(row).get(update.key.slot)
        if row is None or row.recurrence is None or found is None:
            continue
        document = dict(row.recurrence)
        parts = [p for p in found[0].split("/") if p]
        node: Any = document
        for part in parts[:-1]:
            child = node[int(part)] if isinstance(node, list) else node[part]
            child = list(child) if isinstance(child, list) else dict(child)
            if isinstance(node, list):
                node[int(part)] = child
            else:
                node[part] = child
            node = child
        node[parts[-1]] = dump_spec(update.spec)
        row.recurrence = document
        row.revision += 1


def rule_slot_keys(session: Session) -> list[SlotKey]:
    """Every rule time point of every series."""
    rows = session.scalars(
        select(Event).where(Event.recurrence.is_not(None)).order_by(Event.entity_id)
    )
    return [SlotKey(row.entity_id, slot) for row in rows for slot in _points_of(row)]


def rule_moments_beyond(session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
    rows = session.scalars(
        select(Event).where(Event.recurrence.is_not(None), Event.timeline_id.in_(timelines))
    )
    found: list[SlotMoment] = []
    for row in rows:
        resolved = row.recurrence_resolved or {}
        for slot, (pointer, _point) in _points_of(row).items():
            t = resolved.get(pointer)
            if t is not None and int(t) > bound:
                found.append(SlotMoment(EVENT, row.entity_id, slot, int(t)))
    return found


# --- evaluation context --------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleProblem:
    """Why a rule can't be evaluated: an engine error (``code``, ``path`` into the rule, or
    ``/end…`` into the series)."""

    code: str
    path: str
    message: str


def _calendar_of(rule: Rule | None, end: EndSpec) -> tuple[str | None, str]:
    """The calendar the engine needs and the path naming it."""
    if isinstance(rule, CalendarRule):
        return rule.calendar_id, "/calendar_id"
    if isinstance(end, DurationEnd) and isinstance(end.duration, CalendarDuration):
        return end.duration.calendar_id, "/end/duration/calendar_id"
    return None, ""


def recurrence_context(
    resolver: Resolver,
    rule: Rule,
    series_start: int,
    end: EndSpec,
    resolved: dict[str, int],
) -> RecurrenceContext | RuleProblem:
    """The engine's context for a rule of the resolver's dimension, or why there is none (the
    rule's calendar isn't one of the dimension's, doesn't compile, or the series' calendar
    duration uses another calendar)."""
    calendar_id, path = _calendar_of(rule, end)
    calendar: CompiledCalendar | None = None
    if calendar_id is not None:
        found = resolver.calendars.get(calendar_id, path)
        if isinstance(found, Resolution):
            return RuleProblem(
                "rule.unknown_calendar", path, "The rule's calendar isn't a calendar of the "
                "event's dimension, or it doesn't compile."
            )  # fmt: skip
        calendar = found
    if (
        isinstance(rule, CalendarRule)
        and isinstance(end, DurationEnd)
        and isinstance(end.duration, CalendarDuration)
        and end.duration.calendar_id != rule.calendar_id
    ):
        return RuleProblem(
            "rule.unknown_calendar", "/end/duration/calendar_id",
            "A series' calendar duration must use the rule's calendar.",
        )  # fmt: skip
    return RecurrenceContext(
        series_start=series_start,
        end=end,
        dimension_duration=resolver.duration,
        calendar=calendar,
        resolved=resolved,
    )


def check_rule(rule: Rule, ctx: RecurrenceContext) -> RuleProblem | None:
    """The first error of ``validate_rule`` (warnings don't count), or of evaluating the rule's
    bounds (``rule.too_many_positions``, ``rule.too_complex_to_count``)."""
    try:
        errors = [e for e in engine_validate(rule, ctx) if e.severity == "error"]
    except RecurrenceError as exc:
        return RuleProblem(exc.code, "", str(exc))
    if errors:
        first: RuleError = errors[0]
        return RuleProblem(first.code, first.path, first.message)
    return None


def bounds_of(rule: Rule, ctx: RecurrenceContext) -> tuple[int | None, int | None]:
    """``(series_start_t, series_end_t)`` (§5.5): NULL both without occurrences."""
    bounds = series_bounds(rule, ctx)
    if bounds.first_start is None:
        return None, None
    if isinstance(rule.limit, NeverLimit):
        return bounds.first_start, ctx.dimension_duration
    return bounds.first_start, bounds.last_end


def row_context(resolver: Resolver, row: Event) -> tuple[Rule, RecurrenceContext] | RuleProblem:
    """A stored series' rule and context (from its stored moments)."""
    rule = stored_rule(row)
    if rule is None or row.start_t is None:
        return RuleProblem("rule.unresolved", "", "The series has no rule or no start.")
    resolved = {pointer: int(t) for pointer, t in (row.recurrence_resolved or {}).items()}
    ctx = recurrence_context(resolver, rule, row.start_t, parse_end_spec(row.end_spec), resolved)
    return ctx if isinstance(ctx, RuleProblem) else (rule, ctx)


# --- propagation: series bounds ------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesProblem:
    entity_id: str
    code: str
    message: str


def refresh_series(
    context: VaultContext,
    event_ids: Iterable[str],
    calendar_ids: Iterable[str],
    dimension_ids: Iterable[str],
) -> tuple[list[SeriesProblem], set[str]]:
    """Recompute the bounds of the series among ``event_ids``, of every series whose rule (or
    calendar duration) uses one of ``calendar_ids`` and of every series in ``dimension_ids``
    (``recurrence.md`` §5.5). Events that stopped being series lose their bounds. A rule that no
    longer evaluates keeps its last bounds and is reported. Returns the problems and the ids of
    the series looked at."""
    session = context.session
    session.flush()
    rows = list(_series_rows(session, event_ids).values())
    seen = {row.id for row in rows}
    for row in [*_using(session, set(calendar_ids)), *_in_dimensions(session, set(dimension_ids))]:
        if row.id not in seen:
            rows.append(row)
            seen.add(row.id)
    problems: list[SeriesProblem] = []
    resolvers: dict[str, Resolver] = {}
    for row in sorted(rows, key=lambda r: r.entity_id):
        if row.recurrence is None:
            _set_bounds(row, None, None)
            continue
        timeline = session.get(Timeline, row.timeline_id)
        if timeline is None:
            continue
        if timeline.dimension_id not in resolvers:
            resolvers[timeline.dimension_id] = Resolver(context, timeline.dimension_id)
        found = row_context(resolvers[timeline.dimension_id], row)
        problem = found if isinstance(found, RuleProblem) else check_rule(*found)
        if problem is not None:
            problems.append(SeriesProblem(row.entity_id, problem.code, problem.message))
            continue
        assert not isinstance(found, RuleProblem)
        _set_bounds(row, *bounds_of(*found))
    return problems, {row.entity_id for row in rows if row.recurrence is not None}


def _all_series(session: Session) -> Iterable[Event]:
    return session.scalars(
        select(Event).where(Event.recurrence.is_not(None), Event.overrides_id.is_(None))
    )


def _using(session: Session, calendar_ids: set[str]) -> list[Event]:
    """The series whose rule (or calendar duration) uses one of the calendars."""
    if not calendar_ids:
        return []
    return [
        row
        for row in _all_series(session)
        if _calendar_of(stored_rule(row), parse_end_spec(row.end_spec))[0] in calendar_ids
    ]


def _in_dimensions(session: Session, dimension_ids: set[str]) -> list[Event]:
    if not dimension_ids:
        return []
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id.in_(sorted(dimension_ids)))
    return list(
        session.scalars(
            select(Event).where(
                Event.recurrence.is_not(None),
                Event.overrides_id.is_(None),
                Event.timeline_id.in_(timelines),
            )
        )
    )


def series_using(session: Session, calendar_id: str) -> list[str]:
    """Ids of the series whose occurrences depend on a calendar (its rule's or its duration's):
    they count as the calendar's dependents (``time-model.md`` §7.4)."""
    return sorted(row.entity_id for row in _using(session, {calendar_id}))


def _set_bounds(row: Event, start: int | None, end: int | None) -> None:
    if row.series_start_t != start:
        row.series_start_t = start
    if row.series_end_t != end:
        row.series_end_t = end


# --- occurrences --------------------------------------------------------------------------------

REFERENCED = "referenced"
MODIFIED = "modified"
CANCELLED = "cancelled"
OCCURRENCE_STATES = (REFERENCED, MODIFIED, CANCELLED)


def occurrence_point(series_id: str, slot: str, key: str) -> TimePoint:
    """``relative(ref = {event: series, slot, occurrence: key}, 0)`` (``recurrence.md`` §7)."""
    return TimePoint.model_validate(
        {
            "anchor": {
                "kind": "relative",
                "ref": {"type": EVENT, "id": series_id, "slot": slot, "occurrence": key},
                "offset": {"kind": "base", "units": "0"},
            },
            "precision": "base",
        }
    )


def is_occurrence_point(point: Any, series_id: str, slot: str, key: str) -> bool:
    """Whether a spec is the default anchor of a referenced occurrence's slot."""
    return dump_spec(point) == dump_spec(occurrence_point(series_id, slot, key))


def compute_occurrence(
    resolver: Resolver, row: Event, key: str, *, series_start: int | None = None,
    resolved: dict[str, int] | None = None,
) -> Occurrence | RuleProblem:  # fmt: skip
    """A series' computed occurrence ``key`` (``not_found`` as a problem). ``series_start`` and
    ``resolved`` replace the stored moments (a propagation run's new values)."""
    rule = stored_rule(row)
    start = row.start_t if series_start is None else series_start
    if rule is None or start is None:
        return RuleProblem("not_a_series", "", "The event doesn't recur.")
    if resolved is None:
        resolved = {pointer: int(t) for pointer, t in (row.recurrence_resolved or {}).items()}
    ctx = recurrence_context(resolver, rule, start, parse_end_spec(row.end_spec), resolved)
    if isinstance(ctx, RuleProblem):
        return ctx
    try:
        return occurrence(rule, ctx, key)
    except RecurrenceError as exc:
        return RuleProblem(exc.code, "", str(exc))


def materialized(session: Session, series_ids: Iterable[str], *, live: bool = True) -> list[Event]:
    """The materialized occurrences of series (home rows; ``live``: not in the trash)."""
    wanted = sorted(set(series_ids))
    if not wanted:
        return []
    statement = select(Event).where(
        Event.series_entity_id.in_(wanted), Event.overrides_id.is_(None)
    )
    if live:
        statement = statement.join(Entity, Entity.id == Event.entity_id).where(
            Entity.deleted_at.is_(None)
        )
    return list(session.scalars(statement))


def materialized_row(session: Session, series_id: str, key: str, timeline_id: str) -> Event | None:
    """The occurrence's materialized row in a timeline (in the trash or not)."""
    return session.scalar(
        select(Event).where(
            Event.series_entity_id == series_id,
            Event.occurrence_key == key,
            Event.timeline_id == timeline_id,
        )
    )


def number_of(resolver: Resolver, row: Event, key: str) -> int | None:
    """The occurrence number of ``key`` (``recurrence.md`` §3); ``None`` without one."""
    found = row_context(resolver, row)
    if isinstance(found, RuleProblem):
        return None
    try:
        return occurrence_number(*found, key)
    except RecurrenceError:
        return None


def series_slots(series_ids: Iterable[str]) -> list[SlotNode]:
    """The slots occurrence refs to these series depend on."""
    return [SlotNode(EVENT, i, slot) for i in sorted(set(series_ids)) for slot in ("start", "end")]


# --- reads ---------------------------------------------------------------------------------------


class NotASeriesError(ConflictError):
    """Occurrences of an event that doesn't recur."""

    code = "not_a_series"
    title = "Not a recurring event"


@dataclass(frozen=True)
class ListedOccurrence:
    """An occurrence as listed: computed, or its materialized row (``entity_id``, ``state``)."""

    key: str
    start: int
    end: int
    number: int | None
    entity_id: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class OccurrenceList:
    items: list[ListedOccurrence]
    truncated: bool
    estimated_count: int | None


def overlaps(start: int, end: int, w0: int, w1: int) -> bool:
    """``time-model.md`` §2.1 overlap of a span (or instant) and the window ``[w0, w1)``."""
    if start == end:
        return w0 <= start < w1
    return start < w1 and w0 < end


def occurrences(
    context: VaultContext,
    policy: VisibilityPolicy,
    row: Event,
    window: tuple[int, int],
    limit: int,
    *,
    include_cancelled: bool = False,
) -> OccurrenceList:
    """``GET /events/{id}/occurrences``: ``expand`` over ``[from, to)`` with ``max_items =
    limit``, merged with the materialized occurrences the policy sees (``recurrence.md`` §7):
    a materialized key replaces the computed occurrence (a ``modified`` one at its own time, so
    rows moved into the window are listed and rows moved out aren't), ``cancelled`` ones only
    with ``include_cancelled``. More than ``limit`` merged items truncate too."""
    if row.recurrence is None:
        raise NotASeriesError("The event doesn't recur.")
    timeline = context.session.get(Timeline, row.timeline_id)
    assert timeline is not None
    found = row_context(Resolver(context, timeline.dimension_id), row)
    if isinstance(found, RuleProblem):
        raise ConflictError(f"The recurrence rule can't be evaluated: {found.message}")
    rule, ctx = found
    try:
        expansion = expand(rule, ctx, window, limit)
    except RecurrenceError as exc:
        raise ConflictError(f"The recurrence rule can't be evaluated: {exc}") from exc
    if expansion.truncated:
        return OccurrenceList([], True, expansion.estimated_count)
    rows = visible_materialized(context.session, policy, [row.entity_id])
    by_key = {m.occurrence_key: m for m in rows if m.timeline_id == row.timeline_id}
    listed = merge(expansion.items, by_key, window, include_cancelled=include_cancelled)
    if len(listed) > limit:
        return OccurrenceList([], True, len(listed))
    items = []
    for key, (start, end, own) in listed.items():
        try:
            number: int | None = occurrence_number(rule, ctx, key)
        except RecurrenceError:
            number = None
        items.append(ListedOccurrence(
            key, start, end, number,
            None if own is None else own.entity_id,
            None if own is None else own.occurrence_state,
        ))  # fmt: skip
    items.sort(key=lambda o: (o.start, -o.end, _key_order(o.key)))
    return OccurrenceList(items, False, None)


def merge(
    computed: Iterable[Occurrence],
    own_rows: dict[str | None, Event],
    window: tuple[int, int],
    *,
    include_cancelled: bool,
) -> dict[str, tuple[int, int, Event | None]]:
    """Key → (start, end, materialized row or None) of a series' occurrences in a window: the
    computed ones, replaced by their materialized rows (§7)."""
    listed: dict[str, tuple[int, int, Event | None]] = {
        item.key: (item.start, item.end, None) for item in computed
    }
    for key, own in own_rows.items():
        if key is None or own.start_t is None or own.end_t is None:
            continue
        shown = own.occurrence_state != CANCELLED or include_cancelled
        if shown and overlaps(own.start_t, own.end_t, *window):
            listed[key] = (own.start_t, own.end_t, own)
        else:
            listed.pop(key, None)  # cancelled, or moved out of the window
    return listed


def _key_order(key: str) -> tuple[int, int]:
    head, _, tail = key.partition(".")
    return int(head), int(tail or -1)


def visible_materialized(
    session: Session, policy: VisibilityPolicy, series_ids: Iterable[str]
) -> list[Event]:
    """The live materialized occurrences of series that the policy sees."""
    wanted = sorted(set(series_ids))
    if not wanted:
        return []
    return list(
        session.scalars(
            select(Event)
            .join(Entity, Entity.id == Event.entity_id)
            .where(
                Event.series_entity_id.in_(wanted),
                Event.overrides_id.is_(None),
                Entity.deleted_at.is_(None),
                *policy.entities(Entity),
            )
        )
    )


__all__ = [
    "CANCELLED",
    "MODIFIED",
    "OCCURRENCE_STATES",
    "REFERENCED",
    "RULE_SLOT",
    "UNTIL_SLOT",
    "ListedOccurrence",
    "NotASeriesError",
    "OccurrenceList",
    "RuleProblem",
    "SeriesProblem",
    "bounds_of",
    "check_rule",
    "compute_occurrence",
    "dump_rule",
    "is_occurrence_point",
    "load_rule_slots",
    "materialized",
    "materialized_row",
    "merge",
    "number_of",
    "occurrence_point",
    "occurrences",
    "overlaps",
    "parse_rule",
    "recurrence_context",
    "refresh_series",
    "row_context",
    "rule_moments_beyond",
    "rule_points",
    "rule_slot_keys",
    "series_slots",
    "series_using",
    "visible_materialized",
    "write_rule_slots",
    "write_rule_specs",
]
