"""What the narrative rules about existence share (``consistency.md`` §4, §6): existence periods
loaded in sets, and required orders between time slots checked in sets.

- **Existence.** An entity's ``core.exists`` facts in a timeline (``time-model.md`` §10.4),
  overlapping or touching periods merged (by stored moments). An entity without existence facts
  in a timeline exists at every time of it: nothing lies outside its existence.
- **Requirements.** A requirement holds when one of its alternatives does, and an alternative
  when all of its orders ``a ≤ b`` do. Bounds are time slots, or the open ends of time: an open
  start is before everything, an open end after everything. Its certainty of being violated is
  the least certain of its alternatives', each the most certain of its orders' (``compare.py``):
  stored moments select the candidates, and only their slots are loaded (``RuleContext.preload``).
- **Within.** A span lies within an existence when it lies within one of its periods. An open
  bound of the span is not checked: "from some time until the battle" says nothing about when the
  value started. A bound that doesn't resolve counts as open.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select

from lore.core.consistency.compare import DEFINITE, POSSIBLE, Certainty, violates_order, worst
from lore.core.consistency.engine import RuleContext
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.facts.models import EntityFact
from lore.core.time.models import Timeline

EXISTS = "core.exists"
FACT = "fact"
_BATCH = 5000


@dataclass(frozen=True)
class Bound:
    """A time slot with its stored moment."""

    record_type: str
    record_id: str
    slot: str
    t: int


class _Open:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


OPEN_START: Final = _Open("OPEN_START")  # before every moment
OPEN_END: Final = _Open("OPEN_END")  # after every moment
type Edge = Bound | _Open


@dataclass(frozen=True)
class Span:
    """``[start, end)`` in a timeline."""

    start: Edge
    end: Edge


def bound(record_type: str, record_id: str, slot: str, t: int | None, open_: _Open) -> Edge:
    """A slot's bound; an open one when it has no moment (no bound, or it doesn't resolve)."""
    return open_ if t is None else Bound(record_type, record_id, slot, t)


def span(record_type: str, record_id: str, start_t: int | None, end_t: int | None,
         slots: tuple[str, str] = ("valid_from", "valid_to")) -> Span:  # fmt: skip
    """A record's validity (or an event's span, with ``("start", "end")``)."""
    return Span(
        bound(record_type, record_id, slots[0], start_t, OPEN_START),
        bound(record_type, record_id, slots[1], end_t, OPEN_END),
    )


def chunks(ids: Iterable[str]) -> Iterator[list[str]]:
    wanted = sorted(set(ids))
    for start in range(0, len(wanted), _BATCH):
        yield wanted[start : start + _BATCH]


def dimensions_of(ctx: RuleContext) -> dict[str, str]:
    """Timeline id → its dimension's id."""
    return dict(ctx.session.execute(select(Timeline.entity_id, Timeline.dimension_id)).all())


# --- existence -----------------------------------------------------------------------------------


def _key(edge: Edge, *, start: bool) -> tuple[int, int]:
    if isinstance(edge, Bound):
        return (1, edge.t)
    return (0, 0) if start else (2, 0)


def merge(periods: Iterable[Span]) -> list[Span]:
    """Periods sorted by start, the overlapping or touching ones merged (stored moments)."""
    merged: list[Span] = []
    for period in sorted(periods, key=lambda p: _key(p.start, start=True)):
        last = merged[-1] if merged else None
        if last is not None and _key(period.start, start=True) <= _key(last.end, start=False):
            if _key(period.end, start=False) > _key(last.end, start=False):
                merged[-1] = Span(last.start, period.end)
            continue
        merged.append(period)
    return merged


class Existences:
    """Existence periods of entities per timeline, loaded in sets (``load``)."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self._loaded: set[str] = set()
        self._periods: dict[tuple[str, str], list[Span]] = {}

    def load(self, entity_ids: Iterable[str]) -> None:
        missing = set(entity_ids) - self._loaded
        found: dict[tuple[str, str], list[Span]] = {}
        for batch in chunks(missing):
            rows = self.ctx.session.execute(
                select(
                    EntityFact.id,
                    EntityFact.entity_id,
                    EntityFact.timeline_id,
                    EntityFact.valid_from_t,
                    EntityFact.valid_to_t,
                ).where(
                    EntityFact.entity_id.in_(batch),
                    EntityFact.field_key == EXISTS,
                    unindexed(EntityFact.deleted_at).is_(None),
                    unindexed(EntityFact.overrides_id).is_(None),
                )
            )
            for fact_id, entity_id, timeline_id, from_t, to_t in rows:
                found.setdefault((entity_id, timeline_id), []).append(
                    span(FACT, fact_id, from_t, to_t)
                )
        self._loaded |= missing
        for key, periods in found.items():
            self._periods[key] = merge(periods)

    def periods(self, entity_id: str, timeline_id: str) -> list[Span] | None:
        """The entity's merged periods in the timeline; ``None`` when it has none there (it
        exists at every time)."""
        return self._periods.get((entity_id, timeline_id))

    def timelines(self, entity_id: str) -> list[str]:
        """The timelines the entity has existence periods in."""
        return sorted(t for e, t in self._periods if e == entity_id)


def with_existence(ctx: RuleContext) -> frozenset[str]:
    """The entities with existence periods: only their existence can leave something outside,
    so scans start from them (a world records few lifespans, and many events)."""
    rows = ctx.session.execute(
        select(EntityFact.entity_id)
        .where(EntityFact.field_key == EXISTS, unindexed(EntityFact.deleted_at).is_(None))
        .distinct()
    )
    return frozenset(entity_id for (entity_id,) in rows)


def live(ctx: RuleContext, ids: Iterable[str]) -> dict[str, str]:
    """The names of the entities that aren't in the trash."""
    names: dict[str, str] = {}
    for batch in chunks(ids):
        rows = ctx.session.execute(
            select(Entity.id, Entity.name).where(
                Entity.id.in_(batch), unindexed(Entity.deleted_at).is_(None)
            )
        )
        names.update((entity_id, name) for entity_id, name in rows)
    return names


# --- requirements --------------------------------------------------------------------------------

type Order = tuple[Edge, Edge]  # a ≤ b
type Requirement = Sequence[Sequence[Order]]  # alternatives, each a conjunction of orders


def within(inner: Span, periods: Sequence[Span]) -> Requirement:
    """The inner span lies within one of the periods (its open bounds unchecked)."""
    alternatives: list[list[Order]] = []
    for period in periods:
        orders: list[Order] = []
        if isinstance(inner.start, Bound):
            orders.append((period.start, inner.start))
        if isinstance(inner.end, Bound):
            orders.append((inner.end, period.end))
        alternatives.append(orders)
    return alternatives


def overlapping(a: Span, b: Span) -> list[Order]:
    """The orders of two spans overlapping (non-strict: spans that touch count)."""
    return [(b.start, a.end), (a.start, b.end)]


def disjoint(a: Span, b: Span) -> Requirement:
    """Two spans don't overlap (spans that only touch don't)."""
    return [[(a.end, b.start)], [(b.end, a.start)]]


def _may_violate(order: Order) -> bool:
    a, b = order
    if a is OPEN_START or b is OPEN_END:
        return False
    if isinstance(a, Bound) and isinstance(b, Bound):
        return a.t > b.t
    return True  # an open end before something, or something before an open start


class Requirements:
    """Requirements checked together: those their stored moments may violate (``want``) have
    their slots loaded in sets (``load``), then ``violated`` compares extents."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self._wanted: dict[tuple[str, str], set[tuple[str, str]]] = {}

    def want(self, dimension_id: str, requirement: Requirement) -> bool:
        """Whether the stored moments may violate the requirement (noting its slots)."""
        if not all(any(_may_violate(o) for o in orders) for orders in requirement):
            return False
        for orders in requirement:
            for order in orders:
                if _may_violate(order):
                    for edge in order:
                        if isinstance(edge, Bound):
                            self._wanted.setdefault((dimension_id, edge.record_type), set()).add(
                                (edge.record_id, edge.slot)
                            )
        return True

    def load(self) -> None:
        for (dimension_id, record_type), slots in self._wanted.items():
            self.ctx.preload(dimension_id, record_type, slots)
        self._wanted.clear()

    def _order(self, dimension_id: str, order: Order) -> Certainty | None:
        if not _may_violate(order):
            return None
        a, b = order
        if not (isinstance(a, Bound) and isinstance(b, Bound)):
            return DEFINITE
        first = self.ctx.point(dimension_id, a.record_type, a.record_id, a.slot)
        second = self.ctx.point(dimension_id, b.record_type, b.record_id, b.slot)
        if first is None or second is None:
            return None
        return violates_order(first, second)

    def violated(self, dimension_id: str, requirement: Requirement) -> Certainty | None:
        """How certainly the requirement is violated (no alternatives: definitely)."""
        found = [worst(*(self._order(dimension_id, o) for o in orders)) for orders in requirement]
        if None in found:
            return None
        return POSSIBLE if POSSIBLE in found else DEFINITE


__all__ = [
    "EXISTS",
    "OPEN_END",
    "OPEN_START",
    "Bound",
    "Existences",
    "Requirements",
    "Span",
    "chunks",
    "dimensions_of",
    "disjoint",
    "live",
    "merge",
    "overlapping",
    "span",
    "with_existence",
    "within",
]
