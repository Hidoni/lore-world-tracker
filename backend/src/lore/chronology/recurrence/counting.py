"""Counting positions of calendar rules with super-periods (``recurrence.md`` §5.4).

``n(k)`` is the number of positions of candidate period ``k`` (``None`` positions excluded) and
``S(K) = Σ_{k<K} n(k)``. Inside a stretch of years without calendar exceptions, ``n`` is periodic
in ``k``: shifting ``k`` by the **super-period** ``Q`` shifts time by ``M`` whole periods of the
top pattern, which preserves the calendar structure, the interval alignment, every ``mod``
filter's residue and the phase of every continuous cycle the rule uses. Periods that overlap an
exception year are counted one by one; every clean stretch gets the prefix sums of its own first
``Q`` periods (after an exception, ordinals and cycle phases may be shifted). The total number of
periods enumerated is limited (:data:`ENUM_LIMIT`, ``rule.too_complex_to_count`` beyond).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from itertools import accumulate
from math import gcd, lcm
from typing import TYPE_CHECKING

from lore.chronology.calendar.units import cycle_filter, units_per_period
from lore.chronology.schema import (
    AllFilter,
    AnyFilter,
    CycleFilter,
    CycleSelector,
    InFilter,
    ModFilter,
    NotFilter,
    PeriodFilter,
)

if TYPE_CHECKING:
    from lore.chronology.recurrence.calendar_rules import CalendarPlan

ENUM_LIMIT = 1_000_000
"""Most candidate periods enumerated to build the counts (one super-period, exception years and
short stretches together)."""


class TooComplex(Exception):  # noqa: N818 (an internal signal, not an error for callers)
    """The rule can't be counted by super-periods (aperiodic, or too many periods to enumerate)."""


@dataclass(slots=True)
class _Segment:
    """Periods ``[start, end)`` (``end`` ``None``: unbounded) with their counts."""

    start: int
    end: int | None
    dirty: bool = False
    """The periods overlap exception years: always counted one by one."""
    prefix: list[int] = field(default_factory=list)
    """Counts before each of the first periods (length = enumerated periods + 1)."""
    periodic: bool = False
    """``prefix`` covers one super-period and repeats over the whole segment."""

    def total(self, q: int) -> int:
        assert self.end is not None
        return self._upto(self.end - self.start, q)

    def _upto(self, length: int, q: int) -> int:
        if not self.periodic:
            return self.prefix[length]
        full, rest = divmod(length, q)
        return full * self.prefix[-1] + self.prefix[rest]


def _needs(a: int, b: int) -> int:
    """The smallest ``M ≥ 1`` with ``M·a ≡ 0 (mod b)``."""
    return b // gcd(a, b)


class Counter:
    def __init__(self, plan: CalendarPlan) -> None:
        self.plan = plan
        self.enumerated = 0
        self.q = self._super_period()
        self.segments = self._segments()
        self.before: list[int] = [0]
        """``S`` at the start of each segment whose predecessors are summed so far."""

    # super-period

    def _super_period(self) -> int:
        plan = self.plan
        regime, top = plan.regime, plan.top
        needs: list[int] = []
        cycles = set()
        if plan.rounds is None:
            units = units_per_period(regime, plan.level, top)
            needs.append(_needs(units, plan.interval))
            step_units, step_size = units, 1
        else:
            cycles.add(plan.rounds.id)
            units = units_per_period(regime, plan.level, top, cycle_filter(plan.rounds.id))
            needs.append(_needs(units, plan.rounds.length * plan.interval))
            step_units, step_size = units, plan.rounds.length
        for item in plan.rule.filters:
            self._filter_needs(item, needs, cycles, step_units, step_size)
        if plan.rule.select is not None:
            cycles.update(s.cycle.id for s in plan.rule.select.path if isinstance(s, CycleSelector))
        for cycle in regime.cycles:
            if cycle.id in cycles and cycle.reset is None:
                counted = units_per_period(regime, cycle.level, top, cycle_filter(cycle.id))
                needs.append(_needs(counted, cycle.length))
        if units == 0:
            raise TooComplex("the period level has no units in the regular pattern")
        m = lcm(*needs)
        q = m * units // (step_size * plan.interval)
        if q > ENUM_LIMIT:
            raise TooComplex(f"a super-period holds {q} candidate periods")
        return q

    def _filter_needs(
        self, item: PeriodFilter, needs: list[int], cycles: set[str], units: int, size: int
    ) -> None:
        plan = self.plan
        if isinstance(item, ModFilter):
            mod = int(item.mod)
            if item.of == "ordinal" or plan.rounds is not None:
                needs.append(_needs(units, size * mod))
            elif plan.level == plan.top:
                needs.append(_needs(plan.regime.period, mod))
        elif isinstance(item, InFilter):
            if plan.level == plan.top:
                raise TooComplex("an `in` filter on year numbers is not periodic")
        elif isinstance(item, CycleFilter):
            cycles.add(item.cycle)
        elif isinstance(item, AllFilter | AnyFilter):
            for child in item.all if isinstance(item, AllFilter) else item.any:
                self._filter_needs(child, needs, cycles, units, size)
        else:
            assert isinstance(item, NotFilter)
            self._filter_needs(item.not_, needs, cycles, units, size)

    # segments

    def _segments(self) -> list[_Segment]:
        """Exception-affected period ranges and the clean stretches between them, in order."""
        plan, regime = self.plan, self.plan.regime
        dirty: list[tuple[int, int]] = []
        for year in regime.exception_years:
            low, high = regime.year_start(year), regime.year_start(year + 1) - 1
            k_lo, k_hi = plan.k_range(low, high)
            k_lo, k_hi = max(k_lo - 1, 0), k_hi + 1  # a period straddling the year boundary
            if k_hi < 0:
                continue
            if dirty and k_lo <= dirty[-1][1] + 1:
                dirty[-1] = (dirty[-1][0], max(dirty[-1][1], k_hi))
            else:
                dirty.append((k_lo, k_hi))
        segments: list[_Segment] = []
        position = 0
        for k_lo, k_hi in dirty:
            if k_lo > position:
                segments.append(_Segment(position, k_lo))
            segments.append(_Segment(k_lo, k_hi + 1, dirty=True))
            position = k_hi + 1
        segments.append(_Segment(position, None))
        return segments

    def _counts(self, start: int, length: int) -> list[int]:
        self.enumerated += length
        if self.enumerated > ENUM_LIMIT:
            raise TooComplex("too many periods to enumerate")
        counts = (
            sum(p is not None for p in self.plan.positions(k)) for k in range(start, start + length)
        )
        return list(accumulate(counts, initial=0))

    def _fill(self, segment: _Segment) -> None:
        if segment.prefix:
            return
        length = None if segment.end is None else segment.end - segment.start
        if length is not None and (segment.dirty or length <= 2 * self.q):
            segment.prefix = self._counts(segment.start, length)
        else:
            segment.prefix = self._counts(segment.start, self.q)
            segment.periodic = True

    # queries

    def _segment_starts(self, index: int) -> int:
        """``S`` at the start of segment ``index`` (summing earlier segments as needed)."""
        while len(self.before) <= index:
            segment = self.segments[len(self.before) - 1]
            self._fill(segment)
            self.before.append(self.before[-1] + segment.total(self.q))
        return self.before[index]

    def _segment_of(self, k: int) -> int:
        starts = [segment.start for segment in self.segments]
        return bisect_left(starts, k + 1) - 1

    def count(self, k: int) -> int:
        """``S(k)``: positions in periods ``0 … k-1``."""
        index = self._segment_of(k)
        segment = self.segments[index]
        self._fill(segment)
        return self._segment_starts(index) + segment._upto(k - segment.start, self.q)

    def period_of(self, i: int) -> int | None:
        """The period holding the ``i``-th position (1-based), ``None`` if there is none."""
        for index, segment in enumerate(self.segments):
            self._fill(segment)
            base = self._segment_starts(index)
            if segment.end is not None:
                if base + segment.total(self.q) >= i:
                    return segment.start + self._within(segment, i - base)
                continue
            per = segment.prefix[-1]
            if segment.periodic:
                if per == 0:
                    return None
                full, rest = divmod(i - base - 1, per)
                return segment.start + full * self.q + bisect_left(segment.prefix, rest + 1) - 1
            return None  # pragma: no cover (an unbounded segment is always periodic)
        return None  # pragma: no cover

    def _within(self, segment: _Segment, r: int) -> int:
        """Offset of the period holding the ``r``-th position of a bounded segment."""
        if not segment.periodic:
            return bisect_left(segment.prefix, r) - 1
        per = segment.prefix[-1]
        full, rest = divmod(r - 1, per)
        return full * self.q + bisect_left(segment.prefix, rest + 1) - 1


def counter_for(plan: CalendarPlan) -> Counter | None:
    """The plan's counter, or ``None`` when its rule can't be counted by super-periods."""
    try:
        return Counter(plan)
    except TooComplex:
        return None
