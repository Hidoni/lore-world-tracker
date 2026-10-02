"""Expansion, single occurrences and series bounds (``recurrence.md`` §2-§5, §9).

A rule becomes a plan (:mod:`.plan`): candidate period ``k = 0, 1, …`` holds time-ordered
positions. Interval rules have one position, ``series_start + k·every``. Calendar rules
(:mod:`.calendar_rules`) use the period ``p0 + k·interval`` of the frequency level or cycle
(``p0`` = the period of the series start). Windows map to a ``k`` range by ordinal arithmetic, so
the cost doesn't depend on how far the window is from the series start.

Count limits, exclusions, occurrence numbers and window counts use the counting primitives of
:class:`.plan.Plan` (``recurrence.md`` §5.4).
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
    NeverLimit,
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
    for i, _ in enumerate(rule.exclusions):
        begin = ctx.resolved.get(f"/exclusions/{i}/from")
        to = ctx.resolved.get(f"/exclusions/{i}/to")
        for member, value in (("from", begin), ("to", to)):
            if value is None:
                errors.append(
                    _error("anchor.unresolved", f"/exclusions/{i}/{member}", "unresolved")
                )
        if begin is not None and to is not None and to < begin:
            errors.append(_error("rule.bad_exclusion", f"/exclusions/{i}", "to is before from"))
    if isinstance(rule, CalendarRule):
        if ctx.calendar is None:
            errors.append(_error("rule.unknown_calendar", "/calendar_id", "no calendar given"))
        else:
            errors += calendar_rule_errors(rule, ctx.calendar, ctx.series_start)
    return errors


def validate_rule(rule: Rule, ctx: RecurrenceContext) -> list[ValidationError]:
    """§9: errors, plus the warning ``rule.series_start_not_occurrence`` (path ``""``) when the
    first occurrence isn't at the series start. Paths point into the rule, except ``/end…``,
    which points into the series' end spec.
    """
    errors = _structural_errors(rule, ctx)
    if errors:
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

    def count_before(self, t: int) -> int:
        return max(0, -floor_div(self.ctx.series_start - t, self.every))

    def position(self, i: int) -> tuple[int, int, int] | None:
        return i - 1, 0, self.ctx.series_start + (i - 1) * self.every


def _plan(rule: Rule, ctx: RecurrenceContext) -> Plan:
    errors = [e for e in _structural_errors(rule, ctx) if e.severity == "error"]
    if errors:
        raise RecurrenceError("rule.invalid", errors[0].message, tuple(errors))
    last = ctx.dimension_duration
    if isinstance(rule.limit, UntilLimit):
        last = min(last, ctx.resolved["/limit/until"])
    plan: Plan
    if isinstance(rule, IntervalRule):
        plan = _IntervalPlan(rule, ctx, last)
    else:
        assert ctx.calendar is not None
        plan = CalendarPlan(rule, ctx, ctx.calendar, last)
    ranges = sorted(
        (ctx.resolved[f"/exclusions/{i}/from"], ctx.resolved[f"/exclusions/{i}/to"])
        for i in range(len(rule.exclusions))
    )
    for begin, to in ranges:
        if begin >= to:
            continue
        if plan.exclusions and begin <= plan.exclusions[-1][1]:
            plan.exclusions[-1] = (plan.exclusions[-1][0], max(plan.exclusions[-1][1], to))
        else:
            plan.exclusions.append((begin, to))
    plan.exclusion_starts = [begin for begin, _ in plan.exclusions]
    if isinstance(rule.limit, CountLimit):
        # §5.4: the count-th generated occurrence (exclusions still use up the count) ends it.
        index = plan.count_before(ctx.series_start) + int(rule.limit.count)
        found = plan.position(index)
        if found is not None and found[2] <= plan.last:
            plan.last = found[2]
    return plan


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
    low, high = _starts_range(plan, w0, w1)
    k_lo, k_hi = plan.k_range(low, high) if w0 <= w1 and low <= high else (0, -1)
    periods = k_hi - k_lo + 1
    if periods <= 0:
        return Expansion([], False, None)
    if periods > max(ITERATE_LIMIT, TRUNCATE_FACTOR * max_items) or (
        isinstance(plan, _IntervalPlan) and periods > TRUNCATE_FACTOR * max_items
    ):
        return Expansion([], True, _count(plan, w0, w1, k_lo, k_hi)[0])
    items: list[Occurrence] = []
    for k in range(k_lo, k_hi + 1):
        items += [o for o in plan.occurrences(k) if _overlaps(o.start, o.end, w0, w1)]
        if len(items) > TRUNCATE_FACTOR * max_items:
            return Expansion([], True, _count(plan, w0, w1, k_lo, k_hi)[0])
    if len(items) > max_items:
        return Expansion([], True, len(items))
    return Expansion(items, False, None)


def _starts_range(plan: Plan, w0: int, w1: int) -> tuple[int, int]:
    """Starts that may overlap ``[w0, w1)`` (§5.1), within the series bounds."""
    exact = plan.exact_length()
    length = plan.upper_length() if exact is None else exact
    low = max(plan.ctx.series_start, w0 - length + 1 if length > 0 else w0)
    return low, min(w1 - 1 if w1 > w0 else w0, plan.last)


def _count(plan: Plan, w0: int, w1: int, k_lo: int, k_hi: int) -> tuple[int, bool]:
    """(occurrences overlapping the window, exact): by counting, else sampled periods."""
    try:
        return _count_exactly(plan, w0, w1)
    except RecurrenceError as error:
        if error.code != "rule.too_complex_to_count":
            raise
    return plan.estimate(k_lo, k_hi), False


def _count_exactly(plan: Plan, w0: int, w1: int) -> tuple[int, bool]:
    low, high = _starts_range(plan, w0, w1)
    if low > high:
        return 0, True
    if plan.exact_length() is not None:
        return plan.actual_before(high + 1) - plan.actual_before(low), True
    # Calendar durations: starts in the window overlap it; earlier ones are checked one by one.
    inside = plan.actual_before(high + 1) - plan.actual_before(max(low, w0))
    earlier = plan.actual_before(w0) - plan.actual_before(low)
    if earlier > ITERATE_LIMIT:
        return inside + earlier, False
    found = 0
    t = low
    for _ in range(earlier):
        item = plan.next_occurrence(t)
        assert item is not None
        found += _overlaps(item.start, item.end, w0, w1)
        t = item.start + 1
    return inside + found, True


def _valid(plan: Plan, key: str) -> Occurrence:
    match = (_SUB_KEY if plan.multi else _KEY).fullmatch(key)
    found = None
    if match is not None:
        k = int(key.split(".", maxsplit=1)[0])
        found = next((o for o in plan.occurrences(k) if o.key == key), None)
    if found is None:
        raise RecurrenceError("not_found", f"no occurrence has key {key!r}")
    return found


def occurrence(rule: Rule, ctx: RecurrenceContext, key: str) -> Occurrence:
    """The occurrence with ``key`` (``k``, or ``k.j`` for multi-position rules, §3);
    ``not_found`` if the key has none (or it is excluded or beyond the limit)."""
    return _valid(_plan(rule, ctx), key)


def occurrence_number(rule: Rule, ctx: RecurrenceContext, key: str) -> int:
    """§3: the 1-based number of the occurrence among the series' actual occurrences."""
    plan = _plan(rule, ctx)
    return plan.actual_before(_valid(plan, key).start + 1)


def count_in_window(
    rule: Rule, ctx: RecurrenceContext, window: tuple[int, int]
) -> tuple[int, bool]:
    """§4: (occurrences overlapping ``[w0, w1)``, exact). Exact for interval rules and for
    calendar rules that super-periods can count; otherwise sampled (``exact`` false)."""
    plan = _plan(rule, ctx)
    w0, w1 = window
    low, high = _starts_range(plan, w0, w1)
    if w1 < w0 or low > high:
        return 0, True
    k_lo, k_hi = plan.k_range(low, high)
    if k_hi < k_lo:
        return 0, True
    return _count(plan, w0, w1, k_lo, k_hi)


def occurrence_at(rule: Rule, ctx: RecurrenceContext, t: int) -> str | None:
    """§4: the key of the occurrence starting at ``t``, else of the latest-starting occurrence
    whose span contains ``t`` (product decision, 2026-10-02); ``None`` if none does."""
    plan = _plan(rule, ctx)
    found = plan.previous_occurrence(t)
    if found is None or found.start == t:
        return None if found is None else found.key
    if plan.exact_length() is not None:  # earlier occurrences end earlier
        return found.key if found.end > t else None
    earliest = t - plan.upper_length() + 1
    for _ in range(SCAN_LIMIT):
        if found is None or found.start < earliest:
            return None
        if found.end > t:
            return found.key
        found = plan.previous_occurrence(found.start - 1)
    return None


def next_occurrences(rule: Rule, ctx: RecurrenceContext, after: int, n: int) -> list[Occurrence]:
    """The first ``n`` occurrences starting at or after ``after`` (editor previews)."""
    plan = _plan(rule, ctx)
    found: list[Occurrence] = []
    t = after
    while len(found) < n:
        item = plan.next_occurrence(t)
        if item is None:
            break
        found.append(item)
        t = item.start + 1
    return found


def series_bounds(rule: Rule, ctx: RecurrenceContext) -> SeriesBounds:
    """§4 ``series_bounds``: the first and last occurrences and their number.

    ``never``: only ``first_start`` (the rest is unbounded). ``until`` and ``count``: the last
    occurrence and the exact count of actual occurrences (exclusions applied); a ``count`` limit
    counts generated occurrences, so excluded ones use it up (product decision, 2026-10-02).
    """
    plan = _plan(rule, ctx)
    first = plan.next_occurrence(ctx.series_start)
    bounded = not isinstance(rule.limit, NeverLimit)
    if first is None:
        return SeriesBounds(None, None, None, 0 if bounded else None)
    if not bounded:
        return SeriesBounds(first.start, None, None, None)
    last = plan.previous_occurrence(plan.last)
    assert last is not None  # the first occurrence qualifies
    return SeriesBounds(first.start, last.start, last.end, plan.actual_before(plan.last + 1))
