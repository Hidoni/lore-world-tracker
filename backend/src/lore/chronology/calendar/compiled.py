"""Compiled calendars: immutable, precomputed structures (``chronology-engine.md`` §4-§5).

Built by :func:`lore.chronology.calendar.compile.compile_calendar`. Everything here is read-only;
lookups are logarithmic (binary searches over prefix sums), never loops over years or units.
"""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from lore.chronology.schema import CalendarDefinition, CompileContext

type DateErrorCode = Literal["invalid_date", "reform_gap", "reform_ambiguous", "unknown_cycle"]

_NUMBER = re.compile(r"-?[0-9]+")


def is_number(value: str) -> bool:
    """A field value is a regular number (else it is a slot id)."""
    return _NUMBER.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of identical children inside a template (a named slot is a segment of count 1)."""

    count: int
    child: str | None
    """Child template id; ``None`` for level-0 templates (children are base units)."""
    child_length: int
    start: int
    """Base-unit offset of the segment's first child within the template."""
    regular_start: int
    """Number of regular (non-intercalary) children before the segment."""
    slot_id: str | None = None
    name: str | None = None
    abbr: str | None = None
    intercalary: bool = False
    cycle_excluded: tuple[str, ...] = ()

    @property
    def regular_count(self) -> int:
        return 0 if self.intercalary else self.count


@dataclass(frozen=True, slots=True)
class Child:
    """One child unit located inside a template."""

    segment: Segment
    position: int
    """Index of the segment within the template."""
    index: int
    """Index of the child within its segment."""
    offset: int
    """Base-unit offset of the child within the parent template."""

    @property
    def template(self) -> str | None:
        return self.segment.child

    @property
    def length(self) -> int:
        return self.segment.child_length

    @property
    def regular_index(self) -> int | None:
        """0-based ordinal among regular siblings; ``None`` for an intercalary child."""
        return None if self.segment.intercalary else self.segment.regular_start + self.index


@dataclass(frozen=True, slots=True)
class CompiledTemplate:
    """The layout of one unit at one level, with prefix sums (chronology-engine §3.4, §5.5)."""

    id: str
    level: int
    """Index of the template's level in the calendar's levels (0 = finest)."""
    length: int
    """``L(T)`` in base units."""
    segments: tuple[Segment, ...]
    slots: Mapping[str, int]
    """Slot id → segment index."""
    total_count: int
    """Number of children."""
    regular_count: int
    """Number of regular (non-intercalary) children."""
    units: Mapping[int, tuple[int, int]]
    """Level index → (total, regular) number of descendant units at that level."""
    _starts: tuple[int, ...] = field(repr=False)
    _regular_segments: tuple[int, ...] = field(repr=False)
    _regular_starts: tuple[int, ...] = field(repr=False)

    def child_at(self, offset: int) -> Child:
        """The child containing ``0 ≤ offset < length`` (binary search over the prefix sums)."""
        position = bisect_right(self._starts, offset) - 1
        segment = self.segments[position]
        index = (offset - segment.start) // segment.child_length
        return Child(segment, position, index, segment.start + index * segment.child_length)

    def child_by_regular_index(self, regular_index: int) -> Child | None:
        """The regular child with this 0-based ordinal, if it exists."""
        if not 0 <= regular_index < self.regular_count:
            return None
        position = self._regular_segments[bisect_right(self._regular_starts, regular_index) - 1]
        segment = self.segments[position]
        index = regular_index - segment.regular_start
        return Child(segment, position, index, segment.start + index * segment.child_length)

    def child_by_slot(self, slot_id: str) -> Child | None:
        position = self.slots.get(slot_id)
        if position is None:
            return None
        segment = self.segments[position]
        return Child(segment, position, 0, segment.start)


def build_template(
    template_id: str, level: int, segments: Sequence[Segment], units: Mapping[int, tuple[int, int]]
) -> CompiledTemplate:
    """Assemble a template from segments whose ``start``/``regular_start`` are already set."""
    last = segments[-1]
    regular = [i for i, segment in enumerate(segments) if not segment.intercalary]
    return CompiledTemplate(
        id=template_id,
        level=level,
        length=last.start + last.count * last.child_length,
        segments=tuple(segments),
        slots={s.slot_id: i for i, s in enumerate(segments) if s.slot_id is not None},
        total_count=sum(segment.count for segment in segments),
        regular_count=last.regular_start + last.regular_count,
        units=dict(units),
        _starts=tuple(segment.start for segment in segments),
        _regular_segments=tuple(regular),
        _regular_starts=tuple(segments[i].regular_start for i in regular),
    )


@dataclass(frozen=True, slots=True)
class CompiledCycle:
    """A parallel cycle (chronology-engine §3.7), evaluated by the ``cycles`` module."""

    id: str
    level: int
    """Index of the cycle's level."""
    length: int
    names: tuple[str, ...] | None
    abbrs: tuple[str, ...] | None
    number_start: int
    reset: int | None
    """Index of the reset level; ``None`` for a continuous cycle."""
    anchor_index: int
    anchor_ordinal: int | None
    """Continuous cycles: counted ordinal of the unit with ``anchor_index``. ``None`` for reset
    cycles, and for a cycle continuing across a regime start that is still ``local`` (#14)."""


@dataclass(frozen=True, slots=True)
class CompiledRegime:
    """One regime: templates, the top-level period and exceptions, and the epoch (§5.1-§5.4)."""

    id: str
    index: int
    templates: Mapping[str, CompiledTemplate]
    period: int
    """``P``: the top pattern repeats every ``P`` years."""
    top_templates: tuple[str, ...]
    """Distinct template ids used by the pattern; ``top_sequence`` indexes into it."""
    top_sequence: Sequence[int] = field(repr=False)
    """Template (index into ``top_templates``) of years ``0 … P-1`` of a period."""
    year_starts: Sequence[int] = field(repr=False)
    """``S[0..P]``: prefix sums of year lengths over one period."""
    cycle_length: int
    """``C = S[P]``."""
    exception_years: tuple[int, ...]
    exception_templates: tuple[str, ...]
    exception_deltas: tuple[int, ...] = field(repr=False)
    """Prefix sums of ``Δ_e`` over the sorted exceptions (length n + 1)."""
    exception_starts: tuple[int, ...]
    """``A_e = rel_start(Y_e)`` for each exception."""
    epoch: int
    """``E``: the moment year 0 starts."""
    starts_at: int | None
    """Resolved start moment (``None`` for regime 0 and before ``local`` starts are resolved)."""
    cycles: tuple[CompiledCycle, ...] = ()
    cache: dict[object, object] = field(default_factory=dict, repr=False, compare=False)
    """Derived structures computed on first use (unit counts per level and filter, #12)."""

    def _cumulative(self, year: int) -> int:
        """``cum(Y) = Σ_{Y_e < Y} Δ_e - Σ_{Y_e < 0} Δ_e``."""
        before = self.exception_deltas[bisect_left(self.exception_years, year)]
        return before - self.exception_deltas[bisect_left(self.exception_years, 0)]

    def regular_template(self, year: int) -> str:
        """``tmpl(Y)`` from the pattern alone (ignoring exceptions)."""
        return self.top_templates[self.top_sequence[year % self.period]]

    def year_template(self, year: int) -> CompiledTemplate:
        """``tmpl*(Y)``: the template year ``Y`` uses, honoring exceptions."""
        position = bisect_left(self.exception_years, year)
        if position < len(self.exception_years) and self.exception_years[position] == year:
            return self.templates[self.exception_templates[position]]
        return self.templates[self.regular_template(year)]

    def rel_start(self, year: int) -> int:
        """Start of year ``Y`` relative to the epoch (§5.1-§5.2)."""
        k, i = divmod(year, self.period)
        return k * self.cycle_length + self.year_starts[i] + self._cumulative(year)

    def year_of_rel(self, rel: int) -> int:
        """The year containing the epoch-relative moment ``rel`` (§5.3)."""
        position = bisect_right(self.exception_starts, rel) - 1
        if position >= 0:
            exception_year = self.exception_years[position]
            length = self.templates[self.exception_templates[position]].length
            if rel < self.exception_starts[position] + length:
                return exception_year
            offset = self._cumulative(exception_year + 1)
        else:
            offset = self._cumulative(min(self.exception_years, default=0))
        regular = rel - offset
        k, s = divmod(regular, self.cycle_length)
        return k * self.period + bisect_right(self.year_starts, s, hi=self.period) - 1

    def year_start(self, year: int) -> int:
        """Absolute start moment of year ``Y`` (``E + rel_start(Y)``)."""
        return self.epoch + self.rel_start(year)

    def year_of(self, t: int) -> int:
        """The year containing moment ``t`` in this regime's structure."""
        return self.year_of_rel(t - self.epoch)


@dataclass(frozen=True, slots=True)
class CompiledEra:
    """An era with its resolved bounds (chronology-engine §3.8)."""

    id: str
    name: str
    abbr: str
    abbr_position: Literal["prefix", "suffix"]
    backward: bool
    first: int
    start: int | None
    """Start moment (``None`` for era 0: since -∞)."""
    end: int | None
    """The next era's start (``None`` for the last era)."""
    start_year: int | None
    """``Y(start)``: the year containing the start (forward eras)."""
    end_year: int | None
    """``Y_end``: the first year starting at or after ``end`` (backward eras)."""

    def era_year(self, year: int) -> int:
        """The era-relative number of astronomical year ``year``."""
        if self.backward:
            assert self.end_year is not None
            return self.end_year - year + self.first - 1
        assert self.start_year is not None
        return year - self.start_year + self.first

    def year(self, era_year: int) -> int:
        """The astronomical year of era year ``era_year`` (the inverse of :meth:`era_year`)."""
        if self.backward:
            assert self.end_year is not None
            return self.end_year - era_year + self.first - 1
        assert self.start_year is not None
        return era_year - self.first + self.start_year


@dataclass(frozen=True, eq=False, slots=True)
class CompiledCalendar:
    """An immutable compiled calendar, equal/hashable by (definition hash, context hash)."""

    definition: CalendarDefinition = field(repr=False)
    context: CompileContext = field(repr=False)
    levels: tuple[str, ...]
    """Level ids, fine → coarse (index 0 is made of base units; the last is the top level)."""
    numbering_starts: tuple[int, ...]
    regimes: tuple[CompiledRegime, ...]
    definition_hash: str
    context_hash: str
    eras: tuple[CompiledEra, ...] = ()
    overlay_epochs: tuple[int, ...] = ()
    """Resolved epoch of each overlay, in definition order (used by #15)."""

    @property
    def key(self) -> tuple[str, str]:
        return (self.definition_hash, self.context_hash)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CompiledCalendar) and self.key == other.key

    def __hash__(self) -> int:
        return hash(self.key)

    def level_index(self, level_id: str) -> int:
        return self.levels.index(level_id)


class DateError(ValueError):
    """A date the calendar can't resolve. ``level`` names the offending level, if any."""

    def __init__(self, code: DateErrorCode, message: str, level: str | None = None) -> None:
        super().__init__(message)
        self.code: DateErrorCode = code
        self.level = level


def active_regime(calendar: CompiledCalendar, t: int) -> CompiledRegime:
    """The last regime whose start is ``≤ t`` (regime 0 before every other).

    Regimes whose start is a ``local`` anchor are resolved by #14; until then they never activate.
    """
    return next(
        regime
        for regime in reversed(calendar.regimes)
        if regime.index == 0 or (regime.starts_at is not None and regime.starts_at <= t)
    )
