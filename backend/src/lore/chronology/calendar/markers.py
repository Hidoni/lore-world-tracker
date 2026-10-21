"""Annual markers: named parts of every year, e.g. seasons (``chronology-engine.md`` §3.12, §8).

A marker's range in year ``Y`` is ``[a, b)``: ``a`` is the start of its ``from`` fields in ``Y``,
``b`` the start of its ``to`` fields in ``Y``, or in ``Y + 1`` when that is not after ``a`` (the
range wraps into the next year). Both sides are resolved with ``from_fields(…, overflow =
"constrain")``; a year where either can't be resolved has no range. Markers never affect the
date structure.
"""

from collections.abc import Mapping

from lore.chronology.calendar.compiled import CompiledCalendar, DateError, active_regime
from lore.chronology.calendar.convert import from_fields
from lore.chronology.schema import Marker


def marker(calendar: CompiledCalendar, marker_id: str) -> Marker:
    """The marker with ``marker_id``; ``unknown_marker`` if the calendar has none."""
    for item in calendar.definition.markers:
        if item.id == marker_id:
            return item
    raise DateError("unknown_marker", f"no marker {marker_id!r}")


def _side(
    calendar: CompiledCalendar, fields: Mapping[str, str], year: int, regime: str | None
) -> int | None:
    levels = calendar.levels
    precision = min(fields, key=levels.index)
    try:
        return from_fields(
            calendar,
            {levels[-1]: str(year), **fields},
            precision,
            regime=regime,
            overflow="constrain",
        )
    except DateError:
        return None


def range_of(
    calendar: CompiledCalendar, item: Marker, year: int, regime: str | None = None
) -> tuple[int, int] | None:
    """``[a, b)`` of ``item`` in ``year``, or ``None`` when that year has none. With ``regime``,
    the year is reckoned in that regime (recurrence rules: the series start's, extended
    proleptically); else ``from_fields`` picks the regime in force."""
    start = _side(calendar, item.from_, year, regime)
    if start is None:
        return None
    end = _side(calendar, item.to, year, regime)
    if end is None or end <= start:
        end = _side(calendar, item.to, year + 1, regime)
    if end is None or end <= start:
        return None
    return start, end


def marker_range(calendar: CompiledCalendar, marker_id: str, year: int) -> tuple[int, int] | None:
    """§8 ``marker_range``: the marker's range in ``year`` (``None``: none that year)."""
    return range_of(calendar, marker(calendar, marker_id), year)


def markers_at(calendar: CompiledCalendar, t: int) -> list[str]:
    """§8 ``markers_at``: the ids of the markers whose range contains ``t``, in definition order
    (the range of ``t``'s year, or the previous year's running into it), reckoned in the regime
    in force at ``t``."""
    regime = active_regime(calendar, t)
    year = regime.year_of_rel(t - regime.epoch)
    found: list[str] = []
    for item in calendar.definition.markers:
        for candidate in (year, year - 1):
            bounds = range_of(calendar, item, candidate, regime.id)
            if bounds is not None and bounds[0] <= t < bounds[1]:
                found.append(item.id)
                break
    return found
