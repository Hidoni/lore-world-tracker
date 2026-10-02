"""Expansion, single occurrences and series bounds (``recurrence.md`` §2-§5, §9).

A rule is turned into a plan: candidate ``k`` (``k = 0, 1, …``) maps to at most one occurrence
start. Interval rules start at ``series_start + k·every``. Calendar rules use the period with
ordinal ``p0 + k·interval`` of the frequency level (``p0`` = the period containing the series
start), counted in the regime in force at the series start and extended proleptically past its
end, like calendar arithmetic (product decision, 2026-10-02). Windows map to a ``k`` range by
ordinal arithmetic, so the cost doesn't depend on how far the window is from the series start.

Filters, selectors and cycle frequencies arrive with #20; count limits and exclusions with #21.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from lore.chronology.calendar.arithmetic import (
    add,
    descend,
    duration_upper_bound,
    reapply,
)
from lore.chronology.calendar.compile import ValidationError, pointer
from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledRegime,
    DateError,
    active_regime,
)
from lore.chronology.calendar.convert import Overflow, resolve_child
from lore.chronology.calendar.units import REGULAR, counted_position, from_counted_ordinal
from lore.chronology.numbers import floor_div
from lore.chronology.schema import (
    CalendarDuration,
    CalendarRule,
    CountLimit,
    CycleFreq,
    DurationEnd,
    EndSpec,
    InstantEnd,
    IntervalRule,
    LevelFreq,
    UnknownEnd,
    UntilLimit,
)

type Rule = CalendarRule | IntervalRule
type RecurrenceErrorCode = Literal["not_found", "rule.invalid", "rule.too_complex_to_count"]

SCAN_LIMIT = 100_000
"""Most candidate periods searched for one occurrence (first, last, next) or counted one by one."""
TRUNCATE_FACTOR = 4
"""``expand`` gives up on items when the window has more than ``max_items * 4`` candidates."""
SAMPLES = 64
"""Candidates sampled to estimate the share that has an occurrence (until #21's averages)."""

_KEY = re.compile(r"0|[1-9][0-9]*")


class RecurrenceError(ValueError):
    """``not_found``, an invalid rule (``errors`` lists why) or ``rule.too_complex_to_count``."""

    def __init__(
        self, code: RecurrenceErrorCode, message: str, errors: tuple[ValidationError, ...] = ()
    ) -> None:
        super().__init__(message)
        self.code: RecurrenceErrorCode = code
        self.errors = errors


@dataclass(frozen=True, slots=True)
class RecurrenceContext:
    """What a rule needs besides itself (``recurrence.md`` §4 ``ctx``)."""

    series_start: int
    """The resolved series start."""
    end: EndSpec
    """The series' end spec: the occurrence duration (``duration``, ``instant`` or ``unknown``)."""
    dimension_duration: int
    """``D``: no occurrence starts after it."""
    calendar: CompiledCalendar | None = None
    """The rule's calendar (and the calendar of a calendar duration)."""
    resolved: Mapping[str, int] = field(default_factory=dict)
    """Resolved moments of the rule's time points, by JSON pointer (``/limit/until``)."""


@dataclass(frozen=True, slots=True)
class Occurrence:
    key: str
    start: int
    end: int

    def as_json(self) -> dict[str, str]:
        return {"key": self.key, "start": str(self.start), "end": str(self.end)}


@dataclass(frozen=True, slots=True)
class Expansion:
    """The occurrences overlapping a window, or ``truncated`` with a count and no items."""

    items: list[Occurrence]
    truncated: bool
    estimated_count: int | None
    """Set when ``truncated``: the number of occurrences (an estimate when it can't be exact)."""

    def as_json(self) -> dict[str, object]:
        count = None if self.estimated_count is None else str(self.estimated_count)
        return {
            "items": [item.as_json() for item in self.items],
            "truncated": self.truncated,
            "estimated_count": count,
        }


@dataclass(frozen=True, slots=True)
class SeriesBounds:
    """``None`` members are unbounded (``never``), or absent when the series has no occurrence."""

    first_start: int | None
    last_start: int | None
    last_end: int | None
    count: int | None

    def as_json(self) -> dict[str, str | None]:
        def text(value: int | None) -> str | None:
            return None if value is None else str(value)

        return {
            "first_start": text(self.first_start),
            "last_start": text(self.last_start),
            "last_end": text(self.last_end),
            "count": text(self.count),
        }


# --- validation (§9) -----------------------------------------------------------------------------


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code, path, message)


def _structural_errors(rule: Rule, ctx: RecurrenceContext) -> list[ValidationError]:
    errors: list[ValidationError] = []
    end = ctx.end
    if not isinstance(end, DurationEnd | InstantEnd | UnknownEnd):
        errors.append(
            _error("rule.series_end_not_duration", "/end", "a series end must be a duration")
        )
    elif (
        isinstance(end, DurationEnd)
        and isinstance(end.duration, CalendarDuration)
        and ctx.calendar is None
    ):
        errors.append(
            _error("rule.unknown_calendar", "/end/duration/calendar_id", "no calendar given")
        )
    if isinstance(rule.limit, UntilLimit):
        until = ctx.resolved.get("/limit/until")
        if until is None:
            errors.append(_error("anchor.unresolved", "/limit/until", "until is not resolved"))
        elif until < ctx.series_start:
            errors.append(
                _error("rule.until_before_start", "/limit/until", "until is before the start")
            )
    if isinstance(rule, CalendarRule):
        errors += _calendar_errors(rule, ctx.calendar)
    return errors


def _calendar_errors(
    rule: CalendarRule, calendar: CompiledCalendar | None
) -> list[ValidationError]:
    if calendar is None:
        return [_error("rule.unknown_calendar", "/calendar_id", "the calendar is not given")]
    if isinstance(rule.freq, LevelFreq) and rule.freq.level not in calendar.levels:
        return [_error("rule.bad_freq_level", "/freq/level", "unknown level")]
    if rule.time is None or not isinstance(rule.freq, LevelFreq):
        return []
    period = calendar.levels.index(rule.freq.level)
    errors = [
        _error(
            "rule.bad_time_fields", pointer("time", "fields", key), "not a level below the period"
        )
        for key in rule.time.fields
        if key not in calendar.levels or calendar.levels.index(key) >= period
    ]
    if errors:
        return errors
    indexes = sorted(calendar.levels.index(key) for key in rule.time.fields)
    if not indexes or indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        return [_error("rule.bad_time_fields", "/time/fields", "time fields must be contiguous")]
    return []


def _pending(rule: Rule) -> str | None:
    """Why the engine can't evaluate ``rule`` yet (features of later issues), if it can't."""
    if isinstance(rule, CalendarRule) and (
        isinstance(rule.freq, CycleFreq) or rule.filters or rule.select is not None
    ):
        return "filters, selectors and cycle frequencies are implemented by #20"
    if isinstance(rule.limit, CountLimit) or rule.exclusions:
        return "count limits and exclusions are implemented by #21"
    return None


def validate_rule(rule: Rule, ctx: RecurrenceContext) -> list[ValidationError]:
    """§9: errors, plus the warning ``rule.series_start_not_occurrence`` (path ``""``) when the
    first occurrence isn't at the series start. Paths point into the rule, except ``/end…``,
    which points into the series' end spec.
    """
    errors = _structural_errors(rule, ctx)
    if errors or _pending(rule) is not None:
        return errors
    first = series_bounds(rule, ctx).first_start
    if first != ctx.series_start:
        return [
            ValidationError(
                "rule.series_start_not_occurrence",
                "",
                "the series start is not an occurrence; the first occurrence is later",
                "warning",
            )
        ]
    return []


# --- plans ---------------------------------------------------------------------------------------


class _Plan(ABC):
    """Candidates ``k ≥ 0`` with at most one occurrence each, starts increasing with ``k``."""

    def __init__(self, ctx: RecurrenceContext, last: int) -> None:
        self.ctx = ctx
        self.last = last
        """The latest allowed start: ``min(until, D)``."""
        end = ctx.end
        self.duration = end.duration if isinstance(end, DurationEnd) else None

    @abstractmethod
    def start_of(self, k: int) -> int | None:
        """The start of candidate ``k`` (ignoring the series bounds), ``None`` if it has none."""

    @abstractmethod
    def k_range(self, low: int, high: int) -> tuple[int, int]:
        """Candidates (``k ≥ 0``) whose start may lie in ``[low, high]``; empty if ``lo > hi``."""

    @property
    @abstractmethod
    def dense(self) -> bool:
        """Every candidate has an occurrence (no period is skipped)."""

    def end_of(self, start: int) -> int:
        duration = self.duration
        if duration is None:
            return start
        if isinstance(duration, CalendarDuration):
            assert self.ctx.calendar is not None
            return add(self.ctx.calendar, start, duration)
        return start + int(duration.units)

    def exact_length(self) -> int | None:
        """The occurrence length when it is the same for every occurrence."""
        duration = self.duration
        if duration is None:
            return 0
        return None if isinstance(duration, CalendarDuration) else int(duration.units)

    def upper_length(self) -> int:
        duration = self.duration
        if duration is None:
            return 0
        if isinstance(duration, CalendarDuration):
            assert self.ctx.calendar is not None
            return duration_upper_bound(self.ctx.calendar, duration)
        return abs(int(duration.units))

    def occurrence(self, k: int) -> Occurrence | None:
        start = self.start_of(k)
        if start is None or not self.ctx.series_start <= start <= self.last:
            return None
        return Occurrence(str(k), start, self.end_of(start))

    def scan(self, k: int, step: Literal[1, -1]) -> Occurrence | None:
        """The first occurrence from candidate ``k`` on (in direction ``step``), within
        :data:`SCAN_LIMIT` candidates."""
        for candidate in range(k, k + step * SCAN_LIMIT, step):
            if candidate < 0:
                return None
            found = self.occurrence(candidate)
            if found is not None:
                return found
        return None

    def estimate(self, k_lo: int, k_hi: int) -> int:
        count = k_hi - k_lo + 1
        if self.dense:
            return count
        samples = min(count, SAMPLES)
        ks = {k_lo + i * (count - 1) // max(samples - 1, 1) for i in range(samples)}
        hits = sum(self.start_of(k) is not None for k in ks)
        return count * hits // len(ks)


class _IntervalPlan(_Plan):
    def __init__(self, rule: IntervalRule, ctx: RecurrenceContext, last: int) -> None:
        super().__init__(ctx, last)
        self.every = int(rule.every)

    def start_of(self, k: int) -> int | None:
        return self.ctx.series_start + k * self.every

    def k_range(self, low: int, high: int) -> tuple[int, int]:
        start = self.ctx.series_start
        return max(0, -floor_div(start - low, self.every)), floor_div(high - start, self.every)

    @property
    def dense(self) -> bool:
        return True


class _CalendarPlan(_Plan):
    def __init__(
        self, rule: CalendarRule, ctx: RecurrenceContext, calendar: CompiledCalendar, last: int
    ) -> None:
        super().__init__(ctx, last)
        assert isinstance(rule.freq, LevelFreq)
        self.calendar = calendar
        self.regime: CompiledRegime = active_regime(calendar, ctx.series_start)
        self.level = calendar.levels.index(rule.freq.level)
        self.interval = int(rule.interval)
        self.overflow: Overflow = "constrain" if rule.missing == "constrain" else "reject"
        self.time = (
            {calendar.levels.index(key): value for key, value in rule.time.fields.items()}
            if rule.time is not None
            else None
        )
        self.origin = descend(calendar, self.regime, ctx.series_start, 0)
        self.p0 = self._ordinal(ctx.series_start)

    def _ordinal(self, t: int) -> int:
        """Ordinal of the period containing ``t`` (or of the regular unit before it)."""
        top = len(self.calendar.levels) - 1
        before, counted, _ = counted_position(top, self.regime, t, self.level, REGULAR)
        return before if counted else before - 1

    @property
    def dense(self) -> bool:
        return self.overflow == "constrain" and self.time is None

    def k_range(self, low: int, high: int) -> tuple[int, int]:
        k_lo = -floor_div(self.p0 - self._ordinal(low), self.interval)
        return max(0, k_lo), floor_div(self._ordinal(high) - self.p0, self.interval)

    def start_of(self, k: int) -> int | None:
        try:
            return self._place(self.p0 + k * self.interval)
        except DateError:
            return None  # the position doesn't exist in this period (missing = skip)

    def _place(self, period: int) -> int:
        """§2.3-§2.4 with ``select = null``: the series start's position inside the period."""
        calendar, regime = self.calendar, self.regime
        level_id = calendar.levels[self.level]
        start = from_counted_ordinal(calendar, level_id, period, REGULAR, regime=regime.id).start
        template = descend(calendar, regime, start, self.level).template
        top = len(calendar.levels) - 1
        time = self.time
        for level in range(self.level - 1, -1, -1):
            if time is not None and level < min(time):
                return start  # below the time fields: the start of the deepest timed unit
            if time is not None and level in time:
                child = resolve_child(
                    calendar, regime, template, level, time[level], overflow=self.overflow
                )
            else:
                parent, original = self.origin.children[top - 1 - level]
                child = reapply(calendar, template, parent, original, self.overflow)
            start += child.offset
            assert child.template is not None
            template = regime.templates[child.template]
        if time is not None:
            return start
        base = self.origin.offset
        if base >= template.length:
            if self.overflow == "reject":
                raise DateError("invalid_date", "the base remainder doesn't fit")
            base = template.length - 1
        return start + base


def _plan(rule: Rule, ctx: RecurrenceContext) -> _Plan:
    errors = [e for e in _structural_errors(rule, ctx) if e.severity == "error"]
    if errors:
        raise RecurrenceError("rule.invalid", errors[0].message, tuple(errors))
    pending = _pending(rule)
    if pending is not None:
        raise NotImplementedError(pending)
    last = ctx.dimension_duration
    if isinstance(rule.limit, UntilLimit):
        last = min(last, ctx.resolved["/limit/until"])
    if isinstance(rule, IntervalRule):
        return _IntervalPlan(rule, ctx, last)
    assert ctx.calendar is not None
    return _CalendarPlan(rule, ctx, ctx.calendar, last)


# --- public API (§4) -----------------------------------------------------------------------------


def _overlaps(start: int, end: int, w0: int, w1: int) -> bool:
    """``time-model.md`` §2.1 overlap of an occurrence and a window (either may be an instant)."""
    if start == end and w0 == w1:
        return start == w0
    if start == end:
        return w0 <= start < w1
    if w0 == w1:
        return start <= w0 < end
    return start < w1 and w0 < end


def expand(
    rule: Rule, ctx: RecurrenceContext, window: tuple[int, int], max_items: int = 100
) -> Expansion:
    """§5.1-§5.3: the occurrences overlapping ``[w0, w1)``, in time order.

    When more than ``max_items`` occurrences overlap the window, the result is ``truncated`` with
    no items and their count in ``estimated_count``: exact when the window has at most
    ``4 * max_items`` candidates (they are all evaluated) or for interval rules with a fixed
    duration, otherwise candidates times the sampled share of candidates with an occurrence.
    """
    plan = _plan(rule, ctx)
    w0, w1 = window
    exact = plan.exact_length()
    length = plan.upper_length() if exact is None else exact
    low = max(ctx.series_start, w0 - length + 1 if length > 0 else w0)
    high = min(w1 - 1 if w1 > w0 else w0, plan.last)
    if w1 < w0 or low > high:
        return Expansion([], False, None)
    k_lo, k_hi = plan.k_range(low, high)
    candidates = k_hi - k_lo + 1
    if candidates <= 0:
        return Expansion([], False, None)
    if candidates > TRUNCATE_FACTOR * max_items:
        exact_count = isinstance(plan, _IntervalPlan) and exact is not None
        return Expansion([], True, candidates if exact_count else plan.estimate(k_lo, k_hi))
    items = [
        found
        for k in range(k_lo, k_hi + 1)
        if (found := plan.occurrence(k)) is not None and _overlaps(found.start, found.end, w0, w1)
    ]
    if len(items) > max_items:
        return Expansion([], True, len(items))
    return Expansion(items, False, None)


def occurrence(rule: Rule, ctx: RecurrenceContext, key: str) -> Occurrence:
    """The occurrence with ``key``; ``not_found`` if the key has none (§3)."""
    plan = _plan(rule, ctx)
    found = plan.occurrence(int(key)) if _KEY.fullmatch(key) else None
    if found is None:
        raise RecurrenceError("not_found", f"no occurrence has key {key!r}")
    return found


def next_occurrences(rule: Rule, ctx: RecurrenceContext, after: int, n: int) -> list[Occurrence]:
    """The first ``n`` occurrences starting at or after ``after`` (editor previews).

    Searches at most :data:`SCAN_LIMIT` candidates past the first one that could match.
    """
    plan = _plan(rule, ctx)
    low = max(after, ctx.series_start)
    if low > plan.last:
        return []
    k = plan.k_range(low, plan.last)[0]
    found: list[Occurrence] = []
    for candidate in range(k, k + SCAN_LIMIT):
        start = plan.start_of(candidate)
        if len(found) == n or (start is not None and start > plan.last):
            break
        item = plan.occurrence(candidate)
        if item is not None and item.start >= after:
            found.append(item)
    return found


def series_bounds(rule: Rule, ctx: RecurrenceContext) -> SeriesBounds:
    """§4 ``series_bounds`` for ``never`` and ``until`` limits.

    The first (and last) occurrence is searched within :data:`SCAN_LIMIT` candidates; a series
    whose start position never comes back within them is treated as having none. ``count`` is
    exact; for calendar rules that may skip periods it is counted one by one, which is limited
    to :data:`SCAN_LIMIT` candidates (``rule.too_complex_to_count`` beyond, until #21).
    """
    plan = _plan(rule, ctx)
    first = plan.scan(0, 1)
    bounded = isinstance(rule.limit, UntilLimit)
    if first is None:
        return SeriesBounds(None, None, None, 0 if bounded else None)
    if not bounded:
        return SeriesBounds(first.start, None, None, None)
    k_first = int(first.key)
    last = plan.scan(plan.k_range(first.start, plan.last)[1], -1)
    if last is not None and plan.dense:
        return SeriesBounds(first.start, last.start, last.end, int(last.key) - k_first + 1)
    if last is None or int(last.key) - k_first >= SCAN_LIMIT:
        raise RecurrenceError(
            "rule.too_complex_to_count", "counting this series needs super-periods (#21)"
        )
    count = sum(plan.occurrence(k) is not None for k in range(k_first, int(last.key) + 1))
    return SeriesBounds(first.start, last.start, last.end, count)
