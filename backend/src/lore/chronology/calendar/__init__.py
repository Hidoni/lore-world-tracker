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

__all__ = [
    "CompiledCalendar",
    "CompiledRegime",
    "CompiledTemplate",
    "DateError",
    "DateFields",
    "UnitValue",
    "ValidationError",
    "compile_calendar",
    "from_fields",
    "normalize_fields",
    "to_fields",
    "validate_calendar",
]
