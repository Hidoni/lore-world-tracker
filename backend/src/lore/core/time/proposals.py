"""Calendar edit proposals (``time-model.md`` §7.4, D1, R-TIME-5) and the proposal store
(``data-model.md`` §5.9).

A calendar something depends on is edited through a **proposal**: an impact preview that lists
every record whose moment (or status) the new definition changes, then an apply with a strategy
per record. Rules (decided with #54 where the spec is silent):

- **Preview** (``POST /calendars/{id}/proposals {definition}``) compiles the definition (``422
  calendar_invalid`` fails fast), then dry-runs the real write inside a SAVEPOINT: it stores the
  definition, propagates without the hard checks and rolls back. The items are the slots whose
  moment or status changed (the calendar's own anchors aside), plus the slots, series rules
  (slot ``recurrence``) and calendars (slot ``definition``) the change breaks. Each item has
  ``old_t``/``new_t``, its new ``status`` and ``problem``, displays in the dimension's default
  calendar (``old_display`` before the edit, ``new_display`` after) and, for ``invalid_date``
  calendar dates in this calendar, the constrained date. ``series`` lists the series whose
  bounds move. Stored for one hour.
- **Strategies** per item key ``<record type>/<id>/<slot>``: ``keep_date`` (keep the spec),
  ``pin_moment`` (an ``absolute`` anchor at ``old_t``; the precision is kept when the default
  calendar still has that level, else ``base``; an end spec becomes a ``time_point`` end) and
  ``constrain`` (``invalid_date`` dates in this calendar only: the engine's constrain overflow,
  day 31 → 30). ``default_strategy`` covers the items without one where it applies, else
  ``keep_date``. Broken rules and calendars only take ``keep_date``.
- **Apply** is stale (``409 proposal_stale``) when the calendar's definition revision or
  resolved anchors changed, or anything in the calendar's dependency closure (moments, statuses
  and specs, fingerprinted at preview) did. A slot left broken after the strategies (any problem,
  not only ``invalid_date``) fails the apply with ``422 proposal_unresolved`` unless its item was
  given a strategy explicitly: an explicit ``keep_date`` accepts the problem (stored as the slot's
  status, §7.2 step 6). More than ``BACKUP_THRESHOLD`` items take an automatic database backup
  first (``backup_before``). The apply is one changeset, so one undo restores every moment.
"""

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    format_absolute,
    format_date,
    from_fields,
    to_fields,
)
from lore.chronology.schema import (
    AbsoluteAnchor,
    CalendarAnchor,
    EndSpec,
    TimePoint,
    TimePointEnd,
)
from lore.core.consistency.engine import accept
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.history.recorder import describe, discarded
from lore.core.time.calendars import (
    CALENDAR,
    AbsoluteLens,
    compile_document,
    compiled_calendar,
    dimension_spec,
    store_definition,
)
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import Calendar, Dimension, Event, Proposal, Timeline
from lore.core.time.propagate import Propagation, Violation, load_values
from lore.core.time.resolve import BASE, Resolver
from lore.core.time.slots import SlotValue
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.time.status import TimeStatus

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

PROPOSAL_TTL = timedelta(hours=1)
BACKUP_THRESHOLD = 100
"""Applying a calendar proposal with more items than this takes a backup first."""
BACKUP_REASON = "calendar-proposal"
EVENT = "event"
KEEP_DATE = "keep_date"
PIN_MOMENT = "pin_moment"
CONSTRAIN = "constrain"
type CalendarStrategy = Literal["keep_date", "pin_moment", "constrain"]
RULE_SLOT = "recurrence"
DEFINITION_SLOT = "definition"
PSEUDO_SLOTS = frozenset({(EVENT, RULE_SLOT), (CALENDAR, DEFINITION_SLOT)})
"""Items that aren't slots: a series rule that no longer evaluates, a calendar that no longer
compiles."""
CORE_RECORD_TYPES = frozenset({"dimension", "timeline", EVENT, CALENDAR})
"""Record types whose record id is their entity's id."""


class ProposalStaleError(ConflictError):
    """Something the proposal was computed from changed: preview again."""

    code = "proposal_stale"
    title = "Proposal is stale"


class ProposalUnresolvedError(InvalidInputError):
    """Records would be left broken without an explicit strategy."""

    code = "proposal_unresolved"
    title = "Proposal leaves records unresolved"


# --- the store -----------------------------------------------------------------------------------


def save_proposal(
    session: Session,
    *,
    kind: str,
    target_id: str,
    payload: dict[str, Any],
    impact: dict[str, Any],
    base_revision: int,
) -> Proposal:
    now = utc_now()
    proposal = Proposal(
        kind=kind,
        target_id=target_id,
        payload=payload,
        impact=impact,
        base_revision=base_revision,
        created_at=now,
        expires_at=now + PROPOSAL_TTL,
    )
    session.add(proposal)
    session.flush()
    return proposal


def load_proposal(session: Session, kind: str, target_id: str, proposal_id: str) -> Proposal:
    """A live proposal of the target (``404`` when unknown, expired or another target's)."""
    proposal = session.get(Proposal, proposal_id)
    if (
        proposal is None
        or proposal.kind != kind
        or proposal.target_id != target_id
        or proposal.expires_at <= utc_now()
    ):
        raise NotFoundError(f"No proposal {proposal_id} (proposals expire after an hour).")
    return proposal


def purge_expired(session: Session, now: datetime | None = None) -> int:
    """Delete expired proposals (at vault open and hourly); returns how many."""
    result = session.execute(delete(Proposal).where(Proposal.expires_at <= (now or utc_now())))
    return int(getattr(result, "rowcount", 0) or 0)


# --- items ---------------------------------------------------------------------------------------


def item_key(record_type: str, record_id: str, slot: str) -> str:
    return f"{record_type}/{record_id}/{slot}"


def _node_key(node: SlotNode) -> str:
    return item_key(node.type, node.id, node.slot)


type Lens = CompiledCalendar | AbsoluteLens


def _lens(context: VaultContext, dimension_id: str) -> Lens:
    """The dimension's default calendar (raw base units without one, or when it doesn't
    compile)."""
    row = context.session.get(Dimension, dimension_id)
    calendar_id = None if row is None else row.default_calendar_id
    if calendar_id is not None:
        try:
            return compiled_calendar(context, calendar_id)
        except ConflictError, NotFoundError:
            pass
    return AbsoluteLens(dimension_spec(context.session, dimension_id)[0])


def _precision(spec: TimePoint | EndSpec | None) -> str:
    if isinstance(spec, TimePoint):
        return spec.precision
    if isinstance(spec, TimePointEnd):
        return spec.time_point.precision
    return BASE


def _display(lens: Lens, t: int | None, precision: str) -> str | None:
    """A moment in the display calendar, at the spec's precision when the calendar has that
    level (else its finest)."""
    if t is None:
        return None
    if isinstance(lens, AbsoluteLens):
        return format_absolute(t, lens.base_unit)
    level = precision if precision in lens.levels else lens.levels[0]
    try:
        return format_date(lens, t, level)
    except DateError:
        return None


def _calendar_anchor(spec: TimePoint | EndSpec | None) -> tuple[TimePoint, CalendarAnchor] | None:
    point = spec.time_point if isinstance(spec, TimePointEnd) else spec
    if isinstance(point, TimePoint) and isinstance(point.anchor, CalendarAnchor):
        return point, point.anchor
    return None


def constrained(
    calendar: CompiledCalendar, calendar_id: str, spec: TimePoint | EndSpec | None, duration: int
) -> tuple[int, TimePoint | EndSpec] | None:
    """A date of ``calendar_id`` that is no longer valid, moved to the nearest valid date (the
    engine's ``constrain`` overflow: day 31 → day 30): its moment and new spec. ``None`` when the
    spec isn't such a date or can't be constrained."""
    found = _calendar_anchor(spec)
    if found is None or found[1].calendar_id != calendar_id:
        return None
    point, anchor = found
    precision, levels = point.precision, calendar.levels
    try:
        t = from_fields(
            calendar, anchor.fields, precision, era=anchor.era, regime=anchor.regime,
            overflow="constrain",
        )  # fmt: skip
        date = to_fields(calendar, t)
        fields = {
            level: value.slot_id if value.slot_id is not None else str(value.n)
            for level in levels[levels.index(precision) :]
            if (value := date.levels[level]) is not None
        }
        era = anchor.era
        if era is not None and date.era is not None:
            era = date.era.id
            fields[levels[-1]] = str(date.era.year)
        valid = from_fields(calendar, fields, precision, era=era, regime=anchor.regime) == t
    except DateError, ValueError:
        return None
    if not valid or not 0 <= t <= duration:
        return None
    new_point = point.model_copy(
        update={"anchor": anchor.model_copy(update={"fields": fields, "era": era})}
    )
    if isinstance(spec, TimePointEnd):
        return t, spec.model_copy(update={"time_point": new_point})
    return t, new_point


def pinned(
    spec: TimePoint | EndSpec, t: int, has_level: Callable[[str], bool]
) -> TimePoint | EndSpec:
    """``pin_moment``: an absolute anchor at ``t`` (precision kept when the default calendar has
    the level, else ``base``; the circa flag kept). An end spec becomes a ``time_point`` end."""
    inner = spec.time_point if isinstance(spec, TimePointEnd) else spec
    precision, approximate = BASE, False
    if isinstance(inner, TimePoint):
        approximate = inner.approximate
        if inner.precision != BASE and has_level(inner.precision):
            precision = inner.precision
    point = TimePoint(
        anchor=AbsoluteAnchor(kind="absolute", t=str(t)),
        precision=precision,
        approximate=approximate,
    )
    if isinstance(spec, TimePoint):
        return point
    return TimePointEnd(kind="time_point", time_point=point)


def _entities(context: VaultContext, nodes: Iterable[SlotNode]) -> dict[tuple[str, str], str]:
    """(record type, record id) → the entity the record belongs to."""
    session = context.session
    slots = context.registry.slot_registry()
    found: dict[tuple[str, str], str] = {}
    by_type: dict[str, set[str]] = {}
    for node in nodes:
        if node.type in CORE_RECORD_TYPES:
            found[(node.type, node.id)] = node.id
        else:
            by_type.setdefault(node.type, set()).add(node.id)
    for record_type, ids in by_type.items():
        provider = slots.get(record_type)
        if provider is None or provider.entity_column is None:
            continue
        model: Any = provider.model
        id_column = getattr(model, provider.id_column)
        entity_column = getattr(model, provider.entity_column)
        rows = session.execute(select(id_column, entity_column).where(id_column.in_(sorted(ids))))
        found.update({(record_type, str(i)): str(e) for i, e in rows if e is not None})
    return found


def _names(session: Session, entity_ids: Iterable[str]) -> dict[str, str]:
    wanted = sorted(set(entity_ids))
    names: dict[str, str] = {}
    for start in range(0, len(wanted), 5000):
        rows = session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(wanted[start : start + 5000]))
        )
        names.update({entity_id: name for entity_id, name in rows})  # noqa: C416 (Row pairs)
    return names


# --- stale detection ---------------------------------------------------------------------------


def fingerprint(
    calendar_id: str, resolved_anchors: Mapping[str, str], values: Mapping[SlotNode, SlotValue]
) -> str:
    """What a calendar proposal was computed from: the calendar's resolved anchors and the stored
    value (moment, status, spec) of every slot the edit's propagation reaches, as the run loaded
    them (the calendar's own anchors aside)."""
    rows = [
        [node.type, node.id, node.slot, value.t, value.status,
         None if value.spec is None else value.spec.model_dump_json()]
        for node, value in sorted(values.items())
        if not (node.type == CALENDAR and node.id == calendar_id)
    ]  # fmt: skip
    text = json.dumps(
        [dict(resolved_anchors), rows], sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(text.encode()).hexdigest()


# --- preview -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _DryRun:
    result: Propagation
    lens: Lens
    series: dict[str, tuple[int | None, int | None]]


def _series_bounds(session: Session, dimension_id: str) -> dict[str, tuple[int | None, int | None]]:
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
    rows = session.execute(
        select(Event.entity_id, Event.series_start_t, Event.series_end_t).where(
            Event.recurrence.is_not(None),
            Event.overrides_id.is_(None),
            Event.timeline_id.in_(timelines),
        )
    )
    return {entity_id: (start, end) for entity_id, start, end in rows}


def _violation_node(violation: Violation) -> SlotNode:
    return SlotNode(violation.record_type, violation.id, violation.slot)


def _dry_run(context: VaultContext, row: Calendar, compiled: Any) -> _DryRun:
    """Store the definition and propagate without the hard checks inside a SAVEPOINT, note what
    changed, roll back."""
    session = context.session
    session.flush()
    with discarded(session):
        savepoint = session.begin_nested()
        try:
            row.definition_revision += 1
            result = store_definition(context, row, compiled).propagate(strict=False, dry=True)
            lens = _lens(context, row.dimension_id)
            series = _series_bounds(session, row.dimension_id)
        finally:
            savepoint.rollback()
    session.expire_all()
    return _DryRun(result, lens, series)


@dataclass(frozen=True)
class _Lenses:
    """How a preview shows moments: the default calendar before and after the edit, and the
    edited calendar's new compilation (for ``constrain``)."""

    old: Lens
    new: Lens
    calendar: CompiledCalendar
    calendar_id: str
    duration: int


def _item(
    node: SlotNode,
    before: SlotValue | None,
    after: tuple[int | None, TimeStatus] | None,
    violation: Violation | None,
    lenses: _Lenses,
) -> dict[str, Any] | None:
    """A preview item: a slot whose moment or status changes, or that the change breaks.
    ``after`` is the slot's new moment and status from the dry run (``None``: unchanged)."""
    pseudo = (node.type, node.slot) in PSEUDO_SLOTS
    if not pseudo and (before is None or before.spec is None):
        return None  # a slot without a spec (a local calendar anchor)
    if after is None and before is not None:
        after = (before.t, before.status or TimeStatus.OK)
    unchanged = before is not None and after == (before.t, before.status)
    if violation is None and (after is None or unchanged):
        return None
    spec = None if before is None else before.spec
    precision = _precision(spec)
    old_t = None if before is None else before.t
    new_t = violation.t if violation is not None else (None if after is None else after[0])
    status = None if pseudo or after is None else after[1]
    found = None
    if status == TimeStatus.INVALID_DATE:
        found = constrained(lenses.calendar, lenses.calendar_id, spec, lenses.duration)
    strategies = [KEEP_DATE]
    if not pseudo and old_t is not None:
        strategies.append(PIN_MOMENT)
    if found is not None:
        strategies.append(CONSTRAIN)
    return {
        "key": _node_key(node),
        "record_type": node.type,
        "id": node.id,
        "slot": node.slot,
        "entity_id": None,
        "name": None,
        "old_t": _text(old_t),
        "old_status": None if before is None or before.status is None else before.status.value,
        "new_t": _text(new_t),
        "status": None if status is None else status.value,
        "problem": None
        if violation is None
        else {"code": violation.code, "message": violation.message},
        "old_display": _display(lenses.old, old_t, precision),
        "new_display": _display(lenses.new, new_t, precision),
        "constrained_t": None if found is None else str(found[0]),
        "constrained_display": None if found is None else _display(lenses.new, found[0], precision),
        "strategies": strategies,
    }


def _series_changes(
    session: Session,
    before: Mapping[str, tuple[int | None, int | None]],
    after: Mapping[str, tuple[int | None, int | None]],
) -> list[dict[str, Any]]:
    changed = sorted(i for i, bounds in after.items() if before.get(i) != bounds)
    names = _names(session, changed)
    return [
        {
            "entity_id": series_id,
            "name": names.get(series_id),
            "old_start_t": _text(before.get(series_id, (None, None))[0]),
            "old_end_t": _text(before.get(series_id, (None, None))[1]),
            "new_start_t": _text(after[series_id][0]),
            "new_end_t": _text(after[series_id][1]),
        }
        for series_id in changed
    ]


def preview_calendar_edit(
    context: VaultContext, entity: Entity, document: dict[str, Any]
) -> Proposal:
    """``POST /calendars/{id}/proposals``: the impact of a new definition, stored for an hour."""
    session = context.session
    row = _calendar_row(session, entity)
    dimension_id = row.dimension_id
    base_unit, duration = dimension_spec(session, dimension_id)
    compiled = compile_document(
        document, base_unit, duration, entity.id, Resolver(context, dimension_id)
    )
    anchors = dict(row.resolved_anchors)
    base_revision = row.definition_revision
    old_lens = _lens(context, dimension_id)
    series_before = _series_bounds(session, dimension_id)
    dry = _dry_run(context, row, compiled)
    old = dict(dry.result.before)
    closure_print = fingerprint(entity.id, anchors, old)
    lenses = _Lenses(old_lens, dry.lens, compiled.calendar, entity.id, duration)
    violations = {_violation_node(v): v for v in dry.result.violations}
    nodes = {
        n
        for n in {*dry.result.updated, *violations}
        if not (n.type == CALENDAR and n.id == entity.id and n.slot != DEFINITION_SLOT)
    }
    slots = context.registry.slot_registry()
    outside = [n for n in nodes if n not in old and (n.type, n.slot) not in PSEUDO_SLOTS]
    old.update(load_values(slots, session, outside))
    new = dry.result.values
    items = [
        item
        for node in sorted(nodes)
        if (item := _item(node, old.get(node), new.get(node), violations.get(node), lenses))
        is not None
    ]
    owners = _entities(context, (SlotNode(i["record_type"], i["id"], i["slot"]) for i in items))
    names = _names(session, owners.values())
    problems: dict[str, int] = {}
    for item in items:
        item["entity_id"] = owners.get((item["record_type"], item["id"]))
        item["name"] = names.get(item["entity_id"] or "")
        if item["problem"] is not None:
            code = item["problem"]["code"]
            problems[code] = problems.get(code, 0) + 1
    series = _series_changes(session, series_before, dry.series)
    impact = {
        "display_calendar_id": _lens_id(context, dimension_id, dry.lens),
        "definition": compiled.definition,
        "fingerprint": closure_print,
        "items": items,
        "series": series,
        "summary": {
            "affected": dry.result.affected,
            "changed": len(items),
            "problems": sum(problems.values()),
            "by_problem": problems,
            "series": len(series),
        },
    }
    return save_proposal(
        session,
        kind=CALENDAR,
        target_id=entity.id,
        payload={"definition": document},
        impact=impact,
        base_revision=base_revision,
    )


def _text(t: int | None) -> str | None:
    return None if t is None else str(t)


def _lens_id(context: VaultContext, dimension_id: str, lens: Lens) -> str:
    if isinstance(lens, AbsoluteLens):
        return ABSOLUTE_CALENDAR_ID
    row = context.session.get(Dimension, dimension_id)
    return ABSOLUTE_CALENDAR_ID if row is None or row.default_calendar_id is None else (
        row.default_calendar_id
    )  # fmt: skip


def _calendar_row(session: Session, entity: Entity) -> Calendar:
    if entity.deleted_at is not None:
        raise ConflictError("The calendar is in the trash: restore it before editing it.")
    row = session.get(Calendar, entity.id)
    if row is None:
        raise ConflictError("The calendar has no definition.")
    return row


# --- apply ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedCalendar:
    kept: int
    pinned: int
    constrained: int
    accepted: int
    """Records left with a problem by an explicit ``keep_date``."""
    backup: str | None
    entity_ids: list[str]


def _strategy_error(key: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(
        message, errors=[ErrorItem(path=f"strategies.{key}", code=code, message=message)]
    )


def _effective(
    items: Mapping[str, Mapping[str, Any]], strategies: Mapping[str, str], default: str
) -> dict[str, str]:
    chosen: dict[str, str] = {}
    for key, strategy in strategies.items():
        item = items.get(key)
        if item is None:
            raise _strategy_error(key, "The proposal has no such record.", "unknown_record")
        if strategy not in item["strategies"]:
            raise _strategy_error(
                key, f"{strategy} isn't possible for this record (choose one of "
                f"{', '.join(item['strategies'])})."
            )  # fmt: skip
        chosen[key] = strategy
    for key, item in items.items():
        if key not in chosen:
            chosen[key] = default if default in item["strategies"] else KEEP_DATE
    return chosen


def _stale(entity: Entity) -> ProposalStaleError:
    return ProposalStaleError(
        "The calendar or records depending on it changed since the preview: preview the edit "
        "again.",
        context={"proposals": f"/calendars/{entity.id}/proposals"},
    )


def apply_calendar_proposal(
    context: VaultContext,
    entity: Entity,
    proposal_id: str,
    *,
    strategies: Mapping[str, str],
    default_strategy: str,
    backup: Callable[[], str],
) -> AppliedCalendar:
    """``POST /calendars/{id}/proposals/{pid}/apply``: save the definition, apply the strategies
    and propagate, in the request's transaction (one changeset)."""
    session = context.session
    proposal = load_proposal(session, CALENDAR, entity.id, proposal_id)
    row = _calendar_row(session, entity)
    if row.definition_revision != proposal.base_revision:
        raise _stale(entity)
    items: dict[str, dict[str, Any]] = {item["key"]: item for item in proposal.impact["items"]}
    chosen = _effective(items, strategies, default_strategy)
    base_unit, duration = dimension_spec(session, row.dimension_id)
    compiled = compile_document(
        proposal.payload["definition"], base_unit, duration, entity.id,
        Resolver(context, row.dimension_id),
    )  # fmt: skip
    anchors = dict(row.resolved_anchors)
    entity.updated_at = utc_now()  # the calendar entity's revision moves too
    row.definition_revision += 1
    writer = store_definition(context, row, compiled)
    resolver = Resolver(context, row.dimension_id)
    slots = context.registry.slot_registry()
    changed = [k for k, s in chosen.items() if s in (PIN_MOMENT, CONSTRAIN)]
    nodes = {
        k: SlotNode(items[k]["record_type"], items[k]["id"], items[k]["slot"]) for k in changed
    }
    values = load_values(slots, session, nodes.values())
    for key in sorted(changed):
        node, item = nodes[key], items[key]
        value = values.get(node)
        if value is None or value.spec is None:
            raise _strategy_error(key, "The record has no time point to change.")
        if chosen[key] == PIN_MOMENT:
            spec = pinned(value.spec, int(item["old_t"]), resolver.has_default_level)
        else:
            found = constrained(compiled.calendar, entity.id, value.spec, duration)
            if found is None:
                raise _strategy_error(key, "The date can't be constrained.")
            spec = found[1]
        writer.set_spec(node.type, node.id, node.slot, spec, store=True,
                        dimension_id=value.dimension_id)  # fmt: skip
    result = writer.propagate(strict=False, path="strategies")
    # Records given a strategy explicitly may keep hard-rule problems (consistency.md §3).
    accept(session, (items[k]["entity_id"] for k in strategies if items[k]["entity_id"]))
    before = {**result.before, **values}  # the pinned and constrained slots as they were
    if fingerprint(entity.id, anchors, before) != proposal.impact["fingerprint"]:
        raise _stale(entity)
    unresolved = [
        v for v in result.violations
        if item_key(v.record_type, v.id, v.slot) not in strategies
    ]  # fmt: skip
    if unresolved:
        count = len(unresolved)
        raise ProposalUnresolvedError(
            f"{count} record{'s' if count != 1 else ''} would be left broken: give "
            f"{'them' if count != 1 else 'it'} a strategy (pin_moment, constrain, or keep_date "
            "to accept the problem).",
            errors=[
                ErrorItem(
                    path=f"strategies.{item_key(v.record_type, v.id, v.slot)}",
                    code=v.code,
                    message=f"{v.record_type} {v.id}: {v.message}",
                )
                for v in unresolved
            ],
            context={"records": [v.as_record() for v in unresolved]},
        )
    # The backup reads the committed database: what the vault was before this transaction.
    backup_id = backup() if len(items) > BACKUP_THRESHOLD else None
    session.delete(proposal)
    counts = {
        s: sum(1 for c in chosen.values() if c == s) for s in (KEEP_DATE, PIN_MOMENT, CONSTRAIN)
    }
    describe(session, f"Edited the calendar “{entity.name}” ({len(items)} records affected)")
    session.flush()
    touched = {item["entity_id"] for item in items.values() if item["entity_id"]}
    return AppliedCalendar(
        kept=counts[KEEP_DATE],
        pinned=counts[PIN_MOMENT],
        constrained=counts[CONSTRAIN],
        accepted=len(result.violations),
        backup=backup_id,
        entity_ids=sorted(touched | {entity.id}),
    )


__all__ = [
    "BACKUP_REASON",
    "BACKUP_THRESHOLD",
    "PROPOSAL_TTL",
    "AppliedCalendar",
    "ProposalStaleError",
    "ProposalUnresolvedError",
    "apply_calendar_proposal",
    "constrained",
    "fingerprint",
    "item_key",
    "load_proposal",
    "pinned",
    "preview_calendar_edit",
    "purge_expired",
    "save_proposal",
]
