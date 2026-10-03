"""Formatting dates and spans (``chronology-engine.md`` §3.11, §10).

A date is rendered with the pattern for its precision: ``formats[<precision>]``, or
``formats.intercalary[<precision>]`` when the deepest named unit at or above the precision is
intercalary, else a pattern generated from the levels. Numbers use the calendar's ``display``
options: up to 4 digits they are plain, longer ones are grouped, and from
``scientific_threshold`` digits on they switch to scientific notation.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from lore.chronology.calendar import formats
from lore.chronology.calendar.compiled import CompiledCalendar, DateError
from lore.chronology.calendar.convert import DateFields, UnitValue, to_fields
from lore.chronology.calendar.formats import Piece, Token
from lore.chronology.numbers import format_integer
from lore.chronology.schema import BaseUnit, DisplayOptions

BASE = "base"
"""The precision finer than every level: exact moments."""

_PLAIN_DIGITS = 4
"""Date numbers with at most this many digits are never grouped (2024, not 2,024)."""

_SPACES = re.compile(r" {2,}")


@dataclass(frozen=True, slots=True)
class DisplayPoint:
    """A resolved time point to display: moment, precision (level id or ``base``), circa."""

    t: int
    precision: str
    approximate: bool = False


# --- calendar layout (cached per compiled calendar) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class _Layout:
    display: DisplayOptions
    named: frozenset[int]
    """Levels with named slots in some template of some regime."""
    clock: int
    """Levels ``0 … clock-1`` form the clock of default formats (unnamed, numbered from 0)."""
    base_suffix: bool
    """Some level-0 unit spans several base units, so ``base`` precision shows the remainder."""
    cycle_levels: dict[str, int]


@lru_cache(maxsize=64)
def _layout(calendar: CompiledCalendar) -> _Layout:
    definition = calendar.definition
    named = frozenset(
        template.level - 1
        for regime in calendar.regimes
        for template in regime.templates.values()
        if any(segment.slot_id is not None for segment in template.segments)
    )
    clock = 0
    top = len(calendar.levels) - 1
    while clock < top and clock not in named and calendar.numbering_starts[clock] == 0:
        clock += 1
    base_suffix = any(
        template.length > 1
        for regime in calendar.regimes
        for template in regime.templates.values()
        if template.level == 0
    )
    cycle_levels = {cycle.id: cycle.level for regime in calendar.regimes for cycle in regime.cycles}
    return _Layout(definition.display or DisplayOptions(), named, clock, base_suffix, cycle_levels)


# --- one date ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Date:
    fields: DateFields
    level: int
    """Index of the precision level (0 for ``base``)."""
    base: bool
    """The precision is ``base``."""


def _date(calendar: CompiledCalendar, t: int, precision: str) -> _Date:
    if precision == BASE:
        return _Date(to_fields(calendar, t), 0, True)
    if precision not in calendar.levels:
        raise DateError("invalid_date", f"unknown precision {precision!r}", precision)
    return _Date(to_fields(calendar, t), calendar.levels.index(precision), False)


def format_date(
    calendar: CompiledCalendar, t: int, precision: str, *, approximate: bool = False
) -> str:
    """§10 ``format``: the date of ``t`` at ``precision``, with the circa prefix if approximate."""
    date = _date(calendar, t, precision)
    text = _render(calendar, date, _pattern(calendar, date))
    return _circa(calendar, text, approximate=approximate)


def _circa(calendar: CompiledCalendar, text: str, *, approximate: bool) -> str:
    return _layout(calendar).display.circa + text if approximate else text


def _intercalary(calendar: CompiledCalendar, date: _Date) -> bool:
    """The deepest named unit at or above the precision is intercalary."""
    for level in range(date.level, len(calendar.levels) - 1):
        value = date.fields.levels[calendar.levels[level]]
        if value.slot_id is not None:
            return value.intercalary
    return False


def _pattern(calendar: CompiledCalendar, date: _Date) -> tuple[Piece, ...]:
    """The pieces of the pattern used for ``date`` (custom or generated, §3.11)."""
    level_id = calendar.levels[date.level]
    custom = calendar.definition.formats
    pattern: str | None = None
    if custom is not None:
        if _intercalary(calendar, date):
            pattern = custom.intercalary.get(level_id)
        else:
            pattern = (custom.model_extra or {}).get(level_id)
    pieces = formats.parse(pattern) if pattern is not None else _default(calendar, date)
    has_base = any(isinstance(piece, Token) and piece.kind == "base" for piece in pieces)
    if date.base and _layout(calendar).base_suffix and not has_base:
        pieces += [" + ", Token("base"), " " + calendar.context.base_unit.abbr]
    return tuple(pieces)


def _default(calendar: CompiledCalendar, date: _Date) -> list[Piece]:
    """The generated pattern: the date fine → coarse (names for named levels, the year with its
    era), then a clock of the numeric 0-based levels; only children are left out."""
    layout = _layout(calendar)
    levels = calendar.levels
    parts: list[list[Piece]] = []
    for level in range(max(date.level, layout.clock), len(levels) - 1):
        if not date.fields.levels[levels[level]].only_child:
            attr = "name" if level in layout.named else None
            parts.append([Token("level", levels[level], attr)])
    era = date.fields.era
    if era is None:
        parts.append([Token("year")])
    elif next(e for e in calendar.eras if e.id == era.id).abbr_position == "prefix":
        parts.append([Token("era"), " ", Token("era_year")])
    else:
        parts.append([Token("era_year"), " ", Token("era")])
    pieces = _join(parts, " ")
    if date.level < layout.clock:
        clock = range(layout.clock - 1, date.level - 1, -1)
        if len(clock) == 1:
            unit = calendar.definition.levels[date.level]
            pieces += [", ", Token("level", unit.id), " " + (unit.abbr or unit.label)]
        else:
            parts = [[Token("level", levels[level], modifier="pad2")] for level in clock]
            pieces += [", ", *_join(parts, ":")]
    return pieces


def _join(parts: Sequence[list[Piece]], separator: str) -> list[Piece]:
    joined: list[Piece] = []
    for i, part in enumerate(parts):
        if i:
            joined.append(separator)
        joined += part
    return joined


def _render(calendar: CompiledCalendar, date: _Date, pieces: Sequence[Piece]) -> str:
    """The text of ``pieces``; runs of spaces left by empty values collapse, ends are trimmed."""
    text = "".join(
        piece if isinstance(piece, str) else _value(calendar, date, piece) for piece in pieces
    )
    return _SPACES.sub(" ", text).strip()


def _value(calendar: CompiledCalendar, date: _Date, token: Token) -> str:
    fields = date.fields
    display = _layout(calendar).display
    if token.kind == "level":
        return _level(fields.levels[token.id or ""], display, token)
    if token.kind == "cycle":
        return _cycle(calendar, date, token)
    if token.kind == "overlay":
        overlay = fields.overlays[token.id or ""]
        # .fraction truncates, so it never shows 1.00
        return (
            f"0.{math.floor(overlay.phase * 100):02d}" if token.attr == "fraction" else overlay.name
        )
    if token.kind == "era":
        if fields.era is None:
            return ""
        return fields.era.name if token.attr == "name" else fields.era.abbr
    year = fields.levels[calendar.levels[-1]].n
    assert year is not None  # the top level is always numbered
    numbers = {
        "year": year,
        "era_year": year if fields.era is None else fields.era.year,
        "base": fields.base,
    }
    return _number(numbers[token.kind], display, token.modifier)


def _level(value: UnitValue, display: DisplayOptions, token: Token) -> str:
    """A level token: the number, or slot information falling back to the number."""
    number = "" if value.n is None else _number(value.n, display, token.modifier)
    fallbacks = {"name": [value.name], "abbr": [value.abbr, value.name], "id": [value.slot_id]}
    return next((text for text in fallbacks.get(token.attr or "", []) if text), number)


def _cycle(calendar: CompiledCalendar, date: _Date, token: Token) -> str:
    """A cycle's name (number without names), abbreviation or number; empty where excluded or
    in a regime without the cycle."""
    value = date.fields.cycles.get(token.id or "")
    if value is None:
        return ""
    if token.attr == "n":
        return str(value.n)
    if token.attr == "abbr":
        regime = next(r for r in calendar.regimes if r.id == date.fields.regime)
        cycle = next(c for c in regime.cycles if c.id == token.id)
        if cycle.abbrs is not None:
            return cycle.abbrs[value.index]
    return value.name or str(value.n)


def _number(n: int, display: DisplayOptions, modifier: str | None = None) -> str:
    """A date number: plain up to 4 digits, else grouped, scientific from the threshold on."""
    digits = str(abs(n))
    text = format_integer(
        n,
        digit_group=display.digit_group if len(digits) > _PLAIN_DIGITS else "",
        scientific_threshold=display.scientific_threshold,
        significant_digits=display.significant_digits,
    )
    if modifier in ("pad2", "pad3") and text == str(n):
        return ("-" if n < 0 else "") + digits.zfill(int(modifier[-1]))
    if modifier == "ordinal" and len(digits) < display.scientific_threshold:
        return text + _ordinal_suffix(abs(n))  # a suffix on "10^8" would misread as "10 to the 8th"
    return text


def _ordinal_suffix(n: int) -> str:
    if n % 100 in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# --- spans ---------------------------------------------------------------------------------------


def format_span(
    calendar: CompiledCalendar, start: DisplayPoint | None, end: DisplayPoint | None
) -> str:
    """§10 ``format_span``: start and end with the shared coarse parts written once.

    Collapsing needs both ends to use the same pattern (same precision, same intercalary
    choice). The parts that differ are the tokens at or below the coarsest differing level; if
    they all come before the shared ones, the start keeps only them ("12 to 15 March 2024"); if
    they all come after, the end does ("15 March 2024, 14:30 to 16:00"). Both ends in the same
    unit (and equally approximate) give a single date. An open end (``None``) is ``?``.
    """
    separator = _layout(calendar).display.range_separator
    if start is None or end is None:
        texts = [
            "?"
            if point is None
            else format_date(calendar, point.t, point.precision, approximate=point.approximate)
            for point in (start, end)
        ]
        return separator.join(texts)
    first, last = _date(calendar, start.t, start.precision), _date(calendar, end.t, end.precision)
    pattern, end_pattern = _pattern(calendar, first), _pattern(calendar, last)
    start_pieces: Sequence[Piece] = pattern
    end_pieces: Sequence[Piece] = end_pattern
    if start.precision == end.precision and pattern == end_pattern:
        differing = _differing(calendar, first, last)
        if differing is None and start.approximate == end.approximate:
            text = _render(calendar, first, pattern)
            return _circa(calendar, text, approximate=start.approximate)
        if differing is not None:
            start_pieces, end_pieces = _collapse(calendar, pattern, differing)
    return separator.join(
        [
            _circa(calendar, _render(calendar, first, start_pieces), approximate=start.approximate),
            _circa(calendar, _render(calendar, last, end_pieces), approximate=end.approximate),
        ]
    )


def _differing(calendar: CompiledCalendar, first: _Date, last: _Date) -> int | None:
    """The coarsest level at which two dates of one precision differ (the top level + 1 for a
    different era, or for equal fields in different regimes; -1 for the base remainder), or
    ``None`` for the same unit."""
    a, b = first.fields, last.fields
    top = len(calendar.levels) - 1
    if (a.era and a.era.id) != (b.era and b.era.id):
        return top + 1
    for level in range(top, first.level - 1, -1):
        if a.levels[calendar.levels[level]] != b.levels[calendar.levels[level]]:
            return level
    if first.base and a.base != b.base:
        return -1
    return top + 1 if a.regime != b.regime else None


def _rank(calendar: CompiledCalendar, token: Token) -> int:
    """The level a token's value depends on (-1: finer than level 0)."""
    top = len(calendar.levels) - 1
    match token.kind:
        case "level":
            assert token.id is not None
            return calendar.levels.index(token.id)
        case "year" | "era_year":
            return top
        case "era":
            return top + 1
        case "cycle":
            return _layout(calendar).cycle_levels[token.id or ""]
        case "base" | "overlay":
            return -1


def _collapse(
    calendar: CompiledCalendar, pattern: Sequence[Piece], differing: int
) -> tuple[Sequence[Piece], Sequence[Piece]]:
    """(start pieces, end pieces) with the shared tokens dropped from one end, if possible."""
    varying = [
        i
        for i, piece in enumerate(pattern)
        if isinstance(piece, Token) and _rank(calendar, piece) <= differing
    ]
    shared = [
        i
        for i, piece in enumerate(pattern)
        if isinstance(piece, Token) and _rank(calendar, piece) > differing
    ]
    if varying and shared:
        if max(varying) < min(shared):
            return pattern[: max(varying) + 1], pattern
        if min(varying) > max(shared):
            return pattern, pattern[min(varying) :]
    return pattern, pattern


# --- the Absolute calendar -----------------------------------------------------------------------


def format_absolute(
    t: int,
    base_unit: BaseUnit,
    display: DisplayOptions | None = None,
    *,
    approximate: bool = False,
) -> str:
    """§10: the virtual Absolute calendar, ``t = <grouped or scientific> <abbr>``."""
    options = display or DisplayOptions()
    number = format_integer(
        t,
        digit_group=options.digit_group,
        scientific_threshold=options.scientific_threshold,
        significant_digits=options.significant_digits,
    )
    text = f"t = {number} {base_unit.abbr}"
    return options.circa + text if approximate else text
