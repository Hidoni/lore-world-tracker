"""Calendars: compilation and (in later issues) conversions (``chronology-engine.md`` §3-§9)."""

from lore.chronology.calendar.compile import ValidationError, compile_calendar, validate_calendar
from lore.chronology.calendar.compiled import CompiledCalendar, CompiledRegime, CompiledTemplate
from lore.chronology.calendar.convert import (
    DateError,
    DateFields,
    UnitValue,
    from_fields,
    normalize_fields,
    to_fields,
)
from lore.chronology.calendar.units import (
    REGULAR,
    Bounds,
    Ordinal,
    RangeOption,
    SlotOption,
    UnitFilter,
    counted_ordinal,
    from_counted_ordinal,
    from_ordinal,
    options,
    ordinal,
    unit_bounds,
)

__all__ = [
    "REGULAR",
    "Bounds",
    "CompiledCalendar",
    "CompiledRegime",
    "CompiledTemplate",
    "DateError",
    "DateFields",
    "Ordinal",
    "RangeOption",
    "SlotOption",
    "UnitFilter",
    "UnitValue",
    "ValidationError",
    "compile_calendar",
    "counted_ordinal",
    "from_counted_ordinal",
    "from_fields",
    "from_ordinal",
    "normalize_fields",
    "options",
    "ordinal",
    "to_fields",
    "unit_bounds",
    "validate_calendar",
]
