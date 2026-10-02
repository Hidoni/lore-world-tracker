"""Calendar arithmetic: add, diff and duration bounds (``chronology-engine.md`` §9).

Durations are applied level by level from the coarsest to the finest. **Uniform** levels (every
template of the level, in every regime, has the same length) add exact base units, so the
intercalary units they contain are counted like any other. **Variable** levels use ordinal
arithmetic in the regime active at the current moment, extended proleptically past that regime's
end (§7): the target unit is ``n`` regular units away (intercalary units are skipped), and the
finer positions are re-applied inside it, constrained where they don't exist. Every step jumps
with ordinals and prefix sums; nothing iterates over units or years.
"""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from typing import Literal

from lore.chronology.calendar.compiled import (
    Child,
    CompiledCalendar,
    CompiledRegime,
    CompiledTemplate,
    DateError,
    active_regime,
)
from lore.chronology.calendar.convert import Overflow
from lore.chronology.calendar.units import REGULAR, counted_position, from_counted_ordinal
from lore.chronology.schema import BaseDuration, CalendarDuration

type Duration = BaseDuration | CalendarDuration


@dataclass(frozen=True, slots=True)
class Difference:
    """The result of :func:`diff`: ``t2 - t1`` in calendar units (chronology-engine §9.3)."""

    amounts: dict[str, int]
    """Every level from ``largest`` down to ``smallest`` (coarse to fine), each ``≥ 0``."""
    base: int
    """Base units left over below ``smallest`` (``≥ 0``)."""
    sign: Literal[1, -1]
    """``-1`` when ``t1 > t2`` (the amounts then measure ``t1 - t2``)."""

    def as_json(self) -> dict[str, object]:
        return {
            "amounts": {level: str(amount) for level, amount in self.amounts.items()},
            "base": str(self.base),
            "sign": self.sign,
        }

    def duration(self, calendar_id: str) -> CalendarDuration:
        """The amounts as a calendar duration (the base remainder is not included)."""
        amounts = {level: str(amount) for level, amount in self.amounts.items()}
        return CalendarDuration(
            kind="calendar", calendar_id=calendar_id, amounts=amounts, sign=self.sign
        )


# --- levels --------------------------------------------------------------------------------------


def _level(calendar: CompiledCalendar, level: str) -> int:
    if level not in calendar.levels:
        raise DateError("invalid_date", f"unknown level {level!r}", level)
    return calendar.levels.index(level)


def _templates(calendar: CompiledCalendar, level: int) -> list[CompiledTemplate]:
    return [
        template
        for regime in calendar.regimes
        for template in regime.templates.values()
        if template.level == level
    ]


def _uniform_length(calendar: CompiledCalendar, level: int) -> int | None:
    lengths = {template.length for template in _templates(calendar, level)}
    return lengths.pop() if len(lengths) == 1 else None


def is_uniform(calendar: CompiledCalendar, level: str) -> bool:
    """§9.1: every template of ``level``, in every regime, has the same length."""
    return _uniform_length(calendar, _level(calendar, level)) is not None


def _ordered(calendar: CompiledCalendar, duration: CalendarDuration) -> list[tuple[int, int]]:
    """(level index, amount) for the non-zero amounts, coarsest level first."""
    amounts = [(_level(calendar, level), int(amount)) for level, amount in duration.amounts.items()]
    return sorted(((level, n) for level, n in amounts if n != 0), reverse=True)


# --- add -----------------------------------------------------------------------------------------


def add(
    calendar: CompiledCalendar, t: int, duration: Duration, overflow: Overflow = "constrain"
) -> int:
    """§9.2: ``t`` moved by ``duration``. The result may lie outside ``[0, D]``.

    With ``overflow="reject"``, a step that has to constrain a position (31 January + 1 month, a
    slot missing from the target unit) raises ``invalid_date`` instead.
    """
    if isinstance(duration, BaseDuration):
        return t + int(duration.units)
    for level, amount in _ordered(calendar, duration):
        t = _step(calendar, t, level, duration.sign * amount, overflow)
    return t


def _step(calendar: CompiledCalendar, t: int, level: int, n: int, overflow: Overflow) -> int:
    """Move ``t`` by ``n`` (signed) units of one level."""
    if n == 0:
        return t
    length = _uniform_length(calendar, level)
    if length is not None:
        return t + n * length
    return _variable_step(calendar, active_regime(calendar, t), t, level, n, overflow=overflow)


@dataclass(frozen=True, slots=True)
class _Path:
    """The units containing a moment, from the top level down to some level."""

    year: int
    start: int
    """Start moment of the unit at the lowest level reached."""
    children: list[tuple[CompiledTemplate, Child]]
    """(parent template, child) per level below the top, coarse to fine."""
    template: CompiledTemplate
    """The template of the unit at the lowest level reached."""
    offset: int
    """``t`` minus ``start``."""


def _descend(calendar: CompiledCalendar, regime: CompiledRegime, t: int, level: int) -> _Path:
    """The path to the ``level`` unit containing ``t`` in ``regime`` (proleptically)."""
    top = len(calendar.levels) - 1
    rel = t - regime.epoch
    year = regime.year_of_rel(rel)
    start = regime.year_start(year)
    template = regime.year_template(year)
    offset = rel - regime.rel_start(year)
    children: list[tuple[CompiledTemplate, Child]] = []
    for _ in range(top - 1, level - 1, -1):
        child = template.child_at(offset)
        children.append((template, child))
        start += child.offset
        offset -= child.offset
        assert child.template is not None  # children of level >= 1 templates are templates
        template = regime.templates[child.template]
    return _Path(year, start, children, template, offset)


def _variable_step(
    calendar: CompiledCalendar,
    regime: CompiledRegime,
    t: int,
    level: int,
    n: int,
    *,
    overflow: Overflow,
) -> int:
    top = len(calendar.levels) - 1
    origin = _descend(calendar, regime, t, 0)
    before, counted, _ = counted_position(top, regime, t, level, REGULAR)
    # Inside an intercalary unit (between regular units before-1 and before), one unit forward
    # is the next regular unit and one unit back the previous one.
    target = before + n - (1 if not counted and n > 0 else 0)
    start = from_counted_ordinal(
        calendar, calendar.levels[level], target, REGULAR, regime=regime.id
    ).start
    template = _descend(calendar, regime, start, level).template
    for parent, child in origin.children[top - level :]:
        placed = _reapply(calendar, template, parent, child, overflow)
        start += placed.offset
        assert placed.template is not None
        template = regime.templates[placed.template]
    base = origin.offset
    if base >= template.length:
        if overflow == "reject":
            raise DateError("invalid_date", "the base remainder doesn't fit", calendar.levels[0])
        base = template.length - 1
    return start + base


def _reapply(
    calendar: CompiledCalendar,
    template: CompiledTemplate,
    parent: CompiledTemplate,
    child: Child,
    overflow: Overflow,
) -> Child:
    """The child of ``template`` at the position ``child`` had in ``parent`` (§9.2).

    The same slot id if ``template`` has it, else the same regular number constrained to the last
    one; an intercalary position missing from ``template`` becomes the last regular child before
    its original index (or the first regular child). Anything but the same slot id or the same
    number is a constraining step, which ``reject`` refuses.
    """
    segment = child.segment
    regular = child.regular_index
    found: Child | None = None
    if segment.slot_id is not None:
        found = template.child_by_slot(segment.slot_id)
    else:
        assert regular is not None  # unnamed children are never intercalary
        found = template.child_by_regular_index(regular)
    if found is not None:
        return found
    level_id = calendar.levels[parent.level - 1]
    if overflow == "reject":
        raise DateError("invalid_date", f"the {level_id} doesn't exist in the target", level_id)
    if regular is None:
        regular = _regular_before(template, _child_index(parent, child)) - 1
    if template.regular_count == 0:
        return template.child_at(0)
    clamped = min(max(regular, 0), template.regular_count - 1)
    found = template.child_by_regular_index(clamped)
    assert found is not None
    return found


def _child_index(template: CompiledTemplate, child: Child) -> int:
    """0-based index of ``child`` among all children of ``template``."""
    return sum(s.count for s in template.segments[: child.position]) + child.index


def _regular_before(template: CompiledTemplate, index: int) -> int:
    """Number of regular children of ``template`` whose index is below ``index``."""
    firsts = list(accumulate((s.count for s in template.segments), initial=0))
    position = bisect_right(firsts, index) - 1
    if position >= len(template.segments):
        return template.regular_count
    segment = template.segments[position]
    inside = 0 if segment.intercalary else min(index - firsts[position], segment.count)
    return segment.regular_start + inside


# --- diff ----------------------------------------------------------------------------------------


def diff(calendar: CompiledCalendar, t1: int, t2: int, largest: str, smallest: str) -> Difference:
    """§9.3: ``t2 - t1`` in the levels ``largest`` … ``smallest``, greedily from the coarsest.

    For ``t1 ≤ t2``: ``add(t1, amounts) ≤ t2 < add(t1, amounts + 1·smallest)``, and ``base`` is
    ``t2 - add(t1, amounts)``. For ``t1 > t2`` the result is ``diff(t2, t1)`` with sign ``-1``.
    """
    high, low = _level(calendar, largest), _level(calendar, smallest)
    if high < low:
        raise DateError("invalid_date", f"{largest!r} is finer than {smallest!r}", largest)
    if t1 > t2:
        found = diff(calendar, t2, t1, largest, smallest)
        return Difference(found.amounts, found.base, -1)
    amounts: dict[str, int] = {}
    current = t1
    for level in range(high, low - 1, -1):
        count = _fit(calendar, current, level, t2)
        amounts[calendar.levels[level]] = count
        current = _step(calendar, current, level, count, "constrain")
    return Difference(amounts, t2 - current, 1)


def _fit(calendar: CompiledCalendar, t: int, level: int, limit: int) -> int:
    """The largest ``n ≥ 0`` with ``_step(t, level, n) ≤ limit`` (``t ≤ limit``).

    Steps are strictly increasing in ``n``, so an ordinal estimate is corrected by galloping
    and bisecting (a couple of probes in practice).
    """
    length = _uniform_length(calendar, level)
    if length is not None:
        return (limit - t) // length
    regime = active_regime(calendar, t)
    top = len(calendar.levels) - 1
    estimate = (
        counted_position(top, regime, limit, level, REGULAR)[0]
        - counted_position(top, regime, t, level, REGULAR)[0]
    )

    def fits(n: int) -> bool:
        return (
            n == 0 or _variable_step(calendar, regime, t, level, n, overflow="constrain") <= limit
        )

    low = max(estimate, 0)
    if fits(low):  # gallop up to a failing count
        gap = 1
        while fits(low + gap):
            low, gap = low + gap, gap * 2
        high = low + gap
    else:  # gallop down to a fitting count
        high, gap = low, 1
        while not fits(max(high - gap, 0)):
            high, gap = high - gap, gap * 2
        low = max(high - gap, 0)
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (middle, high) if fits(middle) else (low, middle)
    return low


# --- upper bound ---------------------------------------------------------------------------------


def duration_upper_bound(calendar: CompiledCalendar, duration: Duration) -> int:
    """A safe bound on ``|add(t, duration) - t|`` for every ``t`` (recurrence window widening).

    Uniform levels contribute their exact length. A variable step of ``n`` units moves the unit
    start by at most ``n`` maximal units plus the intercalary units skipped in the years crossed,
    and the position inside the unit by less than one maximal unit.
    """
    if isinstance(duration, BaseDuration):
        return abs(int(duration.units))
    return sum(_level_bound(calendar, level, n) for level, n in _ordered(calendar, duration))


def _level_bound(calendar: CompiledCalendar, level: int, n: int) -> int:
    length = _uniform_length(calendar, level)
    if length is not None:
        return n * length
    longest = max(template.length for template in _templates(calendar, level))
    top = len(calendar.levels) - 1
    skipped = 0
    for regime in calendar.regimes:
        memo: dict[str, int] = {}
        for template in regime.templates.values():
            if template.level == top:
                skipped = max(skipped, _intercalary_length(regime, template, level, memo))
    if skipped == 0:
        return (n + 1) * longest
    fewest = min(year.units[level][1] for year in _templates(calendar, top))
    if fewest > 0:
        crossed = n // fewest + 2
    else:  # runs of years without regular units: bounded by the period and the exceptions
        run = max((len(r.exception_years) + 1) * r.period for r in calendar.regimes)
        crossed = n * (run + 1) + 2
    return (n + 1) * longest + crossed * skipped


def _intercalary_length(
    regime: CompiledRegime, template: CompiledTemplate, level: int, memo: dict[str, int]
) -> int:
    """Total length of the intercalary ``level`` units inside one unit of ``template``."""
    if template.level <= level:
        return 0  # the top level: years are never intercalary
    if template.id not in memo:
        total = 0
        for segment in template.segments:
            if template.level - 1 == level:
                total += segment.count * segment.child_length if segment.intercalary else 0
            else:
                assert segment.child is not None
                child = regime.templates[segment.child]
                total += segment.count * _intercalary_length(regime, child, level, memo)
        memo[template.id] = total
    return memo[template.id]
