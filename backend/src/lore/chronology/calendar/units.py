"""Unit navigation: bounds, ordinals and from_ordinal (``chronology-engine.md`` §5.8, §7).

Ordinals count units of a level from the start of year 0 (the first counted unit of year 0 is 0;
units before year 0 are negative). Which units count is a :class:`UnitFilter`: :data:`REGULAR`
(intercalary units don't count) for ordinals, a cycle's exclusions for counted ordinals (#13).
Counts come from prefix sums (per template over its segments, per period over its years, plus
exception deltas), computed on first use per (level, filter) and cached on the regime. Queries
cost ``O(log P + depth · log width)``; nothing iterates over units or years.
"""

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import accumulate

from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledRegime,
    CompiledTemplate,
    DateError,
    Segment,
    active_regime,
)


@dataclass(frozen=True, slots=True)
class UnitFilter:
    """Which units of a level count.

    A unit counts if ``counts(segment)`` holds for its own segment and no segment on its path
    (itself or an ancestor) ``excludes`` its subtree. ``key`` identifies the filter in caches.
    """

    key: str
    counts: Callable[[Segment], bool]
    excludes: Callable[[Segment], bool]


REGULAR = UnitFilter("regular", lambda segment: not segment.intercalary, lambda segment: False)
"""Regular units: everything except intercalary units themselves (§3.4)."""


def cycle_filter(cycle_id: str) -> UnitFilter:
    """The units a cycle counts: all units except those excluded from it with their subtrees
    (``cycle_excluded``, §3.4, §3.7). Intercalary units count unless excluded (R-CAL-4).
    """
    return UnitFilter(
        f"cycle:{cycle_id}",
        counts=lambda segment: True,
        excludes=lambda segment: cycle_id in segment.cycle_excluded,
    )


def counted_position(
    top: int, regime: CompiledRegime, t: int, level: int, unit_filter: UnitFilter
) -> tuple[int, bool, int]:
    """(counted units of ``level`` before the unit containing ``t``, whether that unit counts,
    the unit's start) in ``regime``. ``level`` is a level index, ``top`` the top level's index.
    """
    located = _locate(top, regime, t, level, unit_filter)
    return located.before, located.counted, located.start


@dataclass(frozen=True, slots=True)
class Bounds:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Ordinal:
    value: int
    """Ordinal of the unit, or of the preceding counted unit when ``counted`` is false."""
    counted: bool
    """False for a unit the filter skips (for :data:`REGULAR`: an intercalary unit)."""


# --- counts (cached per regime) ------------------------------------------------------------------


def _per_child(
    regime: CompiledRegime, segment: Segment, level: int, child_level: int, unit_filter: UnitFilter
) -> int:
    """Counted units of ``level`` inside one child of ``segment`` (a unit of ``child_level``)."""
    if unit_filter.excludes(segment):
        return 0
    if child_level == level:
        return 1 if unit_filter.counts(segment) else 0
    assert segment.child is not None
    return _template_count(regime, regime.templates[segment.child], level, unit_filter)


def _template_prefix(
    regime: CompiledRegime, template: CompiledTemplate, level: int, unit_filter: UnitFilter
) -> tuple[int, ...]:
    """Counted ``level`` units before each segment of ``template`` (length = segments + 1)."""
    key = ("prefix", template.id, level, unit_filter.key)
    cached = regime.cache.get(key)
    if cached is None:
        child_level = template.level - 1
        counts = (
            segment.count * _per_child(regime, segment, level, child_level, unit_filter)
            for segment in template.segments
        )
        cached = tuple(accumulate(counts, initial=0))
        regime.cache[key] = cached
    assert isinstance(cached, tuple)
    return cached


def _template_count(
    regime: CompiledRegime, template: CompiledTemplate, level: int, unit_filter: UnitFilter
) -> int:
    count: int = _template_prefix(regime, template, level, unit_filter)[-1]
    return count


@dataclass(frozen=True, slots=True)
class _YearCounts:
    """Counted units before each year: ``base(Y) = k·total + prefix[i] + cum(Y)`` (like §5.2)."""

    prefix: Sequence[int]
    total: int
    exception_years: tuple[int, ...]
    exception_counts: tuple[int, ...]
    deltas: tuple[int, ...]
    starts: tuple[int, ...]

    def cumulative(self, year: int) -> int:
        years = self.exception_years
        return self.deltas[bisect_right(years, year - 1)] - self.deltas[bisect_right(years, -1)]

    def before(self, year: int, period: int) -> int:
        k, i = divmod(year, period)
        return k * self.total + self.prefix[i] + self.cumulative(year)


def _year_counts(regime: CompiledRegime, level: int, unit_filter: UnitFilter) -> _YearCounts:
    key = ("years", level, unit_filter.key)
    cached = regime.cache.get(key)
    if isinstance(cached, _YearCounts):
        return cached
    per_template = [
        _template_count(regime, regime.templates[t], level, unit_filter)
        for t in regime.top_templates
    ]
    prefix = list(accumulate((per_template[i] for i in regime.top_sequence), initial=0))
    total = prefix[-1]
    years = regime.exception_years
    counts = tuple(
        _template_count(regime, regime.templates[t], level, unit_filter)
        for t in regime.exception_templates
    )
    deltas = tuple(
        accumulate(
            (count - per_template[regime.top_sequence[year % regime.period]]
             for year, count in zip(years, counts, strict=True)),
            initial=0,
        )
    )  # fmt: skip
    partial = _YearCounts(prefix, total, years, counts, deltas, ())
    starts = tuple(partial.before(year, regime.period) for year in years)
    result = _YearCounts(prefix, total, years, counts, deltas, starts)
    regime.cache[key] = result
    return result


def _year_of_count(regime: CompiledRegime, counts: _YearCounts, m: int) -> int | None:
    """The year containing counted unit ``m`` (inverse of ``before``), or None if none does."""
    position = bisect_right(counts.starts, m) - 1
    if position >= 0 and m < counts.starts[position] + counts.exception_counts[position]:
        return counts.exception_years[position]
    if counts.total == 0:
        return None
    if position >= 0:
        offset = counts.cumulative(counts.exception_years[position] + 1)
    else:
        offset = counts.cumulative(min(counts.exception_years, default=0))
    k, s = divmod(m - offset, counts.total)
    return k * regime.period + bisect_right(counts.prefix, s, hi=regime.period) - 1


# --- levels and regimes --------------------------------------------------------------------------


def _level(calendar: CompiledCalendar, level: str) -> int:
    if level not in calendar.levels:
        raise DateError("invalid_date", f"unknown level {level!r}", level)
    return calendar.levels.index(level)


def _regime(calendar: CompiledCalendar, regime: str | None) -> CompiledRegime:
    if regime is None:
        return calendar.regimes[0]
    found = next((r for r in calendar.regimes if r.id == regime), None)
    if found is None:
        raise DateError("invalid_date", f"unknown regime {regime!r}")
    return found


def _clip(calendar: CompiledCalendar, regime: CompiledRegime, start: int, end: int) -> Bounds:
    """Clip a unit to its regime's validity interval (§7)."""
    if regime.index > 0 and regime.starts_at is not None:
        start = max(start, regime.starts_at)
    later = [r.starts_at for r in calendar.regimes[regime.index + 1 :] if r.starts_at is not None]
    if later:
        end = min(end, *later)
    return Bounds(start, end)


@dataclass(frozen=True, slots=True)
class _Located:
    start: int
    length: int
    before: int
    """Counted units of the level before this unit."""
    counted: bool


def _locate(
    top: int, regime: CompiledRegime, t: int, level: int, unit_filter: UnitFilter
) -> _Located:
    """Descend from the year containing ``t`` to the unit of ``level`` containing it.

    ``top`` is the index of the top level (the number of levels minus one).
    """
    rel = t - regime.epoch
    year = regime.year_of_rel(rel)
    start = regime.rel_start(year)
    template = regime.year_template(year)
    if level == top:
        return _Located(regime.epoch + start, template.length, year, True)
    before = _year_counts(regime, level, unit_filter).before(year, regime.period)
    offset = rel - start
    excluded = False
    for child_level in range(top - 1, level - 1, -1):
        child = template.child_at(offset)
        segment = child.segment
        if not excluded:  # nothing inside an excluded subtree counts
            per_child = _per_child(regime, segment, level, child_level, unit_filter)
            before += _template_prefix(regime, template, level, unit_filter)[child.position]
            before += child.index * per_child
        excluded = excluded or unit_filter.excludes(segment)
        start += child.offset
        offset -= child.offset
        if child_level == level:
            counted = not excluded and unit_filter.counts(segment)
            return _Located(regime.epoch + start, child.length, before, counted)
        assert segment.child is not None
        template = regime.templates[segment.child]
    raise AssertionError("unreachable")  # pragma: no cover


# --- public API ----------------------------------------------------------------------------------


def unit_bounds(calendar: CompiledCalendar, t: int, level: str) -> Bounds:
    """``[start, end)`` of the ``level`` unit containing ``t``, clipped at regime boundaries."""
    regime = active_regime(calendar, t)
    located = _locate(len(calendar.levels) - 1, regime, t, _level(calendar, level), REGULAR)
    return _clip(calendar, regime, located.start, located.start + located.length)


def counted_ordinal(
    calendar: CompiledCalendar, t: int, level: str, unit_filter: UnitFilter = REGULAR
) -> Ordinal:
    """Ordinal of the ``level`` unit containing ``t`` among the units ``unit_filter`` counts.

    For a unit the filter skips, the ordinal of the preceding counted unit, with
    ``counted=False``. Computed in the regime active at ``t`` (§7).
    """
    regime = active_regime(calendar, t)
    located = _locate(len(calendar.levels) - 1, regime, t, _level(calendar, level), unit_filter)
    if located.counted:
        return Ordinal(located.before, True)
    return Ordinal(located.before - 1, False)


def ordinal(calendar: CompiledCalendar, t: int, level: str) -> Ordinal:
    """§5.8 ``ordinal``: regular units; ``counted=False`` means ``t`` is in an intercalary unit."""
    return counted_ordinal(calendar, t, level, REGULAR)


def from_counted_ordinal(
    calendar: CompiledCalendar,
    level: str,
    m: int,
    unit_filter: UnitFilter = REGULAR,
    *,
    regime: str | None = None,
) -> Bounds:
    """Bounds of the counted ``level`` unit with ordinal ``m`` (default: regime 0)."""
    chosen = _regime(calendar, regime)
    index = _level(calendar, level)
    top = len(calendar.levels) - 1
    if index == top:
        return Bounds(chosen.year_start(m), chosen.year_start(m + 1))
    counts = _year_counts(chosen, index, unit_filter)
    year = _year_of_count(chosen, counts, m)
    if year is None:
        raise DateError("invalid_date", f"no counted {level} has ordinal {m}", level)
    remaining = m - counts.before(year, chosen.period)
    start = chosen.year_start(year)
    template = chosen.year_template(year)
    for child_level in range(top - 1, index - 1, -1):
        prefix = _template_prefix(chosen, template, index, unit_filter)
        position = bisect_right(prefix, remaining) - 1
        segment = template.segments[position]
        per_child = _per_child(chosen, segment, index, child_level, unit_filter)
        within, remaining = divmod(remaining - prefix[position], per_child)
        start += segment.start + within * segment.child_length
        if child_level == index:
            return Bounds(start, start + segment.child_length)
        assert segment.child is not None
        template = chosen.templates[segment.child]
    raise AssertionError("unreachable")  # pragma: no cover


def from_ordinal(
    calendar: CompiledCalendar, level: str, m: int, *, regime: str | None = None
) -> Bounds:
    """§5.8 ``from_ordinal``: bounds of the regular ``level`` unit with ordinal ``m``."""
    return from_counted_ordinal(calendar, level, m, REGULAR, regime=regime)
