"""Anchor resolution (``time-model.md`` §5.2-§5.5, §6, §8): a time point or an end spec → its
moment, uncertainty extent, precision and resolution status, with the Python chronology engine.

    resolver = Resolver(context, dimension_id)
    start = resolver.resolve(point)                  # never raises for bad data: see .status/.error
    end = resolver.resolve_end(end_spec, start)
    t = require(start)                               # the moment, or the error as problem+json

Rules (technical choices documented in ``time-model.md`` §5.3 and §6):

- **Statuses, not exceptions.** A time point that can't be resolved comes back with a status
  (``invalid_date``, ``unresolved_ref``, ``calendar_error``, ``cycle``) and ``t = None``; one
  outside ``[0, D]`` has ``t`` and status ``out_of_bounds``; one whose anchor reaches a record in
  the trash has ``trashed_ref``. Specs that can never resolve (an unknown or unreferenceable slot,
  an occurrence ref to something other than an event) have no status (``None``). ``require``
  turns errors into problem+json (``invalid_date``, ``reform_gap``, ``reform_ambiguous``, …).
- **Relative anchors** use the target slot's stored (last good) moment; its extent and precision
  come from resolving the target's spec. The default precision is the coarser of the target's
  precision and the offset's finest unit (the longer unit at the resolved moment; ties keep the
  target's). An occurrence ref (``ref.occurrence``) uses the occurrence's moment: a
  ``modified`` materialized occurrence's own, else the one computed from the series' rule (with
  the series slot's extent width); a key without an occurrence is ``unresolved_ref``. With that
  precision the extent is the target's extent shifted by the offset; with
  another (explicit) precision it is ``[t, end of the precision unit containing t)``.
- **Precision calendar:** the level named by a precision belongs to the anchor's calendar, the
  offset's calendar (relative anchors with a calendar offset) or the dimension's default calendar
  (absolute anchors, relative anchors with a base offset).
- A ``VisibilityPolicy`` other than the author's resolves only through what it may see: a hidden
  calendar or slot owner is reported as ``unresolved_ref`` (never its moment).
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    add,
    from_fields,
    unit_bounds,
)
from lore.chronology.schema import (
    AbsoluteAnchor,
    BaseDuration,
    CalendarAnchor,
    CalendarDuration,
    Duration,
    DurationEnd,
    EndOfTimeEnd,
    EndSpec,
    InstantEnd,
    RelativeAnchor,
    TimePoint,
    TimePointEnd,
    UnknownEnd,
)
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import Calendar, Dimension, Event
from lore.core.time.slots import SlotError, SlotKey, SlotProvider, SlotRegistry
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.time.status import TimeStatus
from lore.core.visibility import AUTHOR, VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

BASE = "base"
EVENT = "event"
MAX_DEPTH = 64
"""How deep relative anchors may chain while resolving a target's extent (deeper: ``cycle``)."""

type ProblemCode = Literal[
    "invalid_date",
    "reform_gap",
    "reform_ambiguous",
    "out_of_bounds",
    "unresolved_ref",
    "calendar_error",
    "time_cycle",
    "unknown_slot",
    "slot_not_referenceable",
    "not_supported",
]


@dataclass(frozen=True)
class Problem:
    """Why a time point didn't resolve cleanly; ``path`` is relative to the time point."""

    code: ProblemCode
    message: str
    path: str = ""


@dataclass(frozen=True)
class Resolution:
    """A resolved time point (or end).

    ``t`` is the moment (``None`` when it couldn't be computed), ``extent`` the uncertainty
    extent ``[lo, hi)``, ``precision`` the precision used. ``status`` is ``None`` for specs that
    can never resolve (see the module docstring)."""

    t: int | None
    status: TimeStatus | None
    extent: tuple[int, int] | None = None
    precision: str = BASE
    approximate: bool = False
    problem: Problem | None = None
    calendar_id: str | None = None
    """The precision calendar (``None``: none, e.g. precision ``base`` without calendars)."""

    @property
    def ok(self) -> bool:
        return self.status in (TimeStatus.OK, TimeStatus.TRASHED_REF)


def _failed(
    status: TimeStatus | None, code: ProblemCode, message: str, path: str = ""
) -> Resolution:
    return Resolution(t=None, status=status, problem=Problem(code, message, path))


# --- problem+json -------------------------------------------------------------------------------


class TimeInvalidError(InvalidInputError):
    """A time point that doesn't resolve (``invalid_date``)."""

    code = "invalid_date"
    title = "Invalid date"


class ReformGapError(TimeInvalidError):
    code = "reform_gap"
    title = "Date in a calendar reform gap"


class ReformAmbiguousError(TimeInvalidError):
    code = "reform_ambiguous"
    title = "Ambiguous date across calendar regimes"


class TimeNotSupportedError(InvalidInputError):
    code = "not_supported"
    title = "Not supported yet"


_ERRORS: dict[str, type[InvalidInputError]] = {
    "reform_gap": ReformGapError,
    "reform_ambiguous": ReformAmbiguousError,
    "not_supported": TimeNotSupportedError,
}


def require(resolution: Resolution, path: str = "", *, trashed: bool = True) -> int:
    """The moment of a resolution that went well (``trashed_ref`` counts, unless ``trashed`` is
    false); its problem as a problem+json error otherwise (``422``: ``invalid_date``,
    ``reform_gap``, ``reform_ambiguous``, ``not_supported``, or ``invalid_date`` with the problem
    code in ``errors[].code`` for the rest)."""
    if (
        resolution.ok
        and resolution.t is not None
        and (trashed or resolution.status == TimeStatus.OK)
    ):
        return resolution.t
    problem = resolution.problem or Problem("unresolved_ref", "The anchor's target is trashed.")
    where = ".".join(part for part in (path, problem.path) if part)
    error_class = _ERRORS.get(problem.code, TimeInvalidError)
    raise error_class(
        problem.message, errors=[ErrorItem(path=where, code=problem.code, message=problem.message)]
    )


# --- the resolver -------------------------------------------------------------------------------


@dataclass
class _Calendars:
    """The calendars one resolver uses (compiled once per resolver)."""

    context: VaultContext
    dimension_id: str
    policy: VisibilityPolicy
    found: dict[str, CompiledCalendar | Resolution] = field(default_factory=dict)
    trashed: set[str] = field(default_factory=set)

    def get(self, calendar_id: str, path: str) -> CompiledCalendar | Resolution:
        """The compiled calendar, or a failed resolution saying why not."""
        if calendar_id not in self.found:
            self.found[calendar_id] = self._load(calendar_id)
        found = self.found[calendar_id]
        if isinstance(found, Resolution) and found.problem is not None:
            return replace(found, problem=replace(found.problem, path=path))
        return found

    def _load(self, calendar_id: str) -> CompiledCalendar | Resolution:
        from lore.core.time.calendars import compiled_calendar  # noqa: PLC0415 (import cycle)

        if calendar_id == ABSOLUTE_CALENDAR_ID:
            return _failed(None, "invalid_date", "The Absolute calendar has no units: use an "
                           "absolute anchor or a base duration.")  # fmt: skip
        session = self.context.session
        row = session.get(Calendar, calendar_id)
        entity = session.get(Entity, calendar_id)
        if (
            row is None
            or entity is None
            or row.dimension_id != self.dimension_id
            or not self.policy.visible_ids(session, [calendar_id])
        ):
            return _failed(TimeStatus.UNRESOLVED_REF, "unresolved_ref",
                           "No such calendar in this dimension.")  # fmt: skip
        if entity.deleted_at is not None:
            self.trashed.add(calendar_id)
        try:
            return compiled_calendar(self.context, calendar_id)
        except ConflictError:
            return _failed(TimeStatus.CALENDAR_ERROR, "calendar_error",
                           "The calendar's definition doesn't compile.")  # fmt: skip


class Resolver:
    """Resolves time points of one dimension (``timeline_id``: the timeline whose view relative
    anchors see; only the prime exists until M9, so it doesn't change anything yet)."""

    def __init__(
        self,
        context: VaultContext,
        dimension_id: str,
        timeline_id: str | None = None,
        policy: VisibilityPolicy = AUTHOR,
    ) -> None:
        self.context = context
        self.session = context.session
        self.dimension_id = dimension_id
        self.timeline_id = timeline_id
        self.policy = policy
        row = self.session.get(Dimension, dimension_id)
        if row is None:
            raise ConflictError("The dimension has no time spec.")
        self.duration: int = row.duration
        self.default_calendar_id: str | None = row.default_calendar_id
        self.slots: SlotRegistry = context.registry.slot_registry()
        self.calendars = _Calendars(context, dimension_id, policy)
        self.known: dict[SlotNode, Resolution] = {}
        """Slots resolved in the current propagation run: used instead of their stored values."""

    # --- time points --------------------------------------------------------------------------

    def resolve(self, point: TimePoint) -> Resolution:
        """Resolve a time point (§5.2-§5.4)."""
        return self._resolve(point, frozenset(), 0)

    def _resolve(
        self, point: TimePoint, seen: frozenset[tuple[str, str, str]], depth: int
    ) -> Resolution:
        anchor = point.anchor
        match anchor:
            case AbsoluteAnchor():
                result = self._absolute(anchor, point.precision)
            case CalendarAnchor():
                result = self._calendar(anchor, point.precision)
            case RelativeAnchor():
                result = self._relative(anchor, point.precision, seen, depth)
        return self._finish(replace(result, approximate=point.approximate))

    def _finish(self, result: Resolution) -> Resolution:
        """Bounds check and the trash status."""
        if result.t is None or not result.ok:
            return result
        if not 0 <= result.t <= self.duration:
            where = "before the inception" if result.t < 0 else "after the end"
            return replace(
                result,
                status=TimeStatus.OUT_OF_BOUNDS,
                problem=Problem("out_of_bounds", f"The moment lies {where} of the dimension."),
            )
        return result

    def _absolute(self, anchor: AbsoluteAnchor, precision: str) -> Resolution:
        t = int(anchor.t)
        if precision == BASE:
            return Resolution(t, TimeStatus.OK, (t, t + 1), BASE)
        return self._unit_extent(t, precision, self.default_calendar_id, "precision")

    def _calendar(self, anchor: CalendarAnchor, precision: str) -> Resolution:
        calendar = self.calendars.get(anchor.calendar_id, "anchor.calendar_id")
        if isinstance(calendar, Resolution):
            return calendar
        try:
            t = from_fields(
                calendar, anchor.fields, precision, era=anchor.era, regime=anchor.regime
            )
        except DateError as error:
            if error.level is not None and error.level in anchor.fields:
                path = f"anchor.fields.{error.level}"
            else:
                path = "precision" if error.level == precision else "anchor.fields"
            return _failed(TimeStatus.INVALID_DATE, _date_code(error), str(error), path)
        result = self._unit_extent(t, precision, anchor.calendar_id, "precision")
        return self._trash(result, anchor.calendar_id in self.calendars.trashed)

    def _unit_extent(
        self, t: int, precision: str, calendar_id: str | None, path: str
    ) -> Resolution:
        """``[t, end of the precision unit containing t)`` in a calendar."""
        if precision == BASE:
            return Resolution(t, TimeStatus.OK, (t, t + 1), BASE, calendar_id=calendar_id)
        if calendar_id is None:
            return _failed(TimeStatus.INVALID_DATE, "invalid_date",
                           f"Unknown precision {precision!r}: the dimension has no calendar.",
                           path)  # fmt: skip
        calendar = self.calendars.get(calendar_id, path)
        if isinstance(calendar, Resolution):
            return calendar
        if precision not in calendar.levels:
            return _failed(TimeStatus.INVALID_DATE, "invalid_date",
                           f"Unknown precision {precision!r}.", path)  # fmt: skip
        try:
            end = unit_bounds(calendar, t, precision).end
        except DateError:
            end = t + 1
        return Resolution(
            t, TimeStatus.OK, (t, max(end, t + 1)), precision, calendar_id=calendar_id
        )

    def _trash(self, result: Resolution, trashed: bool) -> Resolution:
        if trashed and result.status == TimeStatus.OK:
            return replace(result, status=TimeStatus.TRASHED_REF)
        return result

    # --- relative anchors ---------------------------------------------------------------------

    def _relative(
        self,
        anchor: RelativeAnchor,
        precision: str,
        seen: frozenset[tuple[str, str, str]],
        depth: int,
    ) -> Resolution:
        ref = anchor.ref
        try:
            self.slots.check_ref(ref)
        except SlotError as error:
            unreferenceable = error.code == "slot_not_referenceable"
            code: ProblemCode = "slot_not_referenceable" if unreferenceable else "unknown_slot"
            return _failed(None, code, str(error), "anchor.ref")
        if ref.occurrence is not None and ref.type != EVENT:
            return _failed(None, "not_supported", "Only events have occurrences.",
                           "anchor.ref.occurrence")  # fmt: skip
        target = self.slot(ref.type, ref.id, ref.slot, seen, depth)
        if target.ok and target.t is not None and ref.occurrence is not None:
            target = self._occurrence(
                ref.id, ref.slot, ref.occurrence, target, seen=seen, depth=depth
            )
        if not target.ok or target.t is None:
            return replace(target, problem=_at(target.problem, "anchor.ref"))
        return self._offset(target, anchor.offset, precision, "anchor.offset")

    def slot(
        self,
        record_type: str,
        record_id: str,
        slot: str,
        seen: frozenset[tuple[str, str, str]] = frozenset(),
        depth: int = 0,
    ) -> Resolution:
        """A stored slot as a resolution: its last good moment (``t``), with the extent and
        precision of its spec. ``unresolved_ref`` for a missing (purged), unset or hidden slot."""
        node = (record_type, record_id, slot)
        if node in seen or depth > MAX_DEPTH:
            return _failed(TimeStatus.CYCLE, "time_cycle", "The anchors form a cycle.")
        known = self.known.get(SlotNode(*node))
        if known is not None:
            return known
        provider, definition = self.slots.slot(record_type, slot)
        key = SlotKey(record_id, slot)
        value = self.slots.load(self.session, record_type, [key]).get(key)
        if value is None or value.t is None or not self._visible(provider, record_id):
            return _failed(TimeStatus.UNRESOLVED_REF, "unresolved_ref",
                           "The anchor's target doesn't exist (or has no moment).")  # fmt: skip
        t = value.t
        fresh: Resolution | None = None
        inner = seen | {node}
        if isinstance(value.spec, TimePoint):
            fresh = self._resolve(value.spec, inner, depth + 1)
        elif value.spec is not None and definition.spec == "end":
            start = self.slot(record_type, record_id, definition.start, inner, depth + 1)
            if start.ok:
                fresh = self._end(value.spec, start, inner, depth + 1)
        if fresh is not None and fresh.status == TimeStatus.CYCLE:
            return fresh
        if fresh is None or fresh.t is None or fresh.extent is None:
            result = Resolution(t, TimeStatus.OK, (t, t + 1), BASE)
        else:
            lo, hi = fresh.extent
            result = replace(
                fresh,
                t=t,
                status=TimeStatus.OK,
                extent=(t + lo - fresh.t, t + hi - fresh.t),
                problem=None,
            )
        trashed = value.trashed or (fresh is not None and fresh.status == TimeStatus.TRASHED_REF)
        return self._trash(result, trashed)

    def _occurrence(
        self,
        series_id: str,
        slot: str,
        key: str,
        series_slot: Resolution,
        *,
        seen: frozenset[tuple[str, str, str]],
        depth: int,
    ) -> Resolution:
        """Slot ``slot`` of occurrence ``key`` of a series (``recurrence.md`` §7): a
        ``modified`` materialized occurrence's own moment, else the computed one, with the width
        of the series slot's extent."""
        from lore.core.time import series  # noqa: PLC0415 (import cycle)

        row = self.session.scalar(
            select(Event).where(Event.entity_id == series_id, Event.overrides_id.is_(None))
        )
        if row is None or row.recurrence is None:
            return _failed(TimeStatus.UNRESOLVED_REF, "unresolved_ref",
                           "The anchor's target isn't a recurring event.",
                           "anchor.ref.occurrence")  # fmt: skip
        own = series.materialized_row(self.session, series_id, key, row.timeline_id)
        if own is not None and own.occurrence_state == series.MODIFIED:
            entity = self.session.get(Entity, own.entity_id)
            if entity is not None and entity.deleted_at is None:
                found = self.slot(EVENT, own.entity_id, slot, seen, depth + 1)
                if found.t is not None and found.status != TimeStatus.UNRESOLVED_REF:
                    return found
        start = series_slot if slot == "start" else self.slot(EVENT, series_id, "start", seen,
                                                               depth + 1)  # fmt: skip
        resolved: dict[str, int] = {}
        for point_slot, (pointer, _point) in series.rule_points(
            series.parse_rule(row.recurrence)
        ).items():
            moment = self.slot(EVENT, series_id, point_slot, seen, depth + 1).t
            if moment is not None:
                resolved[pointer] = moment
        computed = series.compute_occurrence(
            self, row, key, series_start=start.t, resolved=resolved
        )
        if isinstance(computed, series.RuleProblem):
            return _failed(TimeStatus.UNRESOLVED_REF, "unresolved_ref",
                           f"No occurrence {key!r}: {computed.message}",
                           "anchor.ref.occurrence")  # fmt: skip
        t = computed.start if slot == "start" else computed.end
        assert series_slot.t is not None
        assert series_slot.extent is not None
        lo, hi = series_slot.extent
        return replace(series_slot, t=t, extent=(t + lo - series_slot.t, t + hi - series_slot.t))

    def forget_calendar(self, calendar_id: str) -> None:
        """Compile the calendar again on its next use (its anchors or definition changed)."""
        self.calendars.found.pop(calendar_id, None)
        self.calendars.trashed.discard(calendar_id)

    def has_default_level(self, level: str) -> bool:
        """Whether the dimension's default calendar has a level (and compiles)."""
        if self.default_calendar_id is None:
            return False
        calendar = self.calendars.get(self.default_calendar_id, "")
        return not isinstance(calendar, Resolution) and level in calendar.levels

    def _visible(self, provider: SlotProvider, record_id: str) -> bool:
        return owner_visible(self.session, self.policy, provider, record_id)

    def _offset(
        self, target: Resolution, offset: Duration, precision: str | None, path: str
    ) -> Resolution:
        """``target`` moved by ``offset``; ``precision=None`` takes the default precision."""
        assert target.t is not None
        assert target.extent is not None
        mover = self._mover(offset, path)
        if isinstance(mover, Resolution):
            return mover
        try:
            t = mover(target.t)
        except DateError as error:
            return _failed(TimeStatus.INVALID_DATE, _date_code(error), str(error), path)
        offset_calendar = (
            offset.calendar_id if isinstance(offset, CalendarDuration) else self.default_calendar_id
        )
        default = self._coarser(target, offset, t)
        status = target.status
        if isinstance(offset, CalendarDuration) and offset.calendar_id in self.calendars.trashed:
            status = TimeStatus.TRASHED_REF
        if precision is None or precision == default:
            lo, hi = target.extent
            try:
                lo, hi = mover(lo), mover(hi)
            except DateError:
                lo, hi = t, t + 1
            calendar_id = target.calendar_id if default == target.precision else offset_calendar
            return Resolution(t, status, (lo, max(hi, lo + 1)), default, calendar_id=calendar_id)
        result = self._unit_extent(t, precision, offset_calendar, "precision")
        return replace(result, status=status) if result.ok else result

    def _mover(self, offset: Duration, path: str) -> Callable[[int], int] | Resolution:
        if isinstance(offset, BaseDuration):
            units = int(offset.units)
            return lambda t: t + units
        calendar = self.calendars.get(offset.calendar_id, f"{path}.calendar_id")
        if isinstance(calendar, Resolution):
            return calendar
        unknown = [level for level in offset.amounts if level not in calendar.levels]
        if unknown:
            return _failed(TimeStatus.INVALID_DATE, "invalid_date",
                           f"{unknown[0]!r} is not a level of the calendar.",
                           f"{path}.amounts.{unknown[0]}")  # fmt: skip
        return lambda t: add(calendar, t, offset)

    def _coarser(self, target: Resolution, offset: Duration, t: int) -> str:
        """The coarser of the target's precision and the offset's finest unit: the longer unit
        (the target's extent; the offset unit containing ``t``), the target's on a tie."""
        if isinstance(offset, BaseDuration):
            return target.precision
        calendar = self.calendars.get(offset.calendar_id, "")
        assert not isinstance(calendar, Resolution)  # _mover checked it
        amounts = [level for level, n in offset.amounts.items() if n != "0"] or list(offset.amounts)
        finest = min(amounts, key=calendar.level_index)
        assert target.extent is not None
        try:
            bounds = unit_bounds(calendar, t, finest)
            length = bounds.end - bounds.start
        except DateError:
            return target.precision
        target_length = target.extent[1] - target.extent[0]
        return finest if length > target_length else target.precision

    # --- ends ---------------------------------------------------------------------------------

    def resolve_end(self, end: EndSpec, start: Resolution) -> Resolution:
        """Resolve an end spec (§5.5) given its record's resolved start."""
        return self._end(end, start, frozenset(), 0)

    def _end(
        self,
        end: EndSpec,
        start: Resolution,
        seen: frozenset[tuple[str, str, str]],
        depth: int,
    ) -> Resolution:
        match end:
            case TimePointEnd():
                result = self._resolve(end.time_point, seen, depth)
                return replace(result, problem=_at(result.problem, "time_point"))
            case EndOfTimeEnd():
                d = self.duration
                return Resolution(d, TimeStatus.OK, (d, d + 1), BASE)
            case InstantEnd() | UnknownEnd():
                return start
            case DurationEnd():
                if start.t is None or start.extent is None or not start.ok:
                    return start
                result = self._offset(start, end.duration, None, "duration")
                return self._finish(replace(result, approximate=start.approximate))


def owner_visible(
    session: Session, policy: VisibilityPolicy, provider: SlotProvider, record_id: str
) -> bool:
    """Whether a policy may see the record owning a slot: through its entity
    (``entity_column``); records without one (link or fact rows) only by the author until their
    types get rules here."""
    if not policy.reader:
        return True
    if provider.entity_column is None:
        return False
    entity_id: str | None = record_id
    if provider.entity_column != provider.id_column:
        model: Any = provider.model
        entity_id = session.scalar(
            select(getattr(model, provider.entity_column)).where(
                getattr(model, provider.id_column) == record_id
            )
        )
    return bool(policy.visible_ids(session, [entity_id]))


def _at(problem: Problem | None, prefix: str) -> Problem | None:
    if problem is None:
        return None
    return replace(problem, path=".".join(part for part in (prefix, problem.path) if part))


def _date_code(error: DateError) -> ProblemCode:
    if error.code in ("reform_gap", "reform_ambiguous"):
        return error.code
    return "invalid_date"


__all__ = [
    "BASE",
    "Problem",
    "ReformAmbiguousError",
    "ReformGapError",
    "Resolution",
    "Resolver",
    "TimeInvalidError",
    "TimeNotSupportedError",
    "owner_visible",
    "require",
]
