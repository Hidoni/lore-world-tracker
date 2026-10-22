"""Re-parenting and merging branches (``time-model.md`` §4.7, #158, ADR-0019): proposals that
change a branch's place in its dimension's tree. The branches module is the API
(``/m/branches/timelines/{id}/proposals``).

- **Plan, preview, apply.** ``plan_*`` reads what an operation would do (which rows move, which
  overrides are dropped or merged, which timelines move, which entities change origin) without
  writing. The preview runs the apply inside a SAVEPOINT and rolls it back, so it also reports the
  branch points the operation pins; it is stored for an hour (``proposals``, kind ``branch``).
  Apply plans again and answers ``409 proposal_stale`` when the plan differs from the preview's;
  then it executes the plan as one changeset.
- **Re-parent** a branch under another timeline of its dimension: its overrides of records it no
  longer inherits spanning its cut-off are dropped (time points anchored to a dropped fact, link or
  validity override pinned first), and branch points anchored to records their parent no longer
  sees are pinned.
- **Merge** a branch ``B`` into its parent ``P`` (D-decision of #158: combine, with a choice per
  record): ``B``'s own rows move to ``P``; each override of ``B`` replaces what ``P`` saw (``P``'s
  own override is reverted and ``B``'s moves; a record of ``P`` itself takes the override's
  changes; an ancestor's record gets ``B``'s override as ``P``'s). ``P``'s own live records
  starting at or after the branch point (``conflicts``) are kept or discarded per record.
  ``B``'s branches move under ``P``, its branch-only entities become ``P``'s, its notes move to
  ``P`` where ``P`` (a branch) has none, and ``B`` goes to the trash, empty.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.schema import EndSpec, TimePoint
from lore.core.db.base import Base
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.history.recorder import describe, discarded
from lore.core.time import series
from lore.core.time.branches import BRANCH_POINT, hidden_targets, origin_for
from lore.core.time.dependencies import SlotNode
from lore.core.time.dimensions import TIMELINE
from lore.core.time.models import EntityTimelineNote, Event, Proposal, Timeline
from lore.core.time.overrides import _VALIDITY, revert_override
from lore.core.time.propagate import TimeWriter
from lore.core.time.proposals import (
    ProposalStaleError,
    load_proposal,
    pinned,
    save_proposal,
)
from lore.core.time.resolve import Resolver
from lore.core.time.specs import parse_end_spec
from lore.core.time.timeline_view import TimeBound, lineage, registered_time_bounds
from lore.core.types import Affected
from lore.core.visibility import AUTHOR

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

KIND = "branch"
REPARENT = "reparent"
MERGE = "merge"
type Operation = Literal["reparent", "merge"]
KEEP = "keep"
DISCARD = "discard"
type Strategy = Literal["keep", "discard"]
LISTED = 200
"""How many records of each list a preview names (the summary counts them all)."""

# What a row does in a plan.
MOVE = "move"  # it moves to the parent
REPLACE = "replace"  # an override moves to the parent; the parent's own override is reverted
APPLY = "apply"  # a record of the parent takes the override's changes; the override is reverted
REHOME = "rehome"  # an override of an ancestor's record moves to the parent
DROP = "drop"  # re-parenting: an override of a record no longer inherited

# What an override may change of an event (and what it resolves to).
_EVENT_COLUMNS = ("end_spec", "end_t", "recurrence", "recurrence_resolved", "series_start_t",
                  "series_end_t", "time_status")  # fmt: skip
# Columns naming the entity a row belongs to, by preference (for names in the preview).
_OWNERS = ("entity_id", "source_id", "target_entity_id", "language_id")


class OccurrenceKeyConflictError(ConflictError):
    """A merge would give a timeline two materialized occurrences of one key."""

    code = "occurrence_key_conflict"
    title = "Occurrence key conflict"


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def missing_parent() -> InvalidInputError:
    return _invalid("parent_timeline_id", "Re-parenting needs the new parent.", "required")


# --- tables --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Table:
    """A time-bound table of the app (core and modules) with a timeline column."""

    model: Any
    bound: TimeBound
    name: str
    record_type: str
    overridable: bool


def _tables() -> list[_Table]:
    from lore.core.facts.models import EntityFact  # noqa: PLC0415 (facts build on time)
    from lore.core.links.models import Link  # noqa: PLC0415
    from lore.core.time.models import WorldlineSegment  # noqa: PLC0415

    known: dict[Any, str] = {Event: "event", EntityFact: "fact", Link: "link",
                             WorldlineSegment: "segment"}  # fmt: skip
    known.update({record.model: record.record_type for record in _VALIDITY.values()})
    found: list[_Table] = []
    for model, bound in registered_time_bounds().items():
        table = getattr(model, "__table__", None)
        # The app's tables only, not tables registered elsewhere (tests).
        if table is None or table.metadata is not Base.metadata or bound.timeline not in table.c:
            continue
        found.append(_Table(model, bound, table.name, known.get(model, table.name),
                            bound.overrides in table.c))  # fmt: skip
    return sorted(found, key=lambda t: t.name)


def _timeline_col(table: _Table) -> Any:
    return getattr(table.model, table.bound.timeline)


def _start(table: _Table, row: Any) -> int | None:
    value: int | None = getattr(row, table.bound.start)
    return value


def _end(table: _Table, row: Any) -> int | None:
    if table.model is Event and row.recurrence is not None:
        series_end: int | None = row.series_end_t  # a series spans by its occurrences
        return series_end
    return None if table.bound.end is None else getattr(row, table.bound.end)


def _overrides(table: _Table, row: Any) -> str | None:
    return getattr(row, table.bound.overrides) if table.overridable else None


def _owner(session: Session, table: _Table, row: Any) -> str | None:
    """The entity a row belongs to (its name labels it in a preview)."""
    validity = _VALIDITY.get(table.record_type)
    if validity is not None:
        return validity.entity_of(session, row)
    for name in _OWNERS:
        if hasattr(row, name):
            value = getattr(row, name)
            return None if value is None else str(value)
    return None


def _live(session: Session, table: _Table, row: Any) -> bool:
    if table.model is Event:
        entity = session.get(Entity, row.entity_id)
        return entity is not None and entity.deleted_at is None
    return getattr(row, "deleted_at", None) is None


# --- plans ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    """One row of the branch: ``action`` (``MOVE``, ``REPLACE``, …); ``other`` is the parent's row
    it replaces or changes."""

    table: _Table
    row_id: str
    action: str
    other: str | None = None


@dataclass(frozen=True)
class _Conflict:
    """A live record of the parent starting at or after the branch point."""

    table: _Table
    row_id: str
    discardable: bool

    @property
    def key(self) -> str:
        return f"{self.table.record_type}/{self.row_id}"


@dataclass
class _Plan:
    operation: Operation
    timeline_id: str
    parent_id: str  # re-parent: the new parent; merge: the parent merged into
    steps: list[_Step] = field(default_factory=list)
    conflicts: list[_Conflict] = field(default_factory=list)
    timelines: dict[str, str] = field(default_factory=dict)  # timeline → its new parent
    origins: dict[str, str | None] = field(default_factory=dict)  # entity → its new origin
    notes: list[str] = field(default_factory=list)  # notes moving to the parent
    notes_kept: int = 0
    siblings: list[str] = field(default_factory=list)  # branches that will see the merged records

    def key(self) -> str:
        """What the plan does, for the stale check."""
        document = [
            self.operation, self.timeline_id, self.parent_id,
            sorted([s.table.name, s.row_id, s.action, s.other or ""] for s in self.steps),
            sorted(c.key for c in self.conflicts), sorted(self.timelines.items()),
            sorted([k, v or ""] for k, v in self.origins.items()), sorted(self.notes),
        ]  # fmt: skip
        return json.dumps(document, separators=(",", ":"))


def _branch(session: Session, timeline_id: str) -> tuple[Entity, Timeline]:
    """A live branch (``404`` for a missing or trashed timeline, ``422`` for a prime)."""
    entity = session.get(Entity, timeline_id)
    row = session.get(Timeline, timeline_id)
    if entity is None or row is None or entity.deleted_at is not None:
        raise NotFoundError(f"No timeline {timeline_id}.")
    if row.parent_timeline_id is None:
        raise _invalid("timeline_id", "The prime timeline has no parent: only branches move.")
    return entity, row


def _children(session: Session, timeline_id: str) -> list[Timeline]:
    return list(
        session.scalars(
            select(Timeline)
            .where(Timeline.parent_timeline_id == timeline_id)
            .order_by(Timeline.entity_id)
        )
    )


def _subtree(session: Session, timeline_id: str) -> set[str]:
    found = {timeline_id}
    frontier = [timeline_id]
    while frontier:
        frontier = list(
            session.scalars(
                select(Timeline.entity_id).where(Timeline.parent_timeline_id.in_(frontier))
            )
        )
        found.update(frontier)
    return found


def _rows(session: Session, table: _Table, timeline_id: str, since: int | None = None) -> list[Any]:
    """The rows of ``timeline_id`` (trashed ones too), starting at or after ``since`` if given."""
    statement = select(table.model).where(_timeline_col(table) == timeline_id)
    if since is not None:
        statement = statement.where(getattr(table.model, table.bound.start) >= since)
    return list(session.scalars(statement.order_by(table.model.id)))


def _family(session: Session, table: _Table, root_id: str) -> list[Any]:
    """A root row and its overrides."""
    model = table.model
    overrides = getattr(model, table.bound.overrides)
    return list(
        session.scalars(
            select(model).where((model.id == root_id) | (overrides == root_id)).order_by(model.id)
        )
    )


def _seen(table: _Table, family: list[Any], entries: Iterable[Any]) -> Any:
    """The row of a family a lineage sees (the closest visible one), or ``None``. The rows of a
    family share their start."""
    by_timeline: dict[str, list[Any]] = {}
    for row in family:
        by_timeline.setdefault(getattr(row, table.bound.timeline), []).append(row)
    for entry in sorted(entries, key=lambda e: e.depth):
        for row in by_timeline.get(entry.timeline_id, []):
            start = _start(table, row)
            if start is None and not table.bound.open_start:
                continue
            if entry.cutoff is None or start is None or start < entry.cutoff:
                return row
    return None


def _discardable(table: _Table, row: Any) -> bool:
    """Events, facts and links go to the trash; overrides of any table are reverted."""
    return _overrides(table, row) is not None or table.record_type in ("event", "fact", "link")


def plan_merge(context: VaultContext, timeline_id: str) -> _Plan:
    session = context.session
    _entity, branch = _branch(session, timeline_id)
    parent_id = branch.parent_timeline_id
    assert parent_id is not None
    parent = session.get(Entity, parent_id)
    if parent is None or parent.deleted_at is not None:
        raise ConflictError("The branch's parent is in the trash: restore it first.")
    cutoff = branch.branch_t
    if cutoff is None:
        raise ConflictError("The branch point doesn't resolve: fix it before merging.")
    plan = _Plan("merge", timeline_id, parent_id)
    _plan_rows(session, plan, cutoff)
    for child in _children(session, timeline_id):
        plan.timelines[child.entity_id] = parent_id
    for child in _children(session, parent_id):
        if child.entity_id != timeline_id and child.branch_t is not None and (
            child.branch_t > cutoff
        ):  # fmt: skip
            plan.siblings.append(child.entity_id)
    parent_origin = origin_for(session, parent_id)
    for entity_id in session.scalars(
        select(Entity.id).where(Entity.origin_timeline_id == timeline_id).order_by(Entity.id)
    ):
        plan.origins[entity_id] = parent_origin
    _plan_notes(session, plan)
    return plan


def _plan_rows(session: Session, plan: _Plan, cutoff: int) -> None:
    """The branch's rows (each override by what the parent sees of its root) and the parent's
    live rows at or after the branch point (the conflicts)."""
    parent_lineage = lineage(session, plan.parent_id)
    for table in _tables():
        for row in _rows(session, table, plan.timeline_id):
            root_id = _overrides(table, row)
            if root_id is None:
                plan.steps.append(_Step(table, row.id, MOVE))
                continue
            seen = _seen(table, _family(session, table, root_id), parent_lineage)
            if seen is None or getattr(seen, table.bound.timeline) != plan.parent_id:
                plan.steps.append(_Step(table, row.id, REHOME))
            elif _overrides(table, seen) is not None:
                plan.steps.append(_Step(table, row.id, REPLACE, seen.id))
            else:
                plan.steps.append(_Step(table, row.id, APPLY, seen.id))
        for row in _rows(session, table, plan.parent_id, since=cutoff):
            if _live(session, table, row):
                plan.conflicts.append(_Conflict(table, row.id, _discardable(table, row)))


def _plan_notes(session: Session, plan: _Plan) -> None:
    """The branch's notes move to a parent branch that has none for their entity."""
    parent_row = session.get(Timeline, plan.parent_id)
    assert parent_row is not None
    for note in session.scalars(
        select(EntityTimelineNote)
        .where(EntityTimelineNote.timeline_id == plan.timeline_id)
        .order_by(EntityTimelineNote.id)
    ):
        taken = session.scalar(
            select(EntityTimelineNote.id).where(
                EntityTimelineNote.timeline_id == plan.parent_id,
                EntityTimelineNote.entity_id == note.entity_id,
            )
        )
        if parent_row.parent_timeline_id is not None and taken is None:
            plan.notes.append(note.id)
        else:
            plan.notes_kept += 1


def plan_reparent(context: VaultContext, timeline_id: str, new_parent_id: str) -> _Plan:
    session = context.session
    entity, branch = _branch(session, timeline_id)
    parent = session.get(Entity, new_parent_id)
    parent_row = session.get(Timeline, new_parent_id)
    if parent is None or parent_row is None or parent.deleted_at is not None:
        raise _invalid("parent_timeline_id", f"No timeline {new_parent_id}.", "not_found")
    if parent_row.dimension_id != branch.dimension_id:
        raise _invalid("parent_timeline_id", "The new parent must be a timeline of the branch's "
                       "dimension.")  # fmt: skip
    if new_parent_id == branch.parent_timeline_id:
        raise _invalid("parent_timeline_id", "That is already the branch's parent.")
    if new_parent_id in _subtree(session, timeline_id):
        raise _invalid("parent_timeline_id", "A branch can't move under itself or one of its "
                       "branches.")  # fmt: skip
    plan = _Plan("reparent", timeline_id, new_parent_id)
    plan.timelines[timeline_id] = new_parent_id
    origin = origin_for(session, new_parent_id)
    if entity.origin_timeline_id != origin:
        plan.origins[timeline_id] = origin
    # The branch's lineage once moved: the new parent's, cut at its branch point.
    cut = branch.branch_t if branch.branch_t is not None else 0
    entries = {e.timeline_id: cut if e.cutoff is None else min(cut, e.cutoff)
               for e in lineage(session, new_parent_id)}  # fmt: skip
    for table in _tables():
        if not table.overridable:
            continue
        for row in _rows(session, table, timeline_id):
            root_id = _overrides(table, row)
            if root_id is None:
                continue
            root = session.get(table.model, root_id)
            if root is None or not _spans(table, root, entries):
                plan.steps.append(_Step(table, row.id, DROP))
    return plan


def _spans(table: _Table, root: Any, entries: Mapping[str, int]) -> bool:
    """Whether a lineage (timeline → cut-off) inherits ``root`` spanning its cut-off."""
    cutoff = entries.get(getattr(root, table.bound.timeline))
    if cutoff is None:
        return False
    start, end = _start(table, root), _end(table, root)
    if start is None and not table.bound.open_start:
        return False
    return (start is None or start < cutoff) and (end is None or end > cutoff)


# --- executing -----------------------------------------------------------------------------------


@dataclass
class _Done:
    """What executing a plan did beyond moving rows."""

    pinned: list[str] = field(default_factory=list)
    discarded: int = 0
    touched: set[str] = field(default_factory=set)  # entities whose records changed


class _Slots:
    """The slot record type and id of a row, through the slot registry."""

    def __init__(self, context: VaultContext) -> None:
        self.providers: dict[Any, list[Any]] = {}
        for provider in context.registry.slot_registry().providers:
            self.providers.setdefault(provider.model, []).append(provider)

    def owner(self, row: Any) -> tuple[str, str] | None:
        for provider in self.providers.get(type(row), []):
            if provider.row_test is None or provider.row_test(
                {"overrides_id": getattr(row, "overrides_id", None)}
            ):
                return provider.record_type, str(getattr(row, provider.id_column))
        return None


def _event_specs(row: Event) -> list[tuple[str, TimePoint | EndSpec]]:
    found: list[tuple[str, TimePoint | EndSpec]] = [
        ("start", row.start_spec), ("end", parse_end_spec(row.end_spec))]  # fmt: skip
    rule = series.stored_rule(row)
    points = {} if rule is None else series.rule_points(rule)
    found += [(slot, point) for slot, (_p, point) in sorted(points.items())]
    return found


def _respec_event(writer: TimeWriter, row: Event, dimension_id: str) -> None:
    """A home row took new end and rule specs: its edges are written again (rule slots it no
    longer has lose theirs) and what is anchored to it resolves again."""
    for node in writer.index.slots_with_edges(series.EVENT, row.entity_id):
        writer.index.replace_edges(node, ())
    for slot, spec in _event_specs(row):
        writer.set_spec(series.EVENT, row.entity_id, slot, spec, dimension_id=dimension_id)
    writer.touch_series(row.entity_id)


def _revert(context: VaultContext, table: _Table, row_id: str) -> None:
    """Revert an override; time points anchored to a fact, link or validity override (its own
    slots) are pinned at their moments first."""
    session = context.session
    row = session.get(table.model, row_id)
    if row is None:
        return
    record_type = table.record_type
    if table.model is not Event:
        writer = TimeWriter(context)
        dependents = writer.index.dependents_of_record(record_type, row.id)
        writer.freeze(d for d in dependents if (d.type, d.id) != (record_type, row.id))
        writer.propagate(path="")
    revert_override(context, AUTHOR, record_type, row.id)


def _discard(context: VaultContext, table: _Table, row_id: str) -> None:
    """A conflicting record of the parent the merge discards: an override is reverted, an event
    (its entity), fact or link goes to the trash."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)
    from lore.core.facts.service import Facts  # noqa: PLC0415
    from lore.core.links.service import LinkService  # noqa: PLC0415

    session = context.session
    row = session.get(table.model, row_id)
    assert row is not None
    if _overrides(table, row) is not None:
        _revert(context, table, row_id)
    elif table.record_type == "event":
        EntityService(context).trash(row.entity_id)
    elif table.record_type == "fact":
        Facts(context).delete(row_id)
    elif table.record_type == "link":
        LinkService(session, context.registry, vault=context.vault).trash(row_id)


def _take_changes(context: VaultContext, table: _Table, root: Any, values: Mapping[str, Any],
                  dimension_id: str) -> None:  # fmt: skip
    """A record of the parent takes what the branch's override of it changed."""
    session = context.session
    if table.model is Event:
        for name in _EVENT_COLUMNS:
            setattr(root, name, values[name])
        root.revision += 1
        session.flush()
        writer = TimeWriter(context)
        _respec_event(writer, root, dimension_id)
        writer.propagate(path="")
        return
    changed = {k: v for k, v in values.items() if getattr(root, k) != v}
    if not changed:
        return
    if table.record_type in ("fact", "link"):
        _update_service(context, table.record_type, root, changed)
        return
    root.valid_to_spec = changed["valid_to_spec"]  # a module's validity record
    if root.valid_to_spec is None:
        root.valid_to_t = None
    session.flush()
    writer = TimeWriter(context)
    writer.set_spec(table.record_type, root.id, "valid_to", root.valid_to_spec,
                    dimension_id=dimension_id)  # fmt: skip
    writer.propagate(path="")


def _update_service(context: VaultContext, record_type: str, root: Any,
                    changed: Mapping[str, Any]) -> None:  # fmt: skip
    """A fact or link of the parent takes the changes through its service (checks, time fields,
    search)."""
    from lore.core.facts.schemas import FactUpdate  # noqa: PLC0415 (facts build on time)
    from lore.core.facts.service import Facts  # noqa: PLC0415
    from lore.core.links.schemas import LinkUpdate  # noqa: PLC0415
    from lore.core.links.service import LinkService  # noqa: PLC0415

    update: dict[str, Any] = {"revision": root.revision}
    for name, value in changed.items():
        update["valid_to" if name == "valid_to_spec" else name] = value
    if record_type == "fact":
        Facts(context).update(root.id, FactUpdate(**update))
    else:
        service = LinkService(context.session, context.registry, vault=context.vault)
        service.update(root.id, LinkUpdate(**update))


def _changes(table: _Table, row: Any) -> dict[str, Any]:
    """What an override may change, as it holds them."""
    if table.model is Event:
        return {name: getattr(row, name) for name in _EVENT_COLUMNS}
    names = {"fact": ("value", "valid_to_spec"), "link": ("role", "data", "valid_to_spec")}
    return {name: getattr(row, name) for name in names.get(table.record_type, ("valid_to_spec",))}


def _execute(context: VaultContext, plan: _Plan, chosen: Mapping[str, str]) -> _Done:
    session = context.session
    done = _Done()
    branch = session.get(Timeline, plan.timeline_id)
    assert branch is not None
    dimension_id = branch.dimension_id
    for conflict in plan.conflicts:
        if chosen.get(conflict.key) == DISCARD:
            row = session.get(conflict.table.model, conflict.row_id)
            owner = None if row is None else _owner(session, conflict.table, row)
            if owner is not None:
                done.touched.add(owner)
            _discard(context, conflict.table, conflict.row_id)
            done.discarded += 1
    moved = [row for step in plan.steps if (row := _step(context, plan, step, done)) is not None]
    _restructure(session, plan)
    # Anchors of the moved records resolve again in their new timeline.
    writer = TimeWriter(context)
    slots = _Slots(context)
    for row in moved:
        owner_slot = slots.owner(row)
        if owner_slot is not None:
            writer.touch(*writer.index.slots_with_edges(*owner_slot))
    writer.propagate(path="")
    if plan.operation == MERGE:
        _retire(context, plan.timeline_id)
    done.pinned = _pin_branch_points(context, dimension_id)
    return done


def _step(context: VaultContext, plan: _Plan, step: _Step, done: _Done) -> Any:
    """Carry out a step; returns the row when it moved to the parent."""
    session = context.session
    table = step.table
    if step.action == DROP:
        _revert(context, table, step.row_id)
        return None
    row = session.get(table.model, step.row_id)
    assert row is not None
    owner = _owner(session, table, row)
    if owner is not None:
        done.touched.add(owner)
    if step.action == APPLY:
        assert step.other is not None
        values = _changes(table, row)
        _revert(context, table, step.row_id)
        root = session.get(table.model, step.other)
        assert root is not None
        branch = session.get(Timeline, plan.timeline_id)
        assert branch is not None
        _take_changes(context, table, root, values, branch.dimension_id)
        return None
    if step.action == REPLACE:
        assert step.other is not None
        _revert(context, table, step.other)
        row = session.get(table.model, step.row_id)
        assert row is not None
    setattr(row, table.bound.timeline, plan.parent_id)  # MOVE, REHOME, REPLACE
    if isinstance(row, Event):
        row.revision += 1
    if hasattr(row, "updated_at"):
        row.updated_at = utc_now()
    return row


def _restructure(session: Session, plan: _Plan) -> None:
    """Timelines move, entities change origin, notes move."""
    for timeline_id, parent_id in sorted(plan.timelines.items()):
        row = session.get(Timeline, timeline_id)
        assert row is not None
        row.parent_timeline_id = parent_id
    for entity_id, origin in sorted(plan.origins.items()):
        entity = session.get(Entity, entity_id)
        assert entity is not None
        entity.origin_timeline_id = origin
        entity.updated_at = utc_now()
    for note_id in plan.notes:
        note = session.get(EntityTimelineNote, note_id)
        assert note is not None
        note.timeline_id = plan.parent_id
        note.updated_at = utc_now()
    session.flush()


def _retire(context: VaultContext, timeline_id: str) -> None:
    """The merged branch goes to the trash, empty; branch points anchored to its own branch
    point are pinned first."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    writer = TimeWriter(context)
    dependents = writer.index.dependents_of_record(TIMELINE, timeline_id)
    writer.freeze(d for d in dependents if (d.type, d.id) != (TIMELINE, timeline_id))
    writer.propagate(path="")
    EntityService(context).trash(timeline_id, cascade=True)


def _pin_branch_points(context: VaultContext, dimension_id: str) -> list[str]:
    """Branch points of the dimension anchored to records their parent doesn't see become
    ``absolute`` anchors at their moment (§4.7). Returns the timelines pinned."""
    session = context.session
    writer = TimeWriter(context)
    pinned_ids: list[str] = []
    rows = list(
        session.scalars(
            select(Timeline)
            .join(Entity, Entity.id == Timeline.entity_id)
            .where(
                Timeline.dimension_id == dimension_id,
                Timeline.parent_timeline_id.is_not(None),
                Entity.deleted_at.is_(None),
            )
            .order_by(Timeline.entity_id)
        )
    )
    resolver = Resolver(context, dimension_id)
    for row in rows:
        assert row.parent_timeline_id is not None
        if row.branch_point_spec is None or row.branch_t is None:
            continue
        node = SlotNode(TIMELINE, row.entity_id, BRANCH_POINT)
        if not hidden_targets(context, row.parent_timeline_id, writer.index.edges_of(node)):
            continue
        spec = pinned(row.branch_point_spec, row.branch_t, resolver.has_default_level)
        assert isinstance(spec, TimePoint)
        row.branch_point_spec = spec
        writer.set_spec(TIMELINE, row.entity_id, BRANCH_POINT, spec, dimension_id=dimension_id)
        pinned_ids.append(row.entity_id)
    session.flush()
    writer.propagate(path="")
    return pinned_ids


def _check_occurrences(session: Session, plan: _Plan) -> None:
    """The parent keeps at most one materialized occurrence per series and key (trashed ones
    count, as for re-keying)."""
    moving = {s.row_id for s in plan.steps if s.table.model is Event and s.action == MOVE}
    if not moving:
        return
    held: dict[tuple[str, str], list[str]] = {}
    rows = session.scalars(
        select(Event).where(
            Event.series_entity_id.is_not(None),
            Event.timeline_id.in_([plan.timeline_id, plan.parent_id]),
        )
    )
    for row in rows:
        if row.timeline_id == plan.parent_id or row.id in moving:
            assert row.series_entity_id is not None
            assert row.occurrence_key is not None
            held.setdefault((row.series_entity_id, row.occurrence_key), []).append(row.entity_id)
    conflicts = [
        {"series_id": s, "key": k, "entity_ids": sorted(v)}
        for (s, k), v in sorted(held.items())
        if len(v) > 1
    ]
    if conflicts:
        raise OccurrenceKeyConflictError(
            f"{len(conflicts)} occurrence(s) of a series are materialized in both timelines: "
            "detach one of each pair first.",
            context={"conflicts": conflicts},
        )


# --- proposals -----------------------------------------------------------------------------------


def _plan(context: VaultContext, timeline_id: str, payload: Mapping[str, Any]) -> _Plan:
    if payload["operation"] == REPARENT:
        return plan_reparent(context, timeline_id, payload["parent_timeline_id"])
    return plan_merge(context, timeline_id)


def _names(session: Session, ids: Iterable[str | None]) -> dict[str, str]:
    wanted = sorted({i for i in ids if i is not None})
    found: dict[str, str] = {}
    for start in range(0, len(wanted), 500):
        rows = session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(wanted[start : start + 500]))
        )
        found.update({str(i): str(n) for i, n in rows})
    return found


def _text(t: int | None) -> str | None:
    return None if t is None else str(t)


def _record(session: Session, table: _Table, row: Any) -> dict[str, Any]:
    return {
        "record_type": table.record_type,
        "id": row.id,
        "entity_id": _owner(session, table, row),
        "override": _overrides(table, row) is not None,
        "start_t": _text(_start(table, row)),
        "end_t": _text(_end(table, row)),
    }


def _impact(context: VaultContext, plan: _Plan, done: _Done) -> dict[str, Any]:
    session = context.session
    records = []
    for step in plan.steps:
        row = session.get(step.table.model, step.row_id)
        if row is not None:
            records.append({**_record(session, step.table, row), "action": step.action})
    conflicts = []
    for conflict in plan.conflicts:
        row = session.get(conflict.table.model, conflict.row_id)
        if row is not None:
            strategies = [KEEP, DISCARD] if conflict.discardable else [KEEP]
            conflicts.append({"key": conflict.key, **_record(session, conflict.table, row),
                              "strategies": strategies, "default_strategy": KEEP})  # fmt: skip
    timelines = [
        {"id": t, "from_parent_id": _parent_of(session, t), "to_parent_id": p}
        for t, p in sorted(plan.timelines.items())
    ]
    origins = [{"id": e, "to_origin_id": o} for e, o in sorted(plan.origins.items())]
    names = _names(session, [
        *(r["entity_id"] for r in (*records, *conflicts)), *plan.timelines,
        *(t["from_parent_id"] for t in timelines), *plan.origins, *done.pinned, *plan.siblings,
    ])  # fmt: skip
    for item in (*records, *conflicts):
        item["name"] = names.get(item["entity_id"] or "")
    for item in (*timelines, *origins):
        item["name"] = names.get(str(item["id"]))
    by_action: dict[str, int] = {}
    for step in plan.steps:
        by_action[step.action] = by_action.get(step.action, 0) + 1
    return {
        "operation": plan.operation,
        "parent_timeline_id": plan.parent_id,
        "records": records[:LISTED],
        "conflicts": conflicts,
        "timelines": timelines,
        "entities": origins[:LISTED],
        "pinned": [{"id": t, "name": names.get(t)} for t in done.pinned],
        "siblings": [{"id": t, "name": names.get(t)} for t in plan.siblings],
        "summary": {
            "records": len(records),
            "by_action": by_action,
            "conflicts": len(conflicts),
            "timelines": len(timelines),
            "entities": len(origins),
            "pinned": len(done.pinned),
            "notes_moved": len(plan.notes),
            "notes_kept": plan.notes_kept,
            "hidden_references": 0,
        },
        "plan": plan.key(),
    }


def _parent_of(session: Session, timeline_id: str) -> str | None:
    row = session.get(Timeline, timeline_id)
    return None if row is None else row.parent_timeline_id


def _hidden_references(context: VaultContext, timeline_id: str) -> int:
    """Slots of the timeline's own records anchored to records it doesn't see."""
    session = context.session
    slots = _Slots(context)
    writer = TimeWriter(context)
    count = 0
    for table in _tables():
        for row in _rows(session, table, timeline_id):
            owner = slots.owner(row)
            if owner is None:
                continue
            for node in writer.index.slots_with_edges(*owner):
                if hidden_targets(context, timeline_id, writer.index.edges_of(node)):
                    count += 1
    return count


def preview(context: VaultContext, timeline_id: str, payload: dict[str, Any]) -> Proposal:
    """``POST /m/branches/timelines/{id}/proposals``: the plan, dry-run inside a SAVEPOINT for
    the branch points it pins (every conflicting record kept), stored for an hour."""
    session = context.session
    plan = _plan(context, timeline_id, payload)
    _check_occurrences(session, plan)
    session.flush()
    hidden = 0
    with discarded(session):
        savepoint = session.begin_nested()
        try:
            done = _execute(context, plan, {})
            if plan.operation == REPARENT:
                hidden = _hidden_references(context, timeline_id)
        finally:
            savepoint.rollback()
    session.expire_all()
    impact = _impact(context, plan, done)
    impact["summary"]["hidden_references"] = hidden
    entity = session.get(Entity, timeline_id)
    assert entity is not None
    return save_proposal(
        session,
        kind=KIND,
        target_id=timeline_id,
        payload=payload,
        impact=impact,
        base_revision=entity.revision,
    )


@dataclass(frozen=True)
class Applied:
    operation: str
    moved: int
    discarded: int
    timelines: int
    pinned: int
    affected: Affected


def _strategy_error(key: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(
        message, errors=[ErrorItem(path=f"strategies.{key}", code=code, message=message)]
    )


def _chosen(plan: _Plan, strategies: Mapping[str, str], default: str) -> dict[str, str]:
    conflicts = {c.key: c for c in plan.conflicts}
    for key, strategy in strategies.items():
        conflict = conflicts.get(key)
        if conflict is None:
            raise _strategy_error(key, "The proposal has no such record.", "unknown_record")
        if strategy == DISCARD and not conflict.discardable:
            raise _strategy_error(key, "This record can only be kept.")
    return {
        key: strategies.get(key, default if c.discardable else KEEP) for key, c in conflicts.items()
    }


def apply(
    context: VaultContext,
    timeline_id: str,
    proposal_id: str,
    strategies: Mapping[str, str] | None = None,
    default_strategy: str = KEEP,
) -> Applied:
    """``POST /m/branches/timelines/{id}/proposals/{pid}/apply``: the plan again (``409
    proposal_stale`` when it differs from the preview's), executed as one changeset with a
    strategy per conflicting record (``keep`` unless given)."""
    session = context.session
    proposal = load_proposal(session, KIND, timeline_id, proposal_id)
    plan = _plan(context, timeline_id, proposal.payload)
    if plan.key() != proposal.impact.get("plan"):
        raise ProposalStaleError(
            "The timelines or their records changed since the preview: preview again.",
            context={"proposals": f"/m/branches/timelines/{timeline_id}/proposals"},
        )
    chosen = _chosen(plan, strategies or {}, default_strategy)
    _check_occurrences(session, plan)
    entity = session.get(Entity, timeline_id)
    parent = session.get(Entity, plan.parent_id)
    assert entity is not None
    assert parent is not None
    name, parent_name = entity.name, parent.name
    done = _execute(context, plan, chosen)
    session.delete(proposal)
    if plan.operation == REPARENT:
        describe(session, f"Moved the branch “{name}” under “{parent_name}”")
    else:
        describe(session, f"Merged the branch “{name}” into “{parent_name}”")
    session.flush()
    branch = session.get(Timeline, timeline_id)
    return Applied(
        operation=plan.operation,
        moved=sum(1 for s in plan.steps if s.action != DROP),
        discarded=done.discarded,
        timelines=len(plan.timelines),
        pinned=len(done.pinned),
        affected=Affected(
            entities=sorted(
                {timeline_id, plan.parent_id, *plan.timelines, *plan.origins, *done.pinned}
                | done.touched
            ),
            dimensions=[] if branch is None else [branch.dimension_id],
            time_changed=True,
            search_changed=True,
        ),
    )


__all__ = [
    "DISCARD",
    "KEEP",
    "KIND",
    "MERGE",
    "REPARENT",
    "Applied",
    "OccurrenceKeyConflictError",
    "apply",
    "missing_parent",
    "plan_merge",
    "plan_reparent",
    "preview",
]
