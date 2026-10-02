"""Recurrence: occurrences of recurring events, computed on demand (``recurrence.md``).

Occurrences are never stored in bulk (ADR-0009). Every function jumps straight to the periods it
needs with ordinal arithmetic; nothing iterates from the series start.
"""

from lore.chronology.recurrence.engine import (
    Expansion,
    SeriesBounds,
    count_in_window,
    expand,
    next_occurrences,
    occurrence,
    occurrence_at,
    occurrence_number,
    series_bounds,
    validate_rule,
)
from lore.chronology.recurrence.plan import Occurrence, RecurrenceContext, RecurrenceError

__all__ = [
    "Expansion",
    "Occurrence",
    "RecurrenceContext",
    "RecurrenceError",
    "SeriesBounds",
    "count_in_window",
    "expand",
    "next_occurrences",
    "occurrence",
    "occurrence_at",
    "occurrence_number",
    "series_bounds",
    "validate_rule",
]
