"""Parallel cycles: weeks, market weeks, Tzolkin-style combinations (``chronology-engine.md``
§3.7, §8).

A cycle counts the units of its level that it doesn't exclude (``cycle_excluded`` on the unit or
an ancestor, :func:`~lore.chronology.calendar.units.cycle_filter`). Continuous cycles index units
by their counted ordinal relative to the anchor unit; reset cycles restart in every unit of the
reset level. Excluded units have no value.
"""

from dataclasses import dataclass

from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledCycle,
    CompiledRegime,
    DateError,
    active_regime,
)
from lore.chronology.calendar.units import REGULAR, counted_position, cycle_filter


@dataclass(frozen=True, slots=True)
class CycleValue:
    index: int
    """``0 ≤ index < length``."""
    name: str | None
    """The name at ``index``, if the cycle has names."""
    n: int
    """Display number: ``index + number_start``."""

    def as_json(self) -> dict[str, object]:
        return {"index": self.index, "name": self.name, "n": self.n}


def regime_cycle_value(
    top: int, regime: CompiledRegime, cycle: CompiledCycle, t: int
) -> CycleValue | None:
    """The value of ``cycle`` for the unit containing ``t`` in ``regime`` (``None``: excluded)."""
    unit_filter = cycle_filter(cycle.id)
    before, counted, _ = counted_position(top, regime, t, cycle.level, unit_filter)
    if not counted:
        return None
    if cycle.reset is None:
        if cycle.anchor_ordinal is None:
            raise DateError("unknown_cycle", f"cycle {cycle.id!r} continues a local regime start")
        index = (before - cycle.anchor_ordinal + cycle.anchor_index) % cycle.length
    else:
        _, _, reset_start = counted_position(top, regime, t, cycle.reset, REGULAR)
        first, _, _ = counted_position(top, regime, reset_start, cycle.level, unit_filter)
        index = (before - first + cycle.anchor_index) % cycle.length
    name = cycle.names[index] if cycle.names is not None else None
    return CycleValue(index, name, index + cycle.number_start)


def cycle_values(top: int, regime: CompiledRegime, t: int) -> dict[str, CycleValue | None]:
    """Every cycle of ``regime`` at ``t`` (the ``cycles`` member of ``to_fields``)."""
    return {cycle.id: regime_cycle_value(top, regime, cycle, t) for cycle in regime.cycles}


def cycle_value(calendar: CompiledCalendar, t: int, cycle_id: str) -> CycleValue | None:
    """§8 ``cycle_value``: the cycle's value at ``t`` in the regime active at ``t``."""
    regime = active_regime(calendar, t)
    cycle = next((c for c in regime.cycles if c.id == cycle_id), None)
    if cycle is None:
        raise DateError("unknown_cycle", f"no cycle {cycle_id!r} in regime {regime.id!r}")
    return regime_cycle_value(len(calendar.levels) - 1, regime, cycle, t)
