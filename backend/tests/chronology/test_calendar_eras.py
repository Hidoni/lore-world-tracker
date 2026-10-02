"""Eras, regimes and local anchors (chronology-engine.md §3.3, §3.8, §3.10, §7)."""

import copy
import json
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import CompiledCalendar, from_fields, to_fields, validate_calendar
from lore.chronology.calendar.compiled import active_regime
from lore.chronology.calendar.eras import era_at, era_of

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(document: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


REFORM_CALENDAR = compiled(load("julian-gregorian"))
JAPANESE = compiled(load("japanese-eras"))
_START = REFORM_CALENDAR.regimes[1].starts_at
assert _START is not None
REFORM: int = _START
moments = st.one_of(
    st.integers(REFORM - 10**11, REFORM + 10**11),
    st.integers(REFORM - 10**6, REFORM + 10**6),
    st.integers(0, 10**20),
)


def as_input(calendar: CompiledCalendar, t: int) -> dict[str, str]:
    date = to_fields(calendar, t)
    return {level: value.slot_id or str(value.n) for level, value in date.levels.items()}


@given(moments)
def test_to_fields_uses_the_regime_active_at_t(t: int) -> None:
    expected = "gregorian" if t >= REFORM else "julian"
    assert to_fields(REFORM_CALENDAR, t).regime == expected
    assert active_regime(REFORM_CALENDAR, t).id == expected


@given(moments)
def test_dates_in_force_round_trip_without_naming_the_regime(t: int) -> None:
    """Regimes partition time: every moment's date resolves back to it, with or without the
    regime, so boundaries leave no gap or overlap in absolute time."""
    date = to_fields(REFORM_CALENDAR, t)
    fields = as_input(REFORM_CALENDAR, t)
    assert from_fields(REFORM_CALENDAR, fields, "second") == t
    assert from_fields(REFORM_CALENDAR, fields, "second", regime=date.regime) == t


def test_reform_boundary_is_continuous() -> None:
    before = to_fields(REFORM_CALENDAR, REFORM - 1)
    after = to_fields(REFORM_CALENDAR, REFORM)
    assert (before.regime, before.levels["day"].n) == ("julian", 4)
    assert (after.regime, after.levels["day"].n) == ("gregorian", 15)


@given(st.integers(-(10**6), 10**6), st.sampled_from(["julian-gregorian", "japanese-eras"]))
def test_era_years_invert(year: int, name: str) -> None:
    calendar = REFORM_CALENDAR if name == "julian-gregorian" else JAPANESE
    for era in calendar.eras:
        assert era.year(era.era_year(year)) == year


@given(moments)
def test_era_of_matches_the_era_bounds(t: int) -> None:
    era = era_at(REFORM_CALENDAR, t)
    assert era is not None
    assert era.start is None or era.start <= t
    assert era.end is None or t < era.end
    value = era_of(REFORM_CALENDAR, t)
    assert value is not None
    year = active_regime(REFORM_CALENDAR, t).year_of(t)
    assert int(value.year) == (year if value.id == "ad" else 1 - year)


def test_calendar_without_eras() -> None:
    calendar = compiled(load("gregorian-seconds"))
    assert era_at(calendar, 0) is None
    assert era_of(calendar, 0) is None


def test_overlay_epochs_are_resolved() -> None:
    document = copy.deepcopy(load("julian-gregorian"))
    local = {
        "anchor": {"kind": "local", "fields": {"year": "2000", "month": "jan", "day": "6"}},
        "precision": "day",
    }
    phases = [{"name": "New", "from": {"num": "0", "den": "1"}}]
    period = {"num": "2551443", "den": "1"}
    document["definition"]["overlays"] = [
        {"id": "moon", "name": "Moon", "period": period, "epoch": local, "phases": phases},
        {
            "id": "other",
            "name": "Other",
            "period": period,
            "epoch": {"anchor": {"kind": "absolute", "t": "42"}, "precision": "base"},
            "phases": phases,
        },
    ]
    document["context"]["resolved"]["/overlays/1/epoch"] = "42"
    calendar = compiled(document)
    jan_6 = from_fields(calendar, {"year": "2000", "month": "jan", "day": "6"}, "day")
    assert calendar.overlay_epochs == (jan_6, 42)
