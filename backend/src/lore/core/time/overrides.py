"""Branch overrides (``time-model.md`` §4.4, ``recurrence.md`` §6, #115): a branch changing an
inherited record that spans its branch point, through an **override row** in the record's own
table (``overrides_id`` = the root row, ``timeline_id`` = the branch). The branches module is the
API; ``TimelineView`` resolves the rows (the closest timeline wins).

- The root is an event (by its entity id), a fact or a link (by id), inherited by the branch (it
  lives in a strict ancestor, starts before the cut-off ``c``) and spanning it: it ends after
  ``c`` (a series: its last occurrence does, or it never ends).
- Only what lies after the cut-off may change: an event's ``end`` (resolved at or after ``c``)
  and its rule's limit and exclusions (the occurrences before ``c`` stay the same, added
  exclusions start at or after ``c``); a fact's ``value`` and ``valid_to``; a link's ``role``,
  ``data`` and ``valid_to`` (bounds at or after ``c``; ``valid_to`` null = it goes on). Ending a
  record at ``c`` is how a branch removes it.
- The override copies its root's start (``branches.override_start_changed`` reports any that
  doesn't); a root's start change is copied to its overrides (``sync_starts``).
- One override per root and timeline: overriding again updates it. Reverting deletes it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.recurrence import RecurrenceError, expand
from lore.chronology.schema import EndSpec, TimePoint
from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.links.models import Link
from lore.core.time import series
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import Event, Timeline
from lore.core.time.propagate import TimeWriter
from lore.core.time.resolve import Resolver
from lore.core.time.specs import parse_end_spec
from lore.core.time.timeline_view import TimelineView
from lore.core.types import Affected
from lore.core.visibility import VisibilityPolicy

EVENT, FACT, LINK = "event", "fact", "link"
RECORD_TYPES = (EVENT, FACT, LINK)
ALLOWED: dict[str, frozenset[str]] = {
    EVENT: frozenset({"end", "recurrence"}),
    FACT: frozenset({"value", "valid_to"}),
    LINK: frozenset({"role", "data", "valid_to"}),
}
# Columns an override doesn't copy from its root.
_OWN = frozenset({"id", "timeline_id", "overrides_id", "revision", "created_at", "updated_at",
                  "deleted_at"})  # fmt: skip


@dataclass(frozen=True)
class ValidityRecord:
    """A module table of validity records a branch may override like facts and links
    (``time-model.md`` §4.4: map pins). Its rows have ``timeline_id``, ``overrides_id`` and the
    ``valid_from``/``valid_to`` slots of the slot provider of ``record_type``; ``entity_of`` names
    the entity whose visibility a row follows. Only ``valid_to`` may change (ending a pin at the
    branch point removes it there)."""

    record_type: str
    model: type
    entity_of: Callable[[Session, Any], str]


_VALIDITY: dict[str, ValidityRecord] = {}


def register_validity_record(record: ValidityRecord) -> ValidityRecord:
    """Make a module table overridable (idempotent for the same declaration)."""
    known = _VALIDITY.get(record.record_type)
    if known is not None and known != record:
        raise ValueError(f"{record.record_type} is already registered differently")
    _VALIDITY[record.record_type] = record
    return record


def _allowed(record_type: str) -> frozenset[str]:
    if record_type in _VALIDITY:
        return frozenset({"valid_to"})
    return ALLOWED.get(record_type, frozenset())


class OverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(
        description="`event` (by entity id), `fact`, `link` or a module's validity record such as "
        "`maps.pin` (by id)."
    )
    root_id: str = Field(description="The inherited record: an event's entity id, or a row id.")
    timeline_id: str = Field(description="The branch overriding it.")
    changes: dict[str, Any] = Field(
        description="Events: `end`, `recurrence`; facts: `value`, `valid_to`; links: `role`, "
        "`data`, `valid_to`; module validity records (`maps.pin`): `valid_to`."
    )


@dataclass
class OverrideResult:
    record_type: str
    id: str
    root_id: str
    timeline_id: str
    affected: Affected


def _invalid(path: str, message: str, code: str = "override_not_allowed") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


# --- the root and its cut-off --------------------------------------------------------------------


@dataclass
class _Target:
    model: Any
    root: Any
    entity_id: str
    start: int | None  # None: unbounded (open validity)
    end: int | None  # None: +∞
    cutoff: int


def _root(session: Session, record_type: str, root_id: str) -> tuple[Any, Any, str]:
    """(model, root row, entity id); ``404`` when missing or trashed."""
    if record_type == EVENT:
        row = session.scalar(
            select(Event).where(Event.entity_id == root_id, Event.overrides_id.is_(None))
        )
        entity = session.get(Entity, root_id)
        if row is None or entity is None or entity.deleted_at is not None:
            raise NotFoundError(f"No event {root_id}.")
        return Event, row, root_id
    validity = _VALIDITY.get(record_type)
    model: Any = (
        validity.model if validity is not None else EntityFact if record_type == FACT else Link
    )
    row = session.get(model, root_id)
    if row is None or row.deleted_at is not None:
        raise NotFoundError(f"No {record_type} {root_id}.")
    if row.overrides_id is not None:
        raise _invalid("root_id", "Override the record it overrides (its root) instead.")
    if validity is not None:
        return model, row, validity.entity_of(session, row)
    entity_id = row.entity_id if record_type == FACT else row.source_id
    return model, row, entity_id


def _bounds(record_type: str, row: Any) -> tuple[int | None, int | None]:
    if record_type == EVENT:
        if row.recurrence is not None:
            # A series spans by its occurrences: from its start to its last one's end.
            return row.start_t, row.series_end_t
        return row.start_t, row.end_t
    return row.valid_from_t, row.valid_to_t


def _target(
    context: Any, policy: VisibilityPolicy, record_type: str, root_id: str, timeline_id: str
) -> _Target:
    session = context.session
    if record_type not in RECORD_TYPES and record_type not in _VALIDITY:
        if record_type == "segment":
            raise _invalid("record_type", "Worldline segments come with worldlines (M9).",
                           "not_supported")  # fmt: skip
        raise _invalid("record_type", f"Unknown record type {record_type!r}.", "invalid_value")
    timeline = session.get(Entity, timeline_id)
    row = session.get(Timeline, timeline_id)
    if (
        timeline is None
        or row is None
        or timeline.deleted_at is not None
        or not policy.visible_ids(session, [timeline_id])
    ):
        raise NotFoundError(f"No timeline {timeline_id}.")
    if row.parent_timeline_id is None:
        raise _invalid("timeline_id", "Only branches override records: edit it directly.")
    model, root, entity_id = _root(session, record_type, root_id)
    if not policy.visible_ids(session, [entity_id]):
        raise NotFoundError(f"No {record_type} {root_id}.")
    view = TimelineView.for_timeline(session, timeline_id)
    entry = next((e for e in view.lineage if e.timeline_id == root.timeline_id), None)
    if entry is None:
        raise _invalid("root_id", "The record isn't part of the branch's past.")
    if entry.depth == 0 or entry.cutoff is None:
        raise _invalid("root_id", "The record is the branch's own: edit it directly.")
    start, end = _bounds(record_type, root)
    cutoff = entry.cutoff
    if start is not None and start >= cutoff:
        raise _invalid("root_id", "The record starts after the branch point: the branch doesn't "
                       "have it.")  # fmt: skip
    if end is not None and end <= cutoff:
        raise _invalid("root_id", "The record ends before the branch point: the shared past "
                       "can't change.")  # fmt: skip
    return _Target(model, root, entity_id, start, end, cutoff)


# --- checking the changes ------------------------------------------------------------------------


def _after_cutoff(t: int | None, cutoff: int, path: str) -> None:
    if t is not None and t < cutoff:
        raise _invalid(path, "Only what lies after the branch point may change.")


def _resolver(context: Any, timeline_id: str) -> Resolver:
    row = context.session.get(Timeline, timeline_id)
    assert row is not None
    return Resolver(context, row.dimension_id, timeline_id)


def _check_point(resolver: Resolver, spec: Any, cutoff: int, path: str) -> TimePoint | None:
    if spec is None:
        return None
    point = TimePoint.model_validate(spec)
    resolution = resolver.resolve(point)
    if resolution.t is None or not resolution.ok:
        raise _invalid(path, "The time point doesn't resolve.", "invalid_value")
    _after_cutoff(resolution.t, cutoff, path)
    return point


def _check_event(context: Any, target: _Target, timeline_id: str, changes: dict[str, Any]
                 ) -> dict[str, Any]:  # fmt: skip
    root: Event = target.root
    resolver = _resolver(context, timeline_id)
    out: dict[str, Any] = {}
    if "end" in changes:
        end: EndSpec = parse_end_spec(changes["end"])
        started = resolver.slot(EVENT, root.entity_id, "start")
        resolution = resolver.resolve_end(end, started)
        if resolution.t is None or not resolution.ok:
            raise _invalid("changes.end", "The end doesn't resolve.", "invalid_value")
        _after_cutoff(resolution.t, target.cutoff, "changes.end")
        out["end_spec"] = end
    if "recurrence" in changes:
        if root.recurrence is None:
            raise _invalid("changes.recurrence", "The event doesn't recur.")
        rule = series.parse_rule(changes["recurrence"])
        _check_rule(context, resolver, root, rule, target.cutoff)
        out["recurrence"] = series.dump_rule(rule)
    return out


def _without(document: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in document.items() if k not in keys}


def _check_rule(context: Any, resolver: Resolver, root: Event, rule: Any, cutoff: int) -> None:
    """Only the limit and the exclusions may change, the occurrences before the cut-off stay
    the same and added exclusions start at or after it (``recurrence.md`` §6)."""
    new, old = series.dump_rule(rule), dict(root.recurrence or {})
    if _without(new, "limit", "exclusions") != _without(old, "limit", "exclusions"):
        raise _invalid("changes.recurrence", "A branch may only change a series' limit and add "
                       "exclusions.")  # fmt: skip
    kept = old.get("exclusions") or []
    added = [e for e in new.get("exclusions") or [] if e not in kept]
    if any(e not in (new.get("exclusions") or []) for e in kept):
        raise _invalid("changes.recurrence", "The series' exclusions before the branch point "
                       "stay: only new ones may be added.")  # fmt: skip
    for index, exclusion in enumerate(added):
        _check_point(
            resolver, exclusion.get("from"), cutoff, f"changes.recurrence.exclusions.{index}"
        )
    if root.start_t is None:
        return
    resolved: dict[str, int] = {}
    for _slot, (pointer, point) in sorted(series.rule_points(rule).items()):
        found = resolver.resolve(point)
        if found.t is None or not found.ok:
            raise _invalid("changes.recurrence", "A rule time point doesn't resolve.",
                           "invalid_value")  # fmt: skip
        resolved[pointer] = found.t
    end = parse_end_spec(root.end_spec)
    stored = series.stored_rule(root)
    assert stored is not None
    before = series.recurrence_context(resolver, stored, root.start_t, end, {
        p: int(t) for p, t in (root.recurrence_resolved or {}).items()})  # fmt: skip
    after = series.recurrence_context(resolver, rule, root.start_t, end, resolved)
    if isinstance(before, series.RuleProblem) or isinstance(after, series.RuleProblem):
        raise _invalid("changes.recurrence", "The recurrence rule can't be evaluated.",
                       "invalid_value")  # fmt: skip
    window = (root.start_t, cutoff)
    try:
        old_items = expand(stored, before, window, 5000)
        new_items = expand(rule, after, window, 5000)
    except RecurrenceError as error:
        raise _invalid("changes.recurrence", str(error), "invalid_value") from error

    def starts(items: Any) -> list[tuple[int, int]]:
        return [(o.start, o.end) for o in items.items if o.start < cutoff]

    if (old_items.truncated, old_items.estimated_count) != (
        new_items.truncated,
        new_items.estimated_count,
    ) or starts(old_items) != starts(new_items):
        raise _invalid("changes.recurrence", "The occurrences before the branch point must stay "
                       "the same.")  # fmt: skip


def _check_validity(context: Any, timeline_id: str, changes: dict[str, Any], cutoff: int,
                    out: dict[str, Any]) -> None:  # fmt: skip
    if "valid_to" in changes:
        resolver = _resolver(context, timeline_id)
        out["valid_to_spec"] = _check_point(resolver, changes["valid_to"], cutoff,
                                            "changes.valid_to")  # fmt: skip
        if out["valid_to_spec"] is None:
            out["valid_to_t"] = None


def _check_fact(context: Any, target: _Target, timeline_id: str, changes: dict[str, Any]
                ) -> dict[str, Any]:  # fmt: skip
    from lore.core.facts.service import Facts  # noqa: PLC0415 (facts build on time)

    out: dict[str, Any] = {}
    if "value" in changes:
        entity = context.session.get(Entity, target.entity_id)
        out["value"] = Facts(context)._value(entity, target.root.field_key, changes["value"],
                                             "changes.value")  # fmt: skip
    _check_validity(context, timeline_id, changes, target.cutoff, out)
    return out


def _check_link(context: Any, target: _Target, timeline_id: str, changes: dict[str, Any]
                ) -> dict[str, Any]:  # fmt: skip
    from lore.core.links.service import LinkService, data_errors  # noqa: PLC0415

    out: dict[str, Any] = {}
    if "role" in changes:
        out["role"] = changes["role"]
    if "data" in changes:
        if not isinstance(changes["data"], dict):
            raise _invalid("changes.data", "data must be an object.", "invalid_value")
        _link, info = LinkService(context.session, context.registry, vault=context.vault)._load(
            target.root.id
        )
        errors = data_errors(info.definition.data_schema, changes["data"])
        if errors:
            raise InvalidInputError("The link data doesn't match its type.", errors=errors)
        out["data"] = changes["data"]
    _check_validity(context, timeline_id, changes, target.cutoff, out)
    return out


def _check_validity_record(context: Any, target: _Target, timeline_id: str,
                           changes: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    out: dict[str, Any] = {}
    _check_validity(context, timeline_id, changes, target.cutoff, out)
    return out


_CHECKS: dict[str, Callable[..., dict[str, Any]]] = {
    EVENT: _check_event,
    FACT: _check_fact,
    LINK: _check_link,
}


# --- writing ------------------------------------------------------------------------------------


def _existing(session: Session, model: Any, root: Any, timeline_id: str) -> Any:
    return session.scalar(
        select(model).where(model.overrides_id == root.id, model.timeline_id == timeline_id)
    )


def _copy(model: Any, root: Any, timeline_id: str) -> Any:
    # Unset columns stay unset: an explicit None would store JSON null in JSON columns.
    values = {
        column.key: getattr(root, column.key)
        for column in model.__table__.columns
        if column.key not in _OWN and getattr(root, column.key) is not None
    }
    row = model(**values, id=new_id(), timeline_id=timeline_id, overrides_id=root.id)
    if hasattr(model, "created_at"):
        row.created_at = row.updated_at = utc_now()
    return row


def _slots(record_type: str, row: Any) -> list[tuple[str, str, Any]]:
    """The override row's slots and specs: ``(record type, slot, spec)``."""
    if record_type == EVENT:
        found = [(series.EVENT_OVERRIDE, "start", row.start_spec),
                 (series.EVENT_OVERRIDE, "end", parse_end_spec(row.end_spec))]  # fmt: skip
        rule = series.stored_rule(row)
        points = {} if rule is None else series.rule_points(rule)
        found += [
            (series.EVENT_OVERRIDE, slot, point) for slot, (_p, point) in sorted(points.items())
        ]
        return found
    return [(record_type, "valid_from", row.valid_from_spec),
            (record_type, "valid_to", row.valid_to_spec)]  # fmt: skip


def _record_id(record_type: str, row: Any) -> str:
    return str(row.id)


def save_override(context: Any, policy: VisibilityPolicy, data: OverrideIn) -> OverrideResult:
    """Create (or update) the branch's override of an inherited spanning record."""
    session = context.session
    unknown = set(data.changes) - _allowed(data.record_type)
    target = _target(context, policy, data.record_type, data.root_id, data.timeline_id)
    if unknown:
        name = sorted(unknown)[0]
        raise _invalid(f"changes.{name}", f"A branch can't change {name!r} of a {data.record_type}"
                       ": only what lies after the branch point.")  # fmt: skip
    check: Callable[..., dict[str, Any]] = _CHECKS.get(data.record_type, _check_validity_record)
    values = check(context, target, data.timeline_id, data.changes)
    row = _existing(session, target.model, target.root, data.timeline_id)
    if row is None:
        row = _copy(target.model, target.root, data.timeline_id)
        session.add(row)
    elif hasattr(row, "revision"):
        row.revision += 1
    for name, value in values.items():
        setattr(row, name, value)
    if data.record_type == EVENT and "recurrence" in values:
        row.recurrence_resolved = None  # resolved again by propagation
    if hasattr(row, "updated_at"):
        row.updated_at = utc_now()
    session.flush()
    writer = TimeWriter(context)
    dimension = session.get(Timeline, data.timeline_id)
    for record_type, slot, spec in _slots(data.record_type, row):
        dimension_id = None if dimension is None else dimension.dimension_id
        writer.set_spec(record_type, row.id, slot, spec, dimension_id=dimension_id)
    if data.record_type == EVENT:
        writer.touch_series(row.entity_id)
    writer.propagate(path="changes")
    return OverrideResult(data.record_type, row.id, data.root_id, data.timeline_id,
                          _affected(session, target.entity_id, data.timeline_id))  # fmt: skip


def revert_override(context: Any, policy: VisibilityPolicy, record_type: str, override_id: str
                    ) -> OverrideResult:  # fmt: skip
    """Delete an override: the branch sees the inherited record again."""
    session = context.session
    validity = _VALIDITY.get(record_type)
    model: Any = (
        validity.model
        if validity is not None
        else {EVENT: Event, FACT: EntityFact, LINK: Link}.get(record_type)
    )
    if model is None:
        raise _invalid("record_type", f"Unknown record type {record_type!r}.", "invalid_value")
    row = session.get(model, override_id)
    if row is None or row.overrides_id is None:
        raise NotFoundError(f"No override {override_id}.")
    if validity is not None:
        entity_id = validity.entity_of(session, row)
    else:
        entity_id = row.entity_id if record_type in (EVENT, FACT) else row.source_id
    if not policy.visible_ids(session, [entity_id, row.timeline_id]) >= {
        entity_id,
        row.timeline_id,
    }:
        raise NotFoundError(f"No override {override_id}.")
    writer = TimeWriter(context)
    own = series.EVENT_OVERRIDE if record_type == EVENT else record_type
    nodes = [SlotNode(own, row.id, slot) for _t, slot, _s in _slots(record_type, row)]
    if record_type != EVENT:
        anchored = [d for node in nodes for d in writer.index.dependents_of(node)]
        if anchored:
            raise ConflictError(
                "Time points are anchored to the override: anchor them elsewhere first.",
                context={"references": {"time_points": len(anchored)}},
            )
    # What the branch anchored to the event sees the inherited row again.
    seen = [SlotNode(EVENT, row.entity_id, n.slot) for n in nodes if n.slot != "start"] if (
        record_type == EVENT) else []  # fmt: skip
    dependents = [d for node in seen for d in writer.index.dependents_of(node)]
    for node in nodes:
        writer.index.replace_edges(node, ())
    root_id = str(row.overrides_id) if record_type != EVENT else row.entity_id
    timeline_id = row.timeline_id
    session.delete(row)
    session.flush()
    writer.touch(*dependents)
    writer.propagate(path="")
    return OverrideResult(record_type, override_id, root_id, timeline_id,
                          _affected(session, entity_id, timeline_id))  # fmt: skip


def _affected(session: Session, entity_id: str, timeline_id: str) -> Affected:
    timeline = session.get(Timeline, timeline_id)
    return Affected(
        entities=[entity_id, timeline_id],
        dimensions=[] if timeline is None else [timeline.dimension_id],
        time_changed=True,
        search_changed=True,
    )


# --- keeping overrides in step with their root ---------------------------------------------------


def sync_starts(context: Any, writer: TimeWriter, record_type: str, root: Any) -> None:
    """A root's start changed: its overrides start there too (their start spec is a copy)."""
    session = context.session
    if record_type == EVENT:
        rows: Sequence[Any] = session.scalars(
            select(Event).where(Event.overrides_id == root.id)
        ).all()
        for row in rows:
            row.start_spec = root.start_spec
            writer.set_spec(series.EVENT_OVERRIDE, row.id, "start", root.start_spec)
        return
    validity = _VALIDITY.get(record_type)
    model: Any = (
        validity.model if validity is not None else EntityFact if record_type == FACT else Link
    )
    for row in session.scalars(select(model).where(model.overrides_id == root.id)):
        row.valid_from_spec = root.valid_from_spec
        if root.valid_from_spec is None:
            row.valid_from_t = None
        writer.set_spec(record_type, row.id, "valid_from", root.valid_from_spec)


def overrides_of(session: Session, model: Any, root_id: str) -> list[Any]:
    """The live override rows of a root."""
    statement = select(model).where(model.overrides_id == root_id)
    if hasattr(model, "deleted_at"):
        statement = statement.where(model.deleted_at.is_(None))
    return list(session.scalars(statement))


__all__ = [
    "ALLOWED",
    "OverrideIn",
    "OverrideResult",
    "ValidityRecord",
    "overrides_of",
    "register_validity_record",
    "revert_override",
    "save_override",
    "sync_starts",
]
