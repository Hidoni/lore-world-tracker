"""Expansion, single occurrences and series bounds (``recurrence.md`` §2-§5, §9).

A rule becomes a plan (:mod:`.plan`): candidate period ``k = 0, 1, …`` holds time-ordered
positions. Interval rules have one position, ``series_start + k·every``. Calendar rules
(:mod:`.calendar_rules`) use the period ``p0 + k·interval`` of the frequency level or cycle
(``p0`` = the period of the series start). Windows map to a ``k`` range by ordinal arithmetic, so
the cost doesn't depend on how far the window is from the series start.

Count limits and exclusions arrive with #21.
"""

import re
from dataclasses import dataclass

from lore.chronology.calendar.compile import ValidationError
from lore.chronology.numbers import floor_div
from lore.chronology.recurrence.calendar_rules import CalendarPlan, calendar_rule_errors
from lore.chronology.recurrence.plan import (
    ITERATE_LIMIT,
    SCAN_LIMIT,
    TRUNCATE_FACTOR,
    Occurrence,
    Plan,
    RecurrenceContext,
    RecurrenceError,
)
from lore.chronology.schema import (
    CalendarDuration,
    CalendarRule,
    CountLimit,
    DurationEnd,
    InstantEnd,
    IntervalRule,
    UnknownEnd,
    UntilLimit,
)

type Rule = CalendarRule | IntervalRule

_KEY = re.compile(r"0|[1-9][0-9]*")
_SUB_KEY = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


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
        if ctx.calendar is None:
            errors.append(_error("rule.unknown_calendar", "/calendar_id", "no calendar given"))
        else:
            errors += calendar_rule_errors(rule, ctx.calendar, ctx.series_start)
    return errors


def _pending(rule: Rule) -> str | None:
    """Why the engine can't evaluate ``rule`` yet (features of a later issue), if it can't."""
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


class _IntervalPlan(Plan):
    def __init__(self, rule: IntervalRule, ctx: RecurrenceContext, last: int) -> None:
        super().__init__(ctx, last)
        self.every = int(rule.every)

    def positions(self, k: int) -> list[int | None]:
        return [self.ctx.series_start + k * self.every]

    def k_range(self, low: int, high: int) -> tuple[int, int]:
        start = self.ctx.series_start
        return max(0, -floor_div(start - low, self.every)), floor_div(high - start, self.every)

    @property
    def dense(self) -> bool:
        return True


def _plan(rule: Rule, ctx: RecurrenceContext) -> Plan:
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
    return CalendarPlan(rule, ctx, ctx.calendar, last)


def _period(found: Occurrence) -> int:
    return int(found.key.split(".", maxsplit=1)[0])


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
    no items and their count in ``estimated_count`` (recurrence.md §5.1 says when it is exact).
    """
    plan = _plan(rule, ctx)
    w0, w1 = window
    exact = plan.exact_length()
    length = plan.upper_length() if exact is None else exact
    low = max(ctx.series_start, w0 - length + 1 if length > 0 else w0)
    high = min(w1 - 1 if w1 > w0 else w0, plan.last)
    k_lo, k_hi = plan.k_range(low, high) if w0 <= w1 and low <= high else (0, -1)
    periods = k_hi - k_lo + 1
    if periods <= 0:
        return Expansion([], False, None)
    if isinstance(plan, _IntervalPlan) and periods > TRUNCATE_FACTOR * max_items:
        return Expansion([], True, periods if exact is not None else plan.estimate(k_lo, k_hi))
    if periods > max(ITERATE_LIMIT, TRUNCATE_FACTOR * max_items):
        return Expansion([], True, plan.estimate(k_lo, k_hi))
    items: list[Occurrence] = []
    for evaluated, k in enumerate(range(k_lo, k_hi + 1), start=1):
        items += [o for o in plan.occurrences(k) if _overlaps(o.start, o.end, w0, w1)]
        if len(items) > TRUNCATE_FACTOR * max_items:  # dense periods: extrapolate the rest
            remaining = periods - evaluated
            return Expansion([], True, len(items) + remaining * len(items) // evaluated)
    if len(items) > max_items:
        return Expansion([], True, len(items))
    return Expansion(items, False, None)


def occurrence(rule: Rule, ctx: RecurrenceContext, key: str) -> Occurrence:
    """The occurrence with ``key`` (``k``, or ``k.j`` for multi-position rules, §3);
    ``not_found`` if the key has none."""
    plan = _plan(rule, ctx)
    match = (_SUB_KEY if plan.multi else _KEY).fullmatch(key)
    found = None
    if match is not None:
        found = next(
            (o for o in plan.occurrences(int(key.split(".", maxsplit=1)[0])) if o.key == key), None
        )
    if found is None:
        raise RecurrenceError("not_found", f"no occurrence has key {key!r}")
    return found


def next_occurrences(rule: Rule, ctx: RecurrenceContext, after: int, n: int) -> list[Occurrence]:
    """The first ``n`` occurrences starting at or after ``after`` (editor previews).

    Searches at most :data:`SCAN_LIMIT` periods past the first one that could match.
    """
    plan = _plan(rule, ctx)
    low = max(after, ctx.series_start)
    if low > plan.last:
        return []
    k = plan.k_range(low, plan.last)[0]
    found: list[Occurrence] = []
    for candidate in range(k, k + SCAN_LIMIT):
        starts = [p for p in plan.positions(candidate) if p is not None]
        if starts and min(starts) > plan.last:
            break
        found += [o for o in plan.occurrences(candidate) if o.start >= after]
        if len(found) >= n:
            break
    return found[:n]


def series_bounds(rule: Rule, ctx: RecurrenceContext) -> SeriesBounds:
    """§4 ``series_bounds`` for ``never`` and ``until`` limits.

    The first (and last) occurrence is searched within :data:`SCAN_LIMIT` periods; a series
    whose positions never come back within them is treated as having none. ``count`` is exact;
    unless every period has exactly one occurrence it is counted period by period, which is
    limited to :data:`SCAN_LIMIT` periods (``rule.too_complex_to_count`` beyond, until #21).
    """
    plan = _plan(rule, ctx)
    first_period = plan.scan(0, 1)
    bounded = isinstance(rule.limit, UntilLimit)
    if first_period is None:
        return SeriesBounds(None, None, None, 0 if bounded else None)
    first = first_period[0]
    if not bounded:
        return SeriesBounds(first.start, None, None, None)
    k_first = _period(first)
    last_period = plan.scan(plan.k_range(first.start, plan.last)[1], -1)
    if last_period is None or _period(last_period[-1]) - k_first >= SCAN_LIMIT:
        raise RecurrenceError(
            "rule.too_complex_to_count", "counting this series needs super-periods (#21)"
        )
    last = last_period[-1]
    k_last = _period(last)
    if plan.dense:
        count = k_last - k_first + 1
    else:
        count = sum(len(plan.occurrences(k)) for k in range(k_first, k_last + 1))
    return SeriesBounds(first.start, last.start, last.end, count)
