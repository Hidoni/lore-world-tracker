"""Calendars: compilation, conversions and unit navigation (``chronology-engine.md`` §3-§9)."""

from lore.chronology.calendar.arithmetic import (
    Difference,
    Duration,
    add,
    diff,
    duration_upper_bound,
    is_uniform,
)
from lore.chronology.calendar.compile import ValidationError, compile_calendar, validate_calendar
from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledRegime,
    CompiledTemplate,
    DateError,
)
from lore.chronology.calendar.convert import (
    DateFields,
    RangeOption,
    SlotOption,
    UnitValue,
    from_fields,
    normalize_fields,
    options,
    to_fields,
)
from lore.chronology.calendar.cycles import CycleValue, cycle_value
from lore.chronology.calendar.overlays import OverlayValue, next_phase_at, overlay_phase
from lore.chronology.calendar.units import (
    REGULAR,
    Bounds,
    Ordinal,
    UnitFilter,
    counted_ordinal,
    from_counted_ordinal,
    from_ordinal,
    ordinal,
    unit_bounds,
)

__all__ = [
    "REGULAR",
    "Bounds",
    "CompiledCalendar",
    "CompiledRegime",
    "CompiledTemplate",
    "CycleValue",
    "DateError",
    "DateFields",
    "Difference",
    "Duration",
    "Ordinal",
    "OverlayValue",
    "RangeOption",
    "SlotOption",
    "UnitFilter",
    "UnitValue",
    "ValidationError",
    "add",
    "compile_calendar",
    "counted_ordinal",
    "cycle_value",
    "diff",
    "duration_upper_bound",
    "from_counted_ordinal",
    "from_fields",
    "from_ordinal",
    "is_uniform",
    "next_phase_at",
    "normalize_fields",
    "options",
    "ordinal",
    "overlay_phase",
    "to_fields",
    "unit_bounds",
    "validate_calendar",
]
