"""Parallel cycles (chronology-engine.md §3.7, §8); vectors: cases/cycles/."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    from_counted_ordinal,
    to_fields,
    unit_bounds,
    validate_calendar,
)
from lore.chronology.calendar.cycles import cycle_value, regime_cycle_value
from lore.chronology.calendar.units import counted_ordinal, cycle_filter

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
DAY = 86_400


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(document: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


CALENDARS = {
    name: compiled(load(name)) for name in ("gregorian-week", "shire-week", "cycles-showcase")
}
CONTINUOUS = [
    ("gregorian-week", "week"),
    ("shire-week", "week"),
    ("cycles-showcase", "trecena"),
    ("cycles-showcase", "veintena"),
]
moments = st.one_of(st.integers(0, 10**12), st.integers(0, 10**60))


# --- properties ----------------------------------------------------------------------------------


@given(st.sampled_from(CONTINUOUS), moments)
def test_consecutive_counted_units_have_consecutive_indices(case: tuple[str, str], t: int) -> None:
    name, cycle_id = case
    calendar = CALENDARS[name]
    unit_filter = cycle_filter(cycle_id)
    level = "day"
    here = counted_ordinal(calendar, t, level, unit_filter)
    unit = from_counted_ordinal(calendar, level, here.value, unit_filter)
    following = from_counted_ordinal(calendar, level, here.value + 1, unit_filter)
    first = cycle_value(calendar, unit.start, cycle_id)
    second = cycle_value(calendar, following.start, cycle_id)
    assert first is not None
    assert second is not None
    length = next(c.length for c in calendar.regimes[0].cycles if c.id == cycle_id)
    assert second.index == (first.index + 1) % length
    value = cycle_value(calendar, t, cycle_id)
    assert (value is None) is (not here.counted)


@given(moments)
def test_reset_cycle_restarts_with_every_month(t: int) -> None:
    calendar = CALENDARS["cycles-showcase"]
    month = unit_bounds(calendar, t, "month")
    value = cycle_value(calendar, t, "decan")
    in_wayeb = to_fields(calendar, t).levels["month"].slot_id == "wayeb"
    if in_wayeb:
        assert value is None
        return
    assert value is not None
    assert value.index == ((t - month.start) // 1) % 10  # one-day units: days since the month start
    first = cycle_value(calendar, month.start, "decan")
    assert first is not None
    assert first.index == 0


@given(st.integers(-3000, 3000))
def test_shire_years_start_on_sterday(year: int) -> None:
    calendar = CALENDARS["shire-week"]
    value = cycle_value(calendar, calendar.regimes[0].year_start(year), "week")
    assert value is not None
    assert value.name == "Sterday"


# --- regimes -------------------------------------------------------------------------------------


def reform(start: dict[str, Any], resolved: str | None) -> CompiledCalendar:
    """gregorian-week plus a regime from noon on 1 January 2000 whose week continues regime 0's.

    The new regime's 1 January 2000 starts at the switch, so it repeats half a day.
    """
    document = copy.deepcopy(load("gregorian-week"))
    definition, context = document["definition"], document["context"]
    second = copy.deepcopy(definition["regimes"][0])
    second["id"] = "reformed"
    second["starts_at"] = start
    switch = 10**14 + 12 * 3600
    second["alignment"]["at"] = {
        "anchor": {"kind": "absolute", "t": str(switch)},
        "precision": "base",
    }
    second["cycles"] = [
        {
            "id": "week",
            "level": "day",
            "length": 7,
            "names": definition["regimes"][0]["cycles"][0]["names"],
            "number_start": 1,
            "continue_from_previous_regime": True,
        }
    ]
    definition["regimes"].append(second)
    context["resolved"]["/regimes/1/alignment/at"] = str(switch)
    if resolved is not None:
        context["resolved"]["/regimes/1/starts_at"] = resolved
    return compiled(document)


def test_week_continues_across_a_regime_start() -> None:
    switch = 10**14 + 12 * 3600
    calendar = reform(
        {"anchor": {"kind": "absolute", "t": str(switch)}, "precision": "base"}, str(switch)
    )
    before = cycle_value(calendar, switch - 1, "week")
    after = cycle_value(calendar, switch, "week")
    assert before is not None
    assert after is not None
    assert (before.name, after.name) == ("Saturday", "Sunday")  # the repeated 1 January is a Sunday
    later = cycle_value(calendar, switch + 6 * DAY, "week")
    assert later is not None
    assert later.name == "Saturday"


def test_continuation_from_a_local_start_waits_for_local_resolution() -> None:
    calendar = reform(
        {"anchor": {"kind": "local", "fields": {"year": "2100"}}, "precision": "year"}, None
    )
    regime = calendar.regimes[1]
    assert regime.cycles[0].anchor_ordinal is None
    with pytest.raises(DateError) as error:
        regime_cycle_value(len(calendar.levels) - 1, regime, regime.cycles[0], 10**14)
    assert error.value.code == "unknown_cycle"
    assert cycle_value(calendar, 10**16, "week") is not None  # regime 0 still applies


def test_unknown_cycle() -> None:
    with pytest.raises(DateError) as error:
        cycle_value(CALENDARS["gregorian-week"], 0, "fortnight")
    assert error.value.code == "unknown_cycle"
