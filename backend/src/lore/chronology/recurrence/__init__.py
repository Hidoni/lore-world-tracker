"""Recurrence: occurrences of recurring events, computed on demand (``recurrence.md``).

Occurrences are never stored in bulk (ADR-0009). Every function jumps straight to the periods it
needs with ordinal arithmetic; nothing iterates from the series start.
"""

from lore.chronology.recurrence.engine import (
    Expansion,
    Occurrence,
    RecurrenceContext,
    RecurrenceError,
    SeriesBounds,
    expand,
    next_occurrences,
    occurrence,
    series_bounds,
    validate_rule,
)

__all__ = [
    "Expansion",
    "Occurrence",
    "RecurrenceContext",
    "RecurrenceError",
    "SeriesBounds",
    "expand",
    "next_occurrences",
    "occurrence",
    "series_bounds",
    "validate_rule",
]
