"""The dependency graph of time slots (``time-model.md`` §7.1): edge extraction from specs and
``DependencyIndex``, the ``time_dependencies`` table's API.

A **dependent** is always a slot of a record (a calendar's own anchors are slots of record type
``calendar``: ``alignment``, ``era:<id>``, …). A **target** is a slot, a calendar or a
dimension's duration:

| Spec | Edges |
|------|-------|
| absolute anchor | none |
| calendar anchor | the calendar (none for the virtual ``absolute`` calendar) |
| relative anchor | the referenced slot (also for occurrence refs: occurrences derive from the
  series), plus the offset's calendar for a calendar offset |
| local anchor (calendar definitions) | none: the calendar being defined |
| end ``time_point`` | the time point's edges |
| end ``duration`` | the record's own start slot, plus the duration's calendar |
| end ``instant`` / ``unknown`` | the record's own start slot (both resolve to the start) |
| end ``end_of_time`` | the dimension (its duration ``D``) |
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, delete, insert, select
from sqlalchemy.orm import Session

from lore.chronology.schema import (
    CalendarDuration,
    DefinitionTimePoint,
    DurationEnd,
    EndOfTimeEnd,
    EndSpec,
    InstantEnd,
    TimePoint,
    TimePointEnd,
    UnknownEnd,
)
from lore.chronology.schema import Duration as DurationSpec
from lore.core.time.models import TimeDependency
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID

DIMENSION = "dimension"


@dataclass(frozen=True, order=True)
class SlotNode:
    """A time slot of a record."""

    type: str
    id: str
    slot: str


@dataclass(frozen=True, order=True)
class CalendarNode:
    """A calendar (its definition and its own anchors)."""

    calendar_id: str


@dataclass(frozen=True, order=True)
class DimensionNode:
    """A dimension's duration ``D`` (what ``end_of_time`` resolves to)."""

    dimension_id: str


type Target = SlotNode | CalendarNode | DimensionNode


class MissingContextError(ValueError):
    """An end spec needs the owner's start slot or dimension to extract its edges."""


# --- extraction ----------------------------------------------------------------------------------


def duration_targets(duration: DurationSpec) -> set[Target]:
    if isinstance(duration, CalendarDuration):
        return _calendar(duration.calendar_id)
    return set()


def time_point_targets(point: TimePoint | DefinitionTimePoint) -> set[Target]:
    """The targets a time point depends on."""
    anchor = point.anchor
    match anchor.kind:
        case "calendar":
            return _calendar(anchor.calendar_id)
        case "relative":
            node = SlotNode(anchor.ref.type, anchor.ref.id, anchor.ref.slot)
            return {node} | duration_targets(anchor.offset)
        case _:  # absolute, local
            return set()


def end_targets(
    end: EndSpec, *, start: SlotNode | None = None, dimension_id: str | None = None
) -> set[Target]:
    """The targets of an end spec. ``start`` is the owner's start slot (duration, instant and
    unknown ends resolve from it), ``dimension_id`` its dimension (``end_of_time``)."""
    match end:
        case TimePointEnd():
            return time_point_targets(end.time_point)
        case DurationEnd():
            return {_need(start, "start", end)} | duration_targets(end.duration)
        case InstantEnd() | UnknownEnd():
            return {_need(start, "start", end)}
        case EndOfTimeEnd():
            return {DimensionNode(_need(dimension_id, "dimension_id", end))}


def _calendar(calendar_id: str) -> set[Target]:
    return set() if calendar_id == ABSOLUTE_CALENDAR_ID else {CalendarNode(calendar_id)}


def _need[T](value: T | None, name: str, end: EndSpec) -> T:
    if value is None:
        raise MissingContextError(f"an end of kind {end.kind!r} needs {name}")
    return value


# --- the table -----------------------------------------------------------------------------------


def _target_columns(target: Target) -> dict[str, str | None]:
    match target:
        case SlotNode():
            return {
                "target_kind": "slot",
                "target_type": target.type,
                "target_id": target.id,
                "target_slot": target.slot,
                "target_calendar_id": None,
            }
        case CalendarNode():
            return {
                "target_kind": "calendar",
                "target_type": None,
                "target_id": None,
                "target_slot": None,
                "target_calendar_id": target.calendar_id,
            }
        case DimensionNode():
            return {
                "target_kind": DIMENSION,
                "target_type": DIMENSION,
                "target_id": target.dimension_id,
                "target_slot": None,
                "target_calendar_id": None,
            }


def _target_of(row: TimeDependency) -> Target:
    match row.target_kind:
        case "slot":
            return SlotNode(str(row.target_type), str(row.target_id), str(row.target_slot))
        case "calendar":
            return CalendarNode(str(row.target_calendar_id))
        case _:
            return DimensionNode(str(row.target_id))


def _target_filter(target: Target) -> ColumnElement[bool]:
    columns = _target_columns(target)
    T = TimeDependency  # noqa: N806
    match target:
        case CalendarNode():
            return T.target_calendar_id == target.calendar_id
        case _:
            return and_(
                T.target_kind == columns["target_kind"],
                T.target_type == columns["target_type"],
                T.target_id == columns["target_id"],
                T.target_slot.is_(None)
                if columns["target_slot"] is None
                else T.target_slot == columns["target_slot"],
            )


def _dependent_filter(dependent: SlotNode) -> ColumnElement[bool]:
    T = TimeDependency  # noqa: N806
    return and_(
        T.dependent_type == dependent.type,
        T.dependent_id == dependent.id,
        T.dependent_slot == dependent.slot,
    )


class DependencyIndex:
    """Reads and rewrites ``time_dependencies`` inside the caller's transaction.

    ``replace_edges`` runs whenever a slot's spec is written (``time-model.md`` §7.2 step 1).
    The table is derived data: Core statements are fine and history doesn't record it.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_edges(self, dependent: SlotNode, targets: Iterable[Target]) -> None:
        """Make ``targets`` the dependent's only outgoing edges (duplicates are dropped)."""
        self.session.execute(delete(TimeDependency).where(_dependent_filter(dependent)))
        rows = [
            {
                "dependent_type": dependent.type,
                "dependent_id": dependent.id,
                "dependent_slot": dependent.slot,
                **_target_columns(target),
            }
            for target in sorted(set(targets), key=_sort_key)
        ]
        if rows:
            self.session.execute(insert(TimeDependency), rows)

    def edges_of(self, dependent: SlotNode) -> list[Target]:
        """The dependent's targets, sorted."""
        rows = self.session.scalars(select(TimeDependency).where(_dependent_filter(dependent)))
        return sorted((_target_of(row) for row in rows), key=_sort_key)

    def dependents_of(self, target: Target) -> list[SlotNode]:
        """Slots with an edge to ``target``, sorted."""
        rows = self.session.execute(
            select(
                TimeDependency.dependent_type,
                TimeDependency.dependent_id,
                TimeDependency.dependent_slot,
            )
            .where(_target_filter(target))
            .distinct()
        )
        return sorted(SlotNode(*row) for row in rows)

    def dependents_of_record(self, record_type: str, record_id: str) -> list[SlotNode]:
        """Slots with an edge to any slot of a record (trash and purge, ``time-model.md``
        §7.3), sorted."""
        T = TimeDependency  # noqa: N806
        rows = self.session.execute(
            select(T.dependent_type, T.dependent_id, T.dependent_slot)
            .where(T.target_kind == "slot", T.target_type == record_type, T.target_id == record_id)
            .distinct()
        )
        return sorted(SlotNode(*row) for row in rows)

    def drop_record(self, record_type: str, record_id: str) -> None:
        """Remove the outgoing edges of every slot of a record (it was purged)."""
        T = TimeDependency  # noqa: N806
        self.session.execute(
            delete(T).where(T.dependent_type == record_type, T.dependent_id == record_id)
        )


def _sort_key(target: Target) -> tuple[int, tuple[str, ...]]:
    match target:
        case SlotNode():
            return (0, (target.type, target.id, target.slot))
        case CalendarNode():
            return (1, (target.calendar_id,))
        case DimensionNode():
            return (2, (target.dimension_id,))
