"""Resolution status of a time slot (``time-model.md`` §6)."""

from enum import StrEnum


class TimeStatus(StrEnum):
    """How a slot's last resolution went. A slot that isn't ``ok`` keeps its last good ``*_t``
    (reads never break) and raises a structural finding."""

    OK = "ok"
    TRASHED_REF = "trashed_ref"  # the target is in the trash; still resolves
    UNRESOLVED_REF = "unresolved_ref"  # the target was purged
    CYCLE = "cycle"
    INVALID_DATE = "invalid_date"  # the fields no longer form a valid date
    OUT_OF_BOUNDS = "out_of_bounds"  # outside [0, D]
    CALENDAR_ERROR = "calendar_error"  # the calendar definition is invalid
