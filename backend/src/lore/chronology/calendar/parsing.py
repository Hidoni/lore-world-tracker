"""Parsing typed dates (``chronology-engine.md`` §10.1): the calendar's formats in reverse.

The text is normalized (trimmed, whitespace runs to one space, an optional circa prefix), then
matched against the patterns ``format`` uses, from the finest precision to the top. A space in a
pattern matches any number of spaces, tokens match the values they can render (names,
abbreviations or ids of slots, numbers, era abbreviations or names, cycle and overlay values),
and matching backtracks. The first match that makes a valid date wins: consistent fields, every
level known down to the precision (an omitted only child filled in), accepted by
``from_fields``, and cycle and overlay tokens that agree with the result.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from lore.chronology.calendar import formats
from lore.chronology.calendar.arithmetic import descend
from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    DateError,
    active_regime,
    is_number,
)
from lore.chronology.calendar.convert import from_fields, to_fields
from lore.chronology.calendar.formats import Piece, Token
from lore.chronology.calendar.formatting import BASE, layout_of

MATCH_LIMIT = 1000
"""Most complete matches of one pattern checked for a valid date."""

_SPACE = re.compile(r"\s+")
_MINUS = "\u2212"
"""The minus sign, read like a hyphen."""
_ORDINAL = ("st", "nd", "rd", "th")


def _digits(text: str) -> bool:
    """ASCII digits only (``str.isdigit`` accepts ``²``, which ``int`` refuses)."""
    return text != "" and all("0" <= char <= "9" for char in text)


@dataclass(frozen=True, slots=True)
class ParsedDate:
    fields: dict[str, str]
    """From the top level down to ``precision`` (the year era-relative with ``era``)."""
    era: str | None
    precision: str
    """A level id, or ``base``."""
    approximate: bool
    t: int

    def as_json(self) -> dict[str, object]:
        return {
            "fields": self.fields,
            "era": self.era,
            "precision": self.precision,
            "approximate": self.approximate,
            "t": str(self.t),
        }


# A matched token: (kind, id, value).
type Capture = tuple[str, str | None, str]


@dataclass(frozen=True, slots=True)
class _Space:
    """A run of spaces in a pattern: matches any number of spaces."""


type _Element = str | _Space | Token


def _elements(pieces: Sequence[Piece]) -> list[_Element]:
    found: list[_Element] = []
    for piece in pieces:
        if isinstance(piece, Token):
            found.append(piece)
            continue
        for char in piece:
            if char.isspace():
                if not (found and isinstance(found[-1], _Space)):
                    found.append(_Space())
            else:
                found.append(char.lower())
    return found


# --- patterns ------------------------------------------------------------------------------------


def _default(calendar: CompiledCalendar, level: int) -> list[list[Piece]]:
    """The generated patterns of a precision, without only-child omissions, with the year as
    ``{year}`` (no eras) or as ``{era_year} {era}`` and ``{era} {era_year}``."""
    layout = layout_of(calendar)
    levels = calendar.levels
    date: list[Piece] = []
    for index in range(max(level, layout.clock), len(levels) - 1):
        attr = "name" if index in layout.named else None
        date += [Token("level", levels[index], attr), " "]
    years: list[list[Piece]] = (
        [[Token("year")]]
        if not calendar.eras
        else [[Token("era_year"), " ", Token("era")], [Token("era"), " ", Token("era_year")]]
    )
    clock: list[Piece] = []
    if level < layout.clock:
        span = range(layout.clock - 1, level - 1, -1)
        if len(span) == 1:
            unit = calendar.definition.levels[level]
            clock = [", ", Token("level", unit.id), " " + (unit.abbr or unit.label)]
        else:
            for i, index in enumerate(span):
                clock += ([":"] if i else [", "]) + [Token("level", levels[index], modifier="pad2")]
    return [date + year + clock for year in years]


def _patterns(calendar: CompiledCalendar) -> Iterator[tuple[str, list[Piece]]]:
    """(precision, pieces) in the order they are tried: finest precision first, the regular
    pattern then the intercalary one."""
    layout = layout_of(calendar)
    custom = calendar.definition.formats
    for level in range(-1, len(calendar.levels)):
        index = max(level, 0)
        level_id = calendar.levels[index]
        regular = None if custom is None else (custom.model_extra or {}).get(level_id)
        intercalary = None if custom is None else custom.intercalary.get(level_id)
        candidates: list[list[Piece]] = []
        for pattern in (regular, intercalary):
            for pieces in (
                [formats.parse(pattern)] if pattern is not None else _default(calendar, index)
            ):
                if pieces not in candidates:
                    candidates.append(pieces)
        for pieces in candidates:
            has_base = any(isinstance(p, Token) and p.kind == "base" for p in pieces)
            if level >= 0:
                yield level_id, pieces
            elif has_base:
                yield BASE, pieces  # the level-0 pattern shows the base itself
            elif layout.base_suffix:
                yield BASE, [*pieces, " + ", Token("base"), " " + calendar.context.base_unit.abbr]


# --- matching ------------------------------------------------------------------------------------


def _number_at(text: str, pos: int, group: str) -> list[int]:
    """End positions of the number starting at ``pos`` (grouped, then plain), longest first."""
    i = pos
    if i < len(text) and text[i] in ("-", _MINUS):
        i += 1
    digits = i
    while digits < len(text) and _digits(text[digits]):
        digits += 1
    if digits == i:
        return []
    ends = [digits]
    if group and digits - i <= 3:  # noqa: PLR2004 (a digit group has three digits)
        grouped = digits
        while text.startswith(group, grouped) and _three_digits(text, grouped + len(group)):
            grouped += len(group) + 3
        if grouped > digits:
            ends.insert(0, grouped)
    return ends


def _three_digits(text: str, pos: int) -> bool:
    chunk = text[pos : pos + 3]
    after = text[pos + 3 : pos + 4]
    return len(chunk) == 3 and _digits(chunk) and not _digits(after)  # noqa: PLR2004


def _number_value(text: str, group: str) -> str:
    raw = text.replace(group, "") if group else text
    return str(int(raw.replace(_MINUS, "-")))


class _Matcher:
    def __init__(self, calendar: CompiledCalendar, text: str) -> None:
        self.calendar = calendar
        self.text = text
        self.lower = text.lower()
        display = layout_of(calendar).display
        self.group = display.digit_group
        self.names = _level_names(calendar)
        self.eras = [
            (era.id, [era.abbr.lower(), era.name.lower()]) for era in calendar.eras
        ]  # fmt: skip
        self.cycles = _cycle_names(calendar)
        self.phases = {
            overlay.id: sorted({phase.name.lower() for phase in overlay.phases}, key=len)[::-1]
            for overlay in calendar.definition.overlays
        }

    def _prefixes(self, pos: int, words: Sequence[str]) -> list[int]:
        return [pos + len(word) for word in words if word and self.lower.startswith(word, pos)]

    def numbers(self, pos: int, ordinal: bool) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        for end in _number_at(self.text, pos, self.group):
            value = _number_value(self.text[pos:end], self.group)
            if ordinal:
                found += [(value, e) for e in self._prefixes(end, _ORDINAL)]
            found.append((value, end))
        return found

    def alternatives(self, token: Token, pos: int) -> list[tuple[Capture | None, int]]:
        """What ``token`` can match at ``pos`` (a capture and the end), in the order tried."""
        kind = token.kind
        if kind in ("year", "era_year", "base"):
            return [((kind, None, v), e) for v, e in self.numbers(pos, token.modifier == "ordinal")]
        if kind == "level":
            level = token.id or ""
            found: list[tuple[Capture | None, int]] = []
            if token.attr is not None:
                words = self.names.get(level, [])
                found += [
                    (("level", level, slot), pos + len(word))
                    for word, slot in words
                    if self.lower.startswith(word, pos)
                ]
            ordinal = token.modifier == "ordinal"
            found += [(("level", level, v), e) for v, e in self.numbers(pos, ordinal)]
            return [*found, (None, pos)]
        if kind == "era":
            found = [
                (("era", era_id, era_id), end)
                for era_id, words in self.eras
                for end in self._prefixes(pos, words)
            ]
            found.sort(key=lambda item: -item[1])
            return [*found, (None, pos)]
        if kind == "cycle":
            cycle = token.id or ""
            found = [
                (("cycle", cycle, str(index)), pos + len(word))
                for word, index in self.cycles.get(cycle, [])
                if self.lower.startswith(word, pos)
            ]
            return [*found, (None, pos)]
        assert kind == "overlay"
        overlay = token.id or ""
        if token.attr == "fraction":
            chunk = self.text[pos : pos + 4]
            ok = len(chunk) == 4 and chunk.startswith("0.") and _digits(chunk[2:])  # noqa: PLR2004
            fraction = [(("overlay.fraction", overlay, chunk), pos + 4)] if ok else []
            return [*fraction, (None, pos)]
        names = [
            (("overlay", overlay, name), end)
            for name in self.phases.get(overlay, [])
            for end in self._prefixes(pos, [name])
        ]
        return [*names, (None, pos)]

    def matches(self, elements: Sequence[_Element]) -> Iterator[list[Capture]]:
        """Every full match of ``elements`` (depth first, alternatives in order)."""
        stack: list[tuple[int, int, list[Capture]]] = [(0, 0, [])]
        while stack:
            index, pos, captures = stack.pop()
            if index == len(elements):
                if pos == len(self.text):
                    yield captures
                continue
            element = elements[index]
            if isinstance(element, _Space):
                ends = [pos + 1, pos] if self.text.startswith(" ", pos) else [pos]
                stack += [(index + 1, end, captures) for end in reversed(ends)]
            elif isinstance(element, str):
                if self.lower.startswith(element, pos):
                    stack.append((index + 1, pos + len(element), captures))
            else:
                options = self.alternatives(element, pos)
                for capture, end in reversed(options):
                    stack.append(
                        (index + 1, end, captures if capture is None else [*captures, capture])
                    )


def _level_names(calendar: CompiledCalendar) -> dict[str, list[tuple[str, str]]]:
    """Per level: (lowercased word, slot id) for every slot name, abbreviation and id, longest
    words first."""
    found: dict[str, dict[str, str]] = {}
    for regime in calendar.regimes:
        for template in regime.templates.values():
            if template.level == 0:
                continue
            level = calendar.levels[template.level - 1]
            for segment in template.segments:
                if segment.slot_id is None:
                    continue
                words = found.setdefault(level, {})
                for word in (segment.name, segment.abbr, segment.slot_id):
                    if word:
                        words.setdefault(word.lower(), segment.slot_id)
    return {
        level: sorted(words.items(), key=lambda item: -len(item[0]))
        for level, words in found.items()
    }


def _cycle_names(calendar: CompiledCalendar) -> dict[str, list[tuple[str, int]]]:
    """Per cycle: (lowercased name, abbreviation or number, index), longest first."""
    found: dict[str, dict[str, int]] = {}
    for regime in calendar.regimes:
        for cycle in regime.cycles:
            words = found.setdefault(cycle.id, {})
            for index in range(cycle.length):
                for word in (
                    cycle.names[index] if cycle.names else None,
                    cycle.abbrs[index] if cycle.abbrs else None,
                    str(index + cycle.number_start),
                ):
                    if word:
                        words.setdefault(word.lower(), index)
    return {
        cycle: sorted(words.items(), key=lambda item: -len(item[0]))
        for cycle, words in found.items()
    }


# --- dates ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Values:
    """A match's values (``None``: not matched); ``ok`` false when two of them disagree."""

    levels: dict[str, list[str]]
    """Every value matched per level (a slot id and a number may name the same unit)."""
    year: str | None = None
    era_year: str | None = None
    era: str | None = None
    base: int | None = None
    ok: bool = True

    def set(self, member: str, value: str) -> None:
        current = getattr(self, member)
        if current is not None and current != value:
            self.ok = False
        setattr(self, member, value)


def _values(
    calendar: CompiledCalendar, captures: Sequence[Capture]
) -> tuple[_Values, list[Capture]]:
    """The fields a match names, and its cycle and overlay values to check."""
    found = _Values({})
    checks: list[Capture] = []
    top = calendar.levels[-1]
    for kind, ident, value in captures:
        if kind == "level" and ident == top:
            found.set("year", value)
        elif kind == "level":
            assert ident is not None
            found.levels.setdefault(ident, []).append(value)
        elif kind in ("year", "era_year", "era"):
            found.set(kind, value)
        elif kind == "base":
            found.base = int(value)
        else:
            checks.append((kind, ident, value))
    return found, checks


def _year(found: _Values) -> tuple[str, str | None] | None:
    """(year, era): era-relative with a matched era, else astronomical ("15 March 2024")."""
    if found.year is not None:
        return found.year, None  # an era token alongside only had to match
    if found.era_year is None:
        return None
    return found.era_year, found.era


def _date(
    calendar: CompiledCalendar, precision: str, captures: Sequence[Capture], approximate: bool
) -> ParsedDate | None:
    """The valid date of a match, or ``None`` (§10.1)."""
    levels = calendar.levels
    found, checks = _values(calendar, captures)
    year = _year(found) if found.ok else None
    if year is None or (precision == BASE and found.base is None):
        return None
    index = 0 if precision == BASE else levels.index(precision)
    fields = {levels[-1]: year[0]}
    era = year[1]
    try:
        for level in range(len(levels) - 2, index - 1, -1):
            matched = found.levels.get(levels[level], [])
            # A slot id first: a number names a regular unit only.
            value = next((v for v in matched if not is_number(v)), next(iter(matched), None))
            if value is None:
                value = _only_child(calendar, fields, levels[level + 1], era)
            if value is None:
                return None
            fields[levels[level]] = value
        t = from_fields(calendar, fields, levels[index], era=era, overflow="reject")
    except DateError:
        return None
    if precision == BASE:
        assert found.base is not None
        unit = descend(calendar, active_regime(calendar, t), t, 0).template.length
        if not 0 <= found.base < unit:
            return None
        t += found.base
    if not _consistent(calendar, t, found.levels) or (
        checks and not _agrees(calendar, t, index, checks)
    ):
        return None
    return ParsedDate(fields, era, precision, approximate, t)


def _only_child(
    calendar: CompiledCalendar, fields: dict[str, str], parent: str, era: str | None
) -> str | None:
    """The child of the ``parent`` unit ``fields`` name when it is its only child."""
    t = from_fields(calendar, fields, parent, era=era, overflow="reject")
    level = calendar.levels.index(parent)
    template = descend(calendar, active_regime(calendar, t), t, level).template
    if template.total_count != 1:
        return None
    segment = template.segments[0]
    if segment.slot_id is not None:
        return segment.slot_id
    return str(calendar.numbering_starts[level - 1])


def _consistent(calendar: CompiledCalendar, t: int, levels: dict[str, list[str]]) -> bool:
    """Every value matched for a level names the date's unit (its number or its slot id)."""
    found = to_fields(calendar, t).levels
    for level, values in levels.items():
        unit = found[level]
        for value in values:
            same = (
                unit.n is not None and int(value) == unit.n
                if is_number(value)
                else (unit.slot_id == value)
            )
            if not same:
                return False
    return True


def _agrees(calendar: CompiledCalendar, t: int, level: int, checks: Sequence[Capture]) -> bool:
    """The matched values of cycles at or above the precision ``level`` are the date's (finer
    cycles and overlays change within the unit: they only have to match)."""
    found = to_fields(calendar, t)
    regime = active_regime(calendar, t)
    for kind, ident, value in checks:
        cycle = next((c for c in regime.cycles if c.id == ident), None)
        if kind != "cycle" or cycle is None or cycle.level < level:
            continue
        current = found.cycles.get(ident or "")
        if current is None or current.index != int(value):
            return False
    return True


def parse_date(calendar: CompiledCalendar, text: str) -> ParsedDate:
    """§10.1 ``parse``: the date ``text`` writes in this calendar's formats; ``invalid_date``
    when none matches."""
    normalized = _SPACE.sub(" ", text).strip()
    approximate = False
    circa = _SPACE.sub(" ", layout_of(calendar).display.circa).strip().lower()
    if circa and normalized.lower().startswith(circa):
        approximate = True
        normalized = normalized[len(circa) :].strip()
    matcher = _Matcher(calendar, normalized)
    for precision, pieces in _patterns(calendar):
        for count, captures in enumerate(matcher.matches(_elements(pieces))):
            if count >= MATCH_LIMIT:
                break
            date = _date(calendar, precision, captures, approximate)
            if date is not None:
                return date
    raise DateError("invalid_date", f"no date of this calendar reads {text!r}")
