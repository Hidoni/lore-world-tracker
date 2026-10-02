"""Calendar rules: periods, filters, selectors and time of day (``recurrence.md`` §2).

Periods are units of a level (``freq.level``) or rounds of a continuous cycle (``freq.cycle``),
counted in the regime in force at the series start and extended proleptically (§2.1). A period's
positions come from the selector path (or, for ``select: null``, the series start's position),
then the finer fields from ``time`` or the series start, re-applied like calendar arithmetic.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from lore.chronology.calendar.arithmetic import descend, reapply
from lore.chronology.calendar.compile import ValidationError, pointer
from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledCycle,
    CompiledRegime,
    CompiledTemplate,
    DateError,
    Segment,
    active_regime,
    is_number,
)
from lore.chronology.calendar.convert import Overflow, resolve_child
from lore.chronology.calendar.cycles import regime_cycle_value
from lore.chronology.calendar.units import (
    REGULAR,
    UnitFilter,
    counted_position,
    cycle_filter,
    from_counted_ordinal,
)
from lore.chronology.numbers import floor_div, floor_mod
from lore.chronology.recurrence.plan import (
    MAX_POSITIONS,
    Plan,
    RecurrenceContext,
    RecurrenceError,
)
from lore.chronology.schema import (
    AllFilter,
    AllSelector,
    AnyFilter,
    CalendarRule,
    CycleFilter,
    CycleFreq,
    CycleMatch,
    CycleSelector,
    InFilter,
    LevelFreq,
    LevelSelector,
    ModFilter,
    NotFilter,
    PeriodFilter,
    ValuesSelector,
)


@dataclass(frozen=True, slots=True)
class _Run:
    """A segment of a located template: ``segment.count`` identical units from ``start``."""

    start: int
    segment: Segment


@dataclass(frozen=True, slots=True)
class _Unit:
    """A located unit: its start moment and template."""

    start: int
    template: CompiledTemplate


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code, path, message)


def _single(rule: CalendarRule, levels: Sequence[str], period: int) -> bool:
    """§3: at most one position per period, decided syntactically. A slot id is unique only
    within one template, so at a level that skips levels it may match several units."""
    if rule.select is None:
        return True
    above = period
    for selector in rule.select.path:
        level = levels.index(selector.level)
        if isinstance(selector, AllSelector):
            return False
        if isinstance(selector, ValuesSelector) and (
            len(selector.values) != 1 or (not is_number(selector.values[0]) and level < above - 1)
        ):
            return False
        if isinstance(selector, CycleSelector):
            nth = selector.cycle.nth
            if len(selector.cycle.values) != 1 or nth is None or len(nth) != 1:
                return False
        above = level
    return True


def _cycle_index(cycle: CompiledCycle, value: str) -> int | None:
    """The cycle index a rule value names: an id from ``ids`` or the number ``n``."""
    if is_number(value):
        index = int(value) - cycle.number_start
        return index if 0 <= index < cycle.length else None
    if cycle.ids is None or value not in cycle.ids:
        return None
    return cycle.ids.index(value)


# --- validation (§9) -----------------------------------------------------------------------------


class _Checker:
    def __init__(self, rule: CalendarRule, calendar: CompiledCalendar, regime: CompiledRegime):
        self.rule = rule
        self.calendar = calendar
        self.regime = regime
        self.errors: list[ValidationError] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(_error(code, path, message))

    def cycle(self, cycle_id: str) -> CompiledCycle | None:
        return next((c for c in self.regime.cycles if c.id == cycle_id), None)

    def slots(self, level: int) -> set[str]:
        """Slot ids of the children at ``level`` in any template of the regime."""
        return {
            slot
            for template in self.regime.templates.values()
            if template.level == level + 1
            for slot in template.slots
        }

    def run(self) -> list[ValidationError]:
        rule, levels = self.rule, self.calendar.levels
        if isinstance(rule.freq, LevelFreq):
            if rule.freq.level not in levels:
                self.error("rule.bad_freq_level", "/freq/level", "unknown level")
                return self.errors
            period, cycle = levels.index(rule.freq.level), None
        else:
            cycle = self.cycle(rule.freq.cycle)
            if cycle is None:
                self.error("rule.bad_freq_level", "/freq/cycle", "unknown cycle")
                return self.errors
            if cycle.reset is not None:
                self.error(
                    "rule.cycle_not_continuous", "/freq/cycle", "a reset cycle has no rounds"
                )
                return self.errors
            period = cycle.level
        for i, item in enumerate(rule.filters):
            self.filter(item, pointer("filters", i), period, cycle)
        deepest = period
        if rule.select is not None:
            for i, selector in enumerate(rule.select.path):
                path = pointer("select", "path", i)
                level = levels.index(selector.level) if selector.level in levels else -1
                # Rounds select their own units first; every other selector is strictly finer
                # than the one before (or the period), and may skip levels (day 256 of a year).
                fits = level == deepest if (cycle is not None and i == 0) else 0 <= level < deepest
                if not fits:
                    self.error("rule.bad_selector_level", path + "/level", "not a finer level")
                    return self.errors
                self.selector(selector, path, level, cycle if i == 0 else None)
                deepest = level
        self.time(deepest)
        return self.errors

    def filter(
        self, item: PeriodFilter, path: str, period: int, rounds: CompiledCycle | None
    ) -> None:
        if isinstance(item, ModFilter):
            if int(item.eq) >= int(item.mod):
                self.error("rule.bad_filter", path + "/eq", "eq must be below mod")
        elif isinstance(item, InFilter):
            if rounds is not None:
                self.error("rule.bad_filter", path, "cycle rounds have no number or slot")
                return
            known = self.slots(period)
            for j, value in enumerate(item.in_):
                if not is_number(value) and value not in known:
                    self.error("rule.unknown_slot", f"{path}/in/{j}", "unknown slot")
        elif isinstance(item, CycleFilter):
            cycle = self.cycle(item.cycle)
            if rounds is not None or cycle is None or cycle.level != period:
                self.error("rule.bad_filter", path + "/cycle", "not a cycle of the period level")
                return
            self.cycle_values(cycle, item.in_, path + "/in")
        elif isinstance(item, AllFilter | AnyFilter):
            items = item.all if isinstance(item, AllFilter) else item.any
            member = "all" if isinstance(item, AllFilter) else "any"
            for j, child in enumerate(items):
                self.filter(child, f"{path}/{member}/{j}", period, rounds)
        else:
            assert isinstance(item, NotFilter)
            self.filter(item.not_, path + "/not", period, rounds)

    def cycle_values(
        self, cycle: CompiledCycle, values: Sequence[str], path: str, *, rounds: bool = False
    ) -> None:
        """Values naming cycle positions: ids or numbers (in rounds, negative from the end)."""
        index = _round_index if rounds else _cycle_index
        for j, value in enumerate(values):
            if index(cycle, value) is None:
                self.error("rule.unknown_slot", f"{path}/{j}", f"no value {value!r} in the cycle")

    def selector(
        self, selector: LevelSelector, path: str, level: int, rounds: CompiledCycle | None
    ) -> None:
        if isinstance(selector, ValuesSelector):
            if rounds is not None:
                self.cycle_values(rounds, selector.values, path + "/values", rounds=True)
                return
            known = self.slots(level)
            for j, value in enumerate(selector.values):
                if not is_number(value) and value not in known:
                    self.error("rule.unknown_slot", f"{path}/values/{j}", "unknown slot")
        elif isinstance(selector, CycleSelector):
            cycle = self.cycle(selector.cycle.id)
            if cycle is None or cycle.level != level:
                self.error("rule.bad_selector_level", path + "/cycle/id", "no such cycle here")
                return
            self.cycle_values(cycle, selector.cycle.values, path + "/cycle/values")
            for j, nth in enumerate(selector.cycle.nth or ()):
                if nth == "0":
                    self.error("rule.bad_nth", f"{path}/cycle/nth/{j}", "nth counts from 1 or -1")

    def time(self, deepest: int) -> None:
        if self.rule.time is None:
            return
        levels = self.calendar.levels
        fields = self.rule.time.fields
        bad = [key for key in fields if key not in levels or levels.index(key) >= deepest]
        for key in bad:
            self.error("rule.bad_time_fields", pointer("time", "fields", key), "not below")
        indexes = sorted(levels.index(key) for key in fields if key not in bad)
        if not bad and (not indexes or indexes != list(range(indexes[0], indexes[-1] + 1))):
            self.error("rule.bad_time_fields", "/time/fields", "time fields must be contiguous")


def calendar_rule_errors(
    rule: CalendarRule, calendar: CompiledCalendar, series_start: int
) -> list[ValidationError]:
    """§9 errors of a calendar rule (the regime is the one in force at the series start)."""
    return _Checker(rule, calendar, active_regime(calendar, series_start)).run()


# --- plan ----------------------------------------------------------------------------------------


class CalendarPlan(Plan):
    def __init__(
        self, rule: CalendarRule, ctx: RecurrenceContext, calendar: CompiledCalendar, last: int
    ) -> None:
        super().__init__(ctx, last)
        self.rule = rule
        self.calendar = calendar
        self.top = len(calendar.levels) - 1
        self.regime: CompiledRegime = active_regime(calendar, ctx.series_start)
        self.interval = int(rule.interval)
        self.overflow: Overflow = "constrain" if rule.missing == "constrain" else "reject"
        self.time = (
            {calendar.levels.index(key): value for key, value in rule.time.fields.items()}
            if rule.time is not None
            else None
        )
        self.origin = descend(calendar, self.regime, ctx.series_start, 0)
        self.rounds: CompiledCycle | None = None
        if isinstance(rule.freq, CycleFreq):
            self.rounds = next(c for c in self.regime.cycles if c.id == rule.freq.cycle)
            assert self.rounds.anchor_ordinal is not None  # continuous (validated)
            self.level = self.rounds.level
            self.unit_filter: UnitFilter = cycle_filter(self.rounds.id)
            self.round_base = self.rounds.anchor_ordinal - self.rounds.anchor_index
        else:
            assert isinstance(rule.freq, LevelFreq)
            self.level = calendar.levels.index(rule.freq.level)
            self.unit_filter = REGULAR
            self.round_base = 0
        # Rounds: the first selector picks units of the round, as if one level up.
        above = self.level + 1 if self.rounds is not None else self.level
        self.multi = not _single(rule, calendar.levels, above)
        counted = self._counted(ctx.series_start)
        self.p0 = self._period_of(counted)
        self.start_index = counted - self._first_counted(self.p0)
        """For rounds: the series start's index in its round (``select: null``)."""

    # periods

    def _counted(self, t: int) -> int:
        """Counted ordinal of the ``level`` unit at ``t`` (or of the counted unit before it)."""
        before, counted, _ = counted_position(
            self.top, self.regime, t, self.level, self.unit_filter
        )
        return before if counted else before - 1

    def _period_of(self, counted: int) -> int:
        if self.rounds is None:
            return counted
        return floor_div(counted - self.round_base, self.rounds.length)

    def _first_counted(self, period: int) -> int:
        if self.rounds is None:
            return period
        return self.round_base + period * self.rounds.length

    def k_range(self, low: int, high: int) -> tuple[int, int]:
        p_low = self._period_of(self._counted(low))
        p_high = self._period_of(self._counted(high))
        k_lo = -floor_div(self.p0 - p_low, self.interval)
        return max(0, k_lo), floor_div(p_high - self.p0, self.interval)

    @property
    def dense(self) -> bool:
        rule = self.rule
        return (
            rule.select is None
            and not rule.filters
            and self.overflow == "constrain"
            and self.time is None
        )

    def _unit(self, counted: int) -> _Unit:
        """The counted ``level`` unit with this ordinal."""
        level_id = self.calendar.levels[self.level]
        start = from_counted_ordinal(
            self.calendar, level_id, counted, self.unit_filter, regime=self.regime.id
        ).start
        return _Unit(start, descend(self.calendar, self.regime, start, self.level).template)

    def positions(self, k: int) -> list[int | None]:
        period = self.p0 + k * self.interval
        try:
            if self.rounds is None:
                unit = self._unit(period)
                if not self._passes(period, unit):
                    return []
                units = [unit]
            else:
                if not all(self._passes_round(f, period) for f in self.rule.filters):
                    return []
                units = []
        except DateError:
            return []  # no counted unit has this ordinal
        if self.rule.select is None:
            if self.rounds is not None:
                units = [self._unit(self._first_counted(period) + self.start_index)]
            return [self._tail(unit, self.level) for unit in units]
        selected = self._select(period, units)
        deepest = self.calendar.levels.index(self.rule.select.path[-1].level)
        return [self._tail(unit, deepest) for unit in selected]

    # filters (§2.2)

    def _passes(self, period: int, unit: _Unit) -> bool:
        return all(self._filter(f, period, unit) for f in self.rule.filters)

    def _filter(self, item: PeriodFilter, period: int, unit: _Unit) -> bool:
        if isinstance(item, ModFilter):
            value = period if item.of == "ordinal" else self._number(unit)[0]
            return floor_mod(value, int(item.mod)) == int(item.eq)
        if isinstance(item, InFilter):
            number, slot = self._number(unit)
            return any((int(v) == number) if is_number(v) else v == slot for v in item.in_)
        if isinstance(item, CycleFilter):
            cycle = next(c for c in self.regime.cycles if c.id == item.cycle)
            found = regime_cycle_value(self.top, self.regime, cycle, unit.start)
            return found is not None and any(
                _cycle_index(cycle, v) == found.index for v in item.in_
            )
        if isinstance(item, AllFilter):
            return all(self._filter(f, period, unit) for f in item.all)
        if isinstance(item, AnyFilter):
            return any(self._filter(f, period, unit) for f in item.any)
        assert isinstance(item, NotFilter)
        return not self._filter(item.not_, period, unit)

    def _passes_round(self, item: PeriodFilter, period: int) -> bool:
        """Rounds: ``mod`` filters (number = ordinal = the round ordinal) and combinations."""
        if isinstance(item, ModFilter):
            return floor_mod(period, int(item.mod)) == int(item.eq)
        if isinstance(item, AllFilter):
            return all(self._passes_round(f, period) for f in item.all)
        if isinstance(item, AnyFilter):
            return any(self._passes_round(f, period) for f in item.any)
        assert isinstance(item, NotFilter)  # in/cycle filters on rounds are invalid (validated)
        return not self._passes_round(item.not_, period)

    def _number(self, unit: _Unit) -> tuple[int, str | None]:
        """(regular number within the parent, slot id) of a period unit; the top level: ``Y``."""
        path = descend(self.calendar, self.regime, unit.start, self.level)
        if self.level == self.top:
            return path.year, None
        _, child = path.children[-1]
        assert child.regular_index is not None  # periods are regular units
        return child.regular_index + self.calendar.numbering_starts[
            self.level
        ], child.segment.slot_id

    # selectors (§2.3)

    def _select(self, period: int, units: list[_Unit]) -> list[_Unit]:
        assert self.rule.select is not None
        path = self.rule.select.path
        if self.rounds is not None:
            units = self._select_round(period, path[0])
            path = path[1:]
        for selector in path:
            level = self.calendar.levels.index(selector.level)
            chosen: list[_Unit] = []
            for unit in units:
                chosen += self._select_children(unit, selector, level)
                if len(chosen) > MAX_POSITIONS:
                    raise RecurrenceError("rule.too_many_positions", "too many positions")
            units = chosen
        return units

    def _select_round(self, period: int, selector: LevelSelector) -> list[_Unit]:
        cycle = self.rounds
        assert cycle is not None
        length = cycle.length
        if isinstance(selector, AllSelector):
            indexes: Sequence[int] = range(length)
        elif isinstance(selector, ValuesSelector):
            indexes = sorted(
                {index for v in selector.values if (index := _round_index(cycle, v)) is not None}
            )
        else:
            match = selector.cycle
            other = next(c for c in self.regime.cycles if c.id == match.id)
            first = self._first_counted(period)
            units = [self._unit(first + i) for i in range(length)]
            values = [regime_cycle_value(self.top, self.regime, other, u.start) for u in units]
            found: set[int] = set()
            for value in match.values:
                wanted = _cycle_index(other, value)
                hits = [i for i, v in enumerate(values) if v is not None and v.index == wanted]
                found.update(_nth(hits, match.nth))
            return [units[i] for i in sorted(found)]
        if len(indexes) > MAX_POSITIONS:
            raise RecurrenceError("rule.too_many_positions", "too many positions")
        first = self._first_counted(period)
        return [self._unit(first + i) for i in indexes]

    def _runs(self, unit: _Unit, level: int) -> list[_Run]:
        """The runs of ``level`` units inside ``unit``, in time order (its children when ``level``
        is the next level down, else every descendant run)."""
        runs: list[_Run] = []

        def walk(start: int, template: CompiledTemplate) -> None:
            for segment in template.segments:
                first = start + segment.start
                if template.level - 1 == level:
                    runs.append(_Run(first, segment))
                    continue
                assert segment.child is not None
                child = self.regime.templates[segment.child]
                if len(runs) + segment.count * self._run_count(child, level) > MAX_POSITIONS:
                    raise RecurrenceError("rule.too_many_positions", "too many positions")
                for i in range(segment.count):
                    walk(first + i * segment.child_length, child)

        walk(unit.start, unit.template)
        return runs

    def _run_count(self, template: CompiledTemplate, level: int) -> int:
        key = ("runs", template.id, level)
        cached = self.regime.cache.get(key)
        if not isinstance(cached, int):
            if template.level - 1 == level:
                cached = len(template.segments)
            else:
                cached = sum(
                    segment.count * self._run_count(self.regime.templates[segment.child], level)
                    for segment in template.segments
                    if segment.child is not None
                )
            self.regime.cache[key] = cached
        return cached

    def _unit_at(self, run: _Run, i: int) -> _Unit:
        assert run.segment.child is not None
        start = run.start + i * run.segment.child_length
        return _Unit(start, self.regime.templates[run.segment.child])

    def _select_children(self, unit: _Unit, selector: LevelSelector, level: int) -> list[_Unit]:
        """The ``level`` units inside ``unit`` that ``selector`` picks, in time order. Numbers
        count the regular ``level`` units of ``unit`` from the level's numbering start (negative:
        from the end); slot ids, ``all`` and cycle matches look at every ``level`` unit in it."""
        runs = self._runs(unit, level)
        if isinstance(selector, CycleSelector):
            return self._cycle_children(runs, selector.cycle)
        regular = [run for run in runs if not run.segment.intercalary]
        total = sum(run.segment.count for run in regular)
        if isinstance(selector, AllSelector):
            if total > MAX_POSITIONS:
                raise RecurrenceError("rule.too_many_positions", "too many positions")
            return [self._unit_at(run, i) for run in regular for i in range(run.segment.count)]
        chosen: dict[int, _Unit] = {}
        numbering = self.calendar.numbering_starts[level]
        for value in selector.values:
            if is_number(value):
                n = int(value)
                index = total + n if n < 0 else n - numbering
                if 0 <= index < total:
                    found = _nth_unit(regular, index)
                    chosen[found[0].start + found[1] * found[0].segment.child_length] = (
                        self._unit_at(*found)
                    )
            else:
                for run in runs:
                    if run.segment.slot_id == value:
                        chosen[run.start] = self._unit_at(run, 0)
        return [chosen[start] for start in sorted(chosen)]

    def _cycle_children(self, runs: list[_Run], match: CycleMatch) -> list[_Unit]:
        """Units whose cycle value matches, per value with optional ``nth`` (arithmetic over each
        run: the cycle indexes of a run's units are consecutive)."""
        cycle = next(c for c in self.regime.cycles if c.id == match.id)
        counted: list[tuple[_Run, int]] = []
        for run in runs:
            found = regime_cycle_value(self.top, self.regime, cycle, run.start)
            if found is not None:
                counted.append((run, found.index))
        chosen: dict[int, _Unit] = {}
        for value in match.values:
            wanted = _cycle_index(cycle, value)
            assert wanted is not None  # validated
            for run, i in _CycleHits(counted, wanted, cycle.length).select(match.nth):
                unit = self._unit_at(run, i)
                chosen[unit.start] = unit
                if len(chosen) > MAX_POSITIONS:
                    raise RecurrenceError("rule.too_many_positions", "too many positions")
        return [chosen[start] for start in sorted(chosen)]

    # finer positions (§2.4)

    def _tail(self, unit: _Unit, level: int) -> int | None:
        """The occurrence start inside the selected ``level`` unit, or ``None`` when a finer
        position doesn't exist (``missing: skip``)."""
        calendar, regime, time = self.calendar, self.regime, self.time
        start, template = unit.start, unit.template
        try:
            for lower in range(level - 1, -1, -1):
                if time is not None and lower < min(time):
                    return start  # below the time fields: the start of the deepest timed unit
                if time is not None and lower in time:
                    child = resolve_child(
                        calendar, regime, template, lower, time[lower], overflow=self.overflow
                    )
                else:
                    parent, original = self.origin.children[self.top - 1 - lower]
                    child = reapply(calendar, template, parent, original, self.overflow)
                start += child.offset
                assert child.template is not None
                template = regime.templates[child.template]
        except DateError:
            return None
        if time is not None:
            return start
        base = self.origin.offset
        if base >= template.length:
            if self.overflow == "reject":
                return None
            base = template.length - 1
        return start + base


def _round_index(cycle: CompiledCycle, value: str) -> int | None:
    """A position in a round: a cycle id or number, negative numbers from the end."""
    if is_number(value) and int(value) < 0:
        index = cycle.length + int(value)
        return index if index >= 0 else None
    return _cycle_index(cycle, value)


def _nth(hits: list[int], nth: Sequence[str] | None) -> list[int]:
    if nth is None:
        return hits
    chosen = []
    for item in nth:
        n = int(item)
        index = n - 1 if n > 0 else len(hits) + n
        if 0 <= index < len(hits):
            chosen.append(hits[index])
    return chosen


def _nth_unit(runs: list[_Run], index: int) -> tuple[_Run, int]:
    """The run and position of the ``index``-th unit over ``runs``."""
    for run in runs:
        if index < run.segment.count:
            return run, index
        index -= run.segment.count
    raise AssertionError("unreachable")  # pragma: no cover


class _CycleHits:
    """The units with one cycle index, over runs whose first unit has a known index."""

    def __init__(self, runs: list[tuple[_Run, int]], wanted: int, length: int):
        self.runs = runs
        self.length = length
        self.firsts = [(wanted - first) % length for _, first in runs]
        self.counts = [
            0 if f >= run.segment.count else (run.segment.count - 1 - f) // length + 1
            for (run, _), f in zip(runs, self.firsts, strict=True)
        ]

    def _at(self, index: int) -> tuple[_Run, int]:
        for (run, _), first, count in zip(self.runs, self.firsts, self.counts, strict=True):
            if index < count:
                return run, first + index * self.length
            index -= count
        raise AssertionError("unreachable")  # pragma: no cover

    def select(self, nth: Sequence[str] | None) -> Iterator[tuple[_Run, int]]:
        total = sum(self.counts)
        if nth is None:
            if total > MAX_POSITIONS:
                raise RecurrenceError("rule.too_many_positions", "too many positions")
            indexes: Sequence[int] = range(total)
        else:
            indexes = [n - 1 if n > 0 else total + n for n in map(int, nth)]
        for index in indexes:
            if 0 <= index < total:
                yield self._at(index)
