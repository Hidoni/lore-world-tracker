"""Moment ⇄ fields conversions (``chronology-engine.md`` §5.3, §5.5-§5.7, §6).

Every step jumps with prefix sums and binary searches: the cost depends on the number of levels
and the logarithm of template widths, never on the year number (years may have 1000 digits).
Cycles, eras and overlays come from their modules (``cycles``, ``eras``, ``overlays``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from lore.chronology.calendar.compiled import (
    Child,
    CompiledCalendar,
    CompiledRegime,
    CompiledTemplate,
    DateError,
    active_regime,
    is_number,
)
from lore.chronology.calendar.cycles import CycleValue, cycle_values
from lore.chronology.calendar.eras import EraValue, era_of, find_era
from lore.chronology.calendar.overlays import OverlayValue, overlay_values

type Overflow = Literal["reject", "constrain"]


@dataclass(frozen=True, slots=True)
class UnitValue:
    """One level of a date: its regular number and, for a named slot, the slot's identity."""

    n: int | None
    """Regular number; ``None`` for an intercalary unit."""
    slot_id: str | None = None
    name: str | None = None
    intercalary: bool = False

    def as_json(self) -> dict[str, str | bool | None]:
        number = None if self.n is None else str(self.n)
        if self.slot_id is None:
            return {"n": number}
        return {"n": number, "id": self.slot_id, "name": self.name, "intercalary": self.intercalary}


@dataclass(frozen=True, slots=True)
class DateFields:
    """The result of :func:`to_fields` (chronology-engine §5.6)."""

    regime: str
    levels: Mapping[str, UnitValue]
    """Every level, top level first."""
    base: int
    """Base-unit remainder inside the level-0 unit."""
    cycles: Mapping[str, CycleValue | None]
    """Every cycle of the regime: its value, or ``None`` where the unit is excluded."""
    era: EraValue | None = None
    """The era and era-relative year (``None`` for a calendar without eras)."""
    overlays: Mapping[str, OverlayValue] = field(default_factory=dict)
    """Every overlay's phase and phase name."""

    def as_json(self) -> dict[str, object]:
        return {
            "regime": self.regime,
            "levels": {level: value.as_json() for level, value in self.levels.items()},
            "base": str(self.base),
            "era": None if self.era is None else self.era.as_json(),
            "cycles": {
                cycle: None if value is None else value.as_json()
                for cycle, value in self.cycles.items()
            },
            "overlays": {key: value.as_json() for key, value in self.overlays.items()},
        }


# --- regimes -------------------------------------------------------------------------------------


def _regime_by_id(calendar: CompiledCalendar, regime: str) -> CompiledRegime:
    found = next((r for r in calendar.regimes if r.id == regime), None)
    if found is None:
        raise DateError("invalid_date", f"unknown regime {regime!r}")
    return found


def _level_index(calendar: CompiledCalendar, level: str) -> int:
    if level not in calendar.levels:
        raise DateError("invalid_date", f"unknown level {level!r}", level)
    return calendar.levels.index(level)


def _regime_end(calendar: CompiledCalendar, regime: CompiledRegime) -> int | None:
    later = [r.starts_at for r in calendar.regimes[regime.index + 1 :] if r.starts_at is not None]
    return min(later, default=None)


# --- to_fields -----------------------------------------------------------------------------------


def to_fields(calendar: CompiledCalendar, t: int) -> DateFields:
    """The date of moment ``t``: every level from the top down, plus the base remainder."""
    regime = active_regime(calendar, t)
    rel = t - regime.epoch
    year = regime.year_of_rel(rel)
    offset = rel - regime.rel_start(year)
    template = regime.year_template(year)
    levels = calendar.levels
    values: dict[str, UnitValue] = {levels[-1]: UnitValue(year)}
    for level in range(len(levels) - 2, -1, -1):
        child = template.child_at(offset)
        offset -= child.offset
        values[levels[level]] = _unit_value(child, calendar.numbering_starts[level])
        assert child.template is not None  # children of level >= 1 templates are templates
        template = regime.templates[child.template]
    cycles = cycle_values(len(levels) - 1, regime, t)
    era = era_of(calendar, t)
    return DateFields(regime.id, values, offset, cycles, era, overlay_values(calendar, t))


def _unit_value(child: Child, numbering_start: int) -> UnitValue:
    regular = child.regular_index
    number = None if regular is None else regular + numbering_start
    segment = child.segment
    if segment.slot_id is None:
        return UnitValue(number)
    return UnitValue(number, segment.slot_id, segment.name, segment.intercalary)


# --- from_fields ---------------------------------------------------------------------------------


def from_fields(
    calendar: CompiledCalendar,
    fields: Mapping[str, str],
    precision: str,
    *,
    era: str | None = None,
    regime: str | None = None,
    overflow: Overflow = "reject",
) -> int:
    """The start moment of the unit at ``precision`` that ``fields`` denote (§5.7).

    ``fields`` hold every level from the top down to ``precision`` and none below; values are
    regular numbers or slot ids. With ``era``, the year is era-relative, the unit must overlap
    the era, and a unit that starts before the era resolves to the era's start. Raises
    :class:`DateError`.
    """
    _check_shape(calendar, fields, precision)
    if era is not None:
        return _from_era_fields(calendar, fields, precision, era, regime=regime, overflow=overflow)
    if regime is not None:
        return _resolve(calendar, _regime_by_id(calendar, regime), fields, precision, overflow)
    results: list[int] = []
    errors: list[DateError] = []
    for candidate in reversed(calendar.regimes):
        try:
            t = _resolve(calendar, candidate, fields, precision, overflow)
        except DateError as error:
            errors.append(error)
            continue
        end = _regime_end(calendar, candidate)
        after_start = (
            candidate.index == 0 or candidate.starts_at is None or candidate.starts_at <= t
        )
        if after_start and (end is None or t < end):
            results.append(t)
    if len(results) > 1:
        raise DateError("reform_ambiguous", "the date exists in several regimes: pass regime")
    if results:
        return results[0]
    if errors and len(errors) == len(calendar.regimes):
        raise errors[-1]  # invalid in every regime: report regime 0's error
    raise DateError("reform_gap", "no regime has this date at a moment it is in force")


def _from_era_fields(
    calendar: CompiledCalendar,
    fields: Mapping[str, str],
    precision: str,
    era_id: str,
    *,
    regime: str | None,
    overflow: Overflow,
) -> int:
    """§5.7 step 1: an era year becomes ``Y``; the resulting unit must overlap the era."""
    top = calendar.levels[-1]
    era = find_era(calendar, era_id)
    if not is_number(fields[top]):
        raise DateError("invalid_date", "the year must be a number", top)
    astronomical = dict(fields) | {top: str(era.year(int(fields[top])))}
    start = from_fields(calendar, astronomical, precision, regime=regime, overflow=overflow)
    chosen = (
        _regime_by_id(calendar, regime) if regime is not None else active_regime(calendar, start)
    )
    end = start + _unit_length(calendar, chosen, astronomical, precision)
    if (era.start is not None and end <= era.start) or (era.end is not None and start >= era.end):
        raise DateError("invalid_date", f"the date is not in the era {era_id!r}", top)
    # A unit that straddles the era's start resolves to the era's start ("Reiwa 1" → 1 May 2019).
    return start if era.start is None else max(start, era.start)


def _unit_length(
    calendar: CompiledCalendar, regime: CompiledRegime, fields: Mapping[str, str], precision: str
) -> int:
    levels = calendar.levels
    template = regime.year_template(int(fields[levels[-1]]))
    for level in range(len(levels) - 2, levels.index(precision) - 1, -1):
        child = resolve_child(
            calendar, regime, template, level, fields[levels[level]], overflow="constrain"
        )
        assert child.template is not None
        template = regime.templates[child.template]
    return template.length


def _check_shape(calendar: CompiledCalendar, fields: Mapping[str, str], precision: str) -> None:
    levels = calendar.levels
    if precision not in levels:
        raise DateError("invalid_date", f"unknown precision {precision!r}", precision)
    for key in fields:
        if key not in levels:
            raise DateError("invalid_date", f"{key!r} is not a level", key)
    lowest = levels.index(precision)
    for level in range(len(levels) - 1, -1, -1):
        present = levels[level] in fields
        if level >= lowest and not present:
            raise DateError("invalid_date", f"{levels[level]} is missing", levels[level])
        if level < lowest and present:
            raise DateError(
                "invalid_date", f"{levels[level]} is below the precision", levels[level]
            )


def _resolve(
    calendar: CompiledCalendar,
    regime: CompiledRegime,
    fields: Mapping[str, str],
    precision: str,
    overflow: Overflow,
) -> int:
    levels = calendar.levels
    top = levels[-1]
    if not is_number(fields[top]):
        raise DateError("invalid_date", "the year must be a number", top)
    year = int(fields[top])
    t = regime.epoch + regime.rel_start(year)
    template = regime.year_template(year)
    for level in range(len(levels) - 2, levels.index(precision) - 1, -1):
        child = resolve_child(
            calendar, regime, template, level, fields[levels[level]], overflow=overflow
        )
        t += child.offset
        assert child.template is not None  # children of level >= 1 templates are templates
        template = regime.templates[child.template]
    return t


def resolve_child(
    calendar: CompiledCalendar,
    regime: CompiledRegime,
    template: CompiledTemplate,
    level: int,
    value: str,
    *,
    overflow: Overflow,
) -> Child:
    """The child of ``template`` (a ``level + 1`` unit) addressed by ``value``: a regular number
    or a slot id, constrained per §5.7 step 4 when ``overflow`` allows. Raises ``invalid_date``.
    """
    level_id = calendar.levels[level]
    numbering = calendar.numbering_starts[level]
    if is_number(value):
        child = template.child_by_regular_index(int(value) - numbering)
        if child is None and overflow == "constrain" and template.regular_count > 0:
            clamped = min(max(int(value) - numbering, 0), template.regular_count - 1)
            child = template.child_by_regular_index(clamped)
    else:
        child = template.child_by_slot(value)
        if child is None and overflow == "constrain":
            child = _fallback(calendar, regime, template, level, value)
    if child is None:
        raise DateError("invalid_date", f"no {level_id} {value!r} here", level_id)
    return child


def _fallback(
    calendar: CompiledCalendar,
    regime: CompiledRegime,
    template: CompiledTemplate,
    level: int,
    slot_id: str,
) -> Child | None:
    """Constrain an unknown slot id: its regular number in the parent level's default template."""
    default_id = calendar.definition.levels[level + 1].default_template
    default = regime.templates.get(default_id) if default_id is not None else None
    found = default.child_by_slot(slot_id) if default is not None else None
    if found is None or found.regular_index is None or template.regular_count == 0:
        return None
    return template.child_by_regular_index(min(found.regular_index, template.regular_count - 1))


# --- normalization -------------------------------------------------------------------------------


def normalize_fields(
    calendar: CompiledCalendar, fields: Mapping[str, str], *, regime: str | None = None
) -> dict[str, str]:
    """Store-ready fields: named units by slot id, unnamed units by canonical number (§6).

    The fields must form a valid date (``reject`` semantics) down to their finest level.
    """
    levels = calendar.levels
    present = [level for level in levels if level in fields]
    precision = present[0] if present else levels[-1]
    from_fields(calendar, fields, precision, regime=regime)  # validates; picks the regime below
    chosen = _regime_for(calendar, fields, precision, regime)
    year = int(fields[levels[-1]])
    template = chosen.year_template(year)
    normalized = {levels[-1]: str(year)}
    for level in range(len(levels) - 2, levels.index(precision) - 1, -1):
        child = resolve_child(
            calendar, chosen, template, level, fields[levels[level]], overflow="reject"
        )
        slot, regular = child.segment.slot_id, child.regular_index
        if slot is not None:
            normalized[levels[level]] = slot
        else:
            assert regular is not None  # unnamed children are never intercalary
            normalized[levels[level]] = str(regular + calendar.numbering_starts[level])
        assert child.template is not None
        template = chosen.templates[child.template]
    return normalized


def _regime_for(
    calendar: CompiledCalendar, fields: Mapping[str, str], precision: str, regime: str | None
) -> CompiledRegime:
    if regime is not None:
        return next(r for r in calendar.regimes if r.id == regime)
    return active_regime(calendar, from_fields(calendar, fields, precision))


# --- picker options (§6) -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlotOption:
    """A named child: by slot id, with its regular number (``None`` if intercalary)."""

    slot_id: str
    n: int | None
    name: str | None
    intercalary: bool


@dataclass(frozen=True, slots=True)
class RangeOption:
    """Unnamed children numbered ``first … last`` (``None`` bounds: any year)."""

    first: int | None
    last: int | None


type Option = SlotOption | RangeOption


def options(
    calendar: CompiledCalendar, fields: Mapping[str, str], level: str, *, regime: str | None = None
) -> list[Option]:
    """The valid children at ``level`` given the parents ``fields`` (top level down to the
    level just above), in template order: named slots one by one, unnamed runs as ranges.
    """
    index = _level_index(calendar, level)
    top = len(calendar.levels) - 1
    if index == top:
        if fields:
            raise DateError("invalid_date", "the top level has no parents", calendar.levels[top])
        return [RangeOption(None, None)]
    parent = calendar.levels[index + 1]
    start = from_fields(calendar, fields, parent, regime=regime)
    chosen = (
        _regime_by_id(calendar, regime) if regime is not None else active_regime(calendar, start)
    )
    template = _template_at(calendar, chosen, start, index + 1)
    numbering = calendar.numbering_starts[index]
    result: list[Option] = []
    for segment in template.segments:
        if segment.slot_id is not None:
            number = None if segment.intercalary else segment.regular_start + numbering
            result.append(SlotOption(segment.slot_id, number, segment.name, segment.intercalary))
        else:
            first = segment.regular_start + numbering
            result.append(RangeOption(first, first + segment.count - 1))
    return result


def _template_at(
    calendar: CompiledCalendar, regime: CompiledRegime, t: int, level: int
) -> CompiledTemplate:
    """The template of the ``level`` unit starting at ``t``."""
    top = len(calendar.levels) - 1
    rel = t - regime.epoch
    year = regime.year_of_rel(rel)
    template = regime.year_template(year)
    offset = rel - regime.rel_start(year)
    for _ in range(top, level, -1):
        child = template.child_at(offset)
        offset -= child.offset
        assert child.template is not None
        template = regime.templates[child.template]
    return template


def _number(value: int | None) -> str | None:
    return None if value is None else str(value)


def options_json(found: Sequence[Option]) -> list[dict[str, object]]:
    """The conformance-vector form of :func:`options` (README ``options``)."""
    result: list[dict[str, object]] = []
    for option in found:
        if isinstance(option, SlotOption):
            result.append(
                {
                    "kind": "slot",
                    "value": option.slot_id,
                    "n": _number(option.n),
                    "name": option.name,
                    "intercalary": option.intercalary,
                }
            )
        else:
            result.append(
                {"kind": "range", "first": _number(option.first), "last": _number(option.last)}
            )
    return result
