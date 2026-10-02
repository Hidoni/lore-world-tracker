"""Eras: display-level year numbering (``chronology-engine.md`` §3.8, §8).

Eras partition time by their resolved starts. ``forward`` eras count from the year containing
their start (``era_year = Y - Y(start) + first``); ``backward`` eras count down towards the next
era (``era_year = Y_end - Y + first - 1``). Without eras, years are astronomical.
"""

from bisect import bisect_right
from dataclasses import dataclass

from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledEra,
    DateError,
    active_regime,
)


@dataclass(frozen=True, slots=True)
class EraValue:
    id: str
    year: int
    """The era-relative year."""
    abbr: str
    name: str

    def as_json(self) -> dict[str, str]:
        return {"id": self.id, "year": str(self.year), "abbr": self.abbr, "name": self.name}


def era_at(calendar: CompiledCalendar, t: int) -> CompiledEra | None:
    """The era containing ``t`` (``None`` for a calendar without eras)."""
    if not calendar.eras:
        return None
    starts = [era.start for era in calendar.eras[1:] if era.start is not None]  # all set
    return calendar.eras[bisect_right(starts, t)]


def era_of(calendar: CompiledCalendar, t: int) -> EraValue | None:
    """§8 ``era_of``: the era of ``t`` and the era-relative number of ``t``'s year."""
    era = era_at(calendar, t)
    if era is None:
        return None
    year = active_regime(calendar, t).year_of(t)
    return EraValue(era.id, era.era_year(year), era.abbr, era.name)


def find_era(calendar: CompiledCalendar, era_id: str) -> CompiledEra:
    era = next((e for e in calendar.eras if e.id == era_id), None)
    if era is None:
        raise DateError("invalid_date", f"unknown era {era_id!r}", calendar.levels[-1])
    return era
