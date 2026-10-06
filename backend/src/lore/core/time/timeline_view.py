"""``TimelineView``: the one query helper for time-bound tables (``time-model.md`` §4.2-§4.6,
ADR-0008).

Every read of a time-bound table (events, facts, temporal links, worldline segments, module
records with validity) goes through a view of the timeline it is read in::

    view = TimelineView.for_timeline(session, timeline_id)   # computes the lineage once
    stmt = view.select(Event)                                 # lineage visibility + overrides
    stmt = stmt.where(view.overlaps(Event, window_start, window_end))

**Hand-rolled lineage SQL is forbidden** (``CLAUDE.md`` rule 5): no other code walks
``parent_timeline_id``, compares ``branch_t`` cut-offs or resolves ``overrides_id``. If a query
can't be written with this helper, extend the helper.

A view only knows timelines: it checks neither the reader's visibility nor the trash. Callers load
the timeline through their ``VisibilityPolicy`` first and add the policy's conditions (and trash
filters) to the statement, row filters that must apply *before* override resolution through
``where=``.

Tables register their columns with ``register_time_bound`` (``links`` is registered here; a
module registers its tables when its models are imported).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    String,
    and_,
    column,
    func,
    inspect,
    or_,
    select,
    values,
)
from sqlalchemy.orm import Session, aliased

from lore.chronology.numbers import sortable_key
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.time.models import Timeline

type Conditions = list[ColumnElement[bool]]
type RowFilter = Callable[[Any], Iterable[ColumnElement[bool]]]

# Sorts after every sortable key (their 4-digit length prefix is at most "1000"): the cut-off of
# the viewed timeline itself, which sees all of its own records (+∞).
UNBOUNDED_KEY = "9"
# Longer lineages mean corrupt data (a cycle) rather than a deep tree.
MAX_DEPTH = 10_000


@dataclass(frozen=True)
class TimeBound:
    """How a time-bound table stores its time (``time-model.md`` §4.3).

    ``start``/``end`` name the moment columns (``SortableBigInt``). ``open_start``: a NULL start
    is minus infinity (validity tables: always inherited); otherwise rows with a NULL start are
    never visible. ``open_end``: a NULL end is plus infinity. Without an ``end`` column a record is
    an instant at its start.
    """

    model: type
    start: str
    end: str | None = None
    open_start: bool = False
    open_end: bool = False
    timeline: str = "timeline_id"
    overrides: str = "overrides_id"
    id: str = "id"


_REGISTRY: dict[type, TimeBound] = {}


def register_time_bound(bound: TimeBound) -> TimeBound:
    """Registers a time-bound table (idempotent for the same declaration)."""
    known = _REGISTRY.get(bound.model)
    if known is not None and known != bound:
        raise ValueError(f"{bound.model.__name__} is already registered differently")
    _REGISTRY[bound.model] = bound
    return bound


def time_bound(model: type) -> TimeBound:
    """The registration of ``model``."""
    try:
        return _REGISTRY[model]
    except KeyError:
        raise ValueError(f"{model.__name__} is not a registered time-bound table") from None


# Facts and temporal links: half-open validity, NULL bounds unbounded (time-model.md §10.1).
register_time_bound(
    TimeBound(Link, start="valid_from_t", end="valid_to_t", open_start=True, open_end=True)
)


@dataclass(frozen=True)
class LineageEntry:
    """``(timeline, cutoff)`` at ``depth`` (0 = the viewed timeline). ``cutoff`` None is +∞."""

    timeline_id: str
    cutoff: int | None
    depth: int


def lineage(session: Session, timeline_id: str) -> list[LineageEntry]:
    """The lineage of a timeline (``time-model.md`` §4.2): itself with cut-off +∞, then each
    ancestor with ``cutoff_{i+1} = min(cutoff_i, b(L_i))``.

    A branch whose branch point never resolved (``branch_t`` NULL) has cut-off 0: it inherits
    nothing until it resolves. Raises ``NotFoundError`` for a timeline that doesn't exist.
    """
    entries: list[LineageEntry] = []
    seen: set[str] = set()
    current: str | None = timeline_id
    cutoff: int | None = None
    while current is not None:
        if current in seen or len(entries) >= MAX_DEPTH:
            raise RuntimeError(f"the ancestry of timeline {timeline_id} has a cycle")
        row = session.get(Timeline, current)
        if row is None:
            if not entries:
                raise NotFoundError(f"No timeline {timeline_id}.")
            raise RuntimeError(f"timeline {entries[-1].timeline_id} has a missing parent")
        seen.add(current)
        entries.append(LineageEntry(current, cutoff, len(entries)))
        if row.parent_timeline_id is not None:
            branch = row.branch_t if row.branch_t is not None else 0
            cutoff = branch if cutoff is None else min(cutoff, branch)
        current = row.parent_timeline_id
    return entries


class TimelineView:
    """Time-bound rows as one timeline sees them. Build it with ``for_timeline``."""

    def __init__(self, entries: list[LineageEntry]) -> None:
        if not entries:
            raise ValueError("a lineage has at least the viewed timeline")
        self.lineage = tuple(entries)
        self.timeline_id = entries[0].timeline_id

    @classmethod
    def for_timeline(cls, session: Session, timeline_id: str) -> TimelineView:
        """The view of ``timeline_id``; its lineage is read once, here."""
        return cls(lineage(session, timeline_id))

    @property
    def timeline_ids(self) -> tuple[str, ...]:
        """The viewed timeline and its ancestors, nearest first."""
        return tuple(entry.timeline_id for entry in self.lineage)

    # --- time-bound rows ------------------------------------------------------------------------

    @cached_property
    def _lineage_cte(self) -> Any:
        """Built once: statements combining several selects of a view share one ``lineage``."""
        table = values(
            column("timeline_id", String),
            column("cutoff_key", String),
            column("depth", Integer),
            name="lineage",
        ).data(
            [
                (
                    e.timeline_id,
                    UNBOUNDED_KEY if e.cutoff is None else sortable_key(e.cutoff),
                    e.depth,
                )
                for e in self.lineage
            ]
        )
        return table.cte("lineage")

    def select(
        self,
        model: type,
        *,
        where: RowFilter | None = None,
        window: tuple[int, int] | None = None,
    ) -> Select[Any]:
        """``SELECT model`` restricted to the rows visible in this timeline (§4.3), exactly one
        per root after override resolution (§4.4: the smallest lineage depth wins).

        ``where`` gives conditions on the candidate rows (called with the row alias) that apply
        *before* resolution, such as a trash filter: a trashed override then falls back to the
        row it overrides. Conditions added to the returned statement apply after it.

        ``window=(w0, w1)`` keeps the records overlapping ``[w0, w1)`` (``overlaps``); the bound
        on the start is applied before resolution too (an override starts where its root does),
        so the lineage index ``(timeline_id, start)`` narrows the scan.
        """
        bound = time_bound(model)
        row: Any = aliased(model)
        lineage = self._lineage_cte
        start = getattr(row, bound.start)
        visible = start < lineage.c.cutoff_key
        if bound.open_start:
            visible = or_(start.is_(None), visible)
        conditions: Conditions = [visible]
        if where is not None:
            conditions.extend(where(row))
        if window is not None:
            conditions.append(self._starts_before(bound, row, *window))
        row_id = getattr(row, bound.id)
        rank = (
            func.row_number()
            .over(
                partition_by=func.coalesce(getattr(row, bound.overrides), row_id),
                order_by=(lineage.c.depth, row_id),
            )
            .label("rank")
        )
        ranked = (
            select(row_id.label("id"), rank)
            .join(lineage, getattr(row, bound.timeline) == lineage.c.timeline_id)
            .where(*conditions)
            .subquery("resolved")
        )
        statement: Select[Any] = (
            select(model)
            .join(ranked, ranked.c.id == getattr(model, bound.id))
            .where(ranked.c.rank == 1)
        )
        if window is not None:
            statement = statement.where(self.overlaps(model, *window))
        return statement

    @staticmethod
    def _starts_before(bound: TimeBound, row: Any, w0: int, w1: int) -> ColumnElement[bool]:
        _check_window(w0, w1)
        start = getattr(row, bound.start)
        condition = start < w1 if w0 < w1 else start <= w0
        return or_(start.is_(None), condition) if bound.open_start else condition

    def overlaps(self, model: Any, w0: int, w1: int) -> ColumnElement[bool]:
        """Records whose span overlaps the half-open window ``[w0, w1)`` (``time-model.md``
        §2.1): ``start < w1 and w0 < end``, where instants (``start = end``, or ``w0 = w1``) count
        at their moment. ``model`` is the registered model or an alias of it."""
        bound = _bound_of(model)
        start = getattr(model, bound.start)
        before = self._starts_before(bound, model, w0, w1)
        if bound.end is None:
            after = start >= w0  # an instant at start: w0 <= start
            return and_(before, or_(start.is_(None), after) if bound.open_start else after)
        end = getattr(model, bound.end)
        after = or_(end > w0, and_(end == w0, start == w0))
        if bound.open_end:
            after = or_(end.is_(None), after)
        return and_(before, after)

    def covering(self, model: Any, t: int) -> ColumnElement[bool]:
        """Records whose span covers moment ``t``: ``start <= t < end``, or an instant at ``t``."""
        return self.overlaps(model, t, t)

    # --- entities -------------------------------------------------------------------------------

    def entities(self, entity: Any) -> Conditions:
        """Conditions for the entities visible in this timeline (``time-model.md`` §4.6): those
        created in a prime timeline (or timeless, ``origin_timeline_id`` NULL) and the branch-only
        entities of this timeline and its ancestors. ``entity`` is ``Entity`` or an alias."""
        origin = entity.origin_timeline_id
        return [or_(origin.is_(None), origin.in_(self.timeline_ids))]

    def shows_entity(self, origin_timeline_id: str | None) -> bool:
        """``entities`` for one loaded entity."""
        return origin_timeline_id is None or origin_timeline_id in self.timeline_ids


def _check_window(w0: int, w1: int) -> None:
    if w0 > w1:
        raise ValueError(f"the window [{w0}, {w1}) ends before it starts")


def _bound_of(model: Any) -> TimeBound:
    """The registration of a model or an alias of one."""
    return time_bound(inspect(model).mapper.class_)


__all__ = [
    "LineageEntry",
    "TimeBound",
    "TimelineView",
    "lineage",
    "register_time_bound",
    "time_bound",
]
