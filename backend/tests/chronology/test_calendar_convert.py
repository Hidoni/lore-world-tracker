"""Moment ⇄ fields conversions (chronology-engine.md §5.5-§5.7, §6); vectors: cases/conversions/."""

import copy
import json
import random
import time
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import CompiledCalendar, DateError, validate_calendar
from lore.chronology.calendar.convert import (
    DateFields,
    from_fields,
    normalize_fields,
    to_fields,
)

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
    name: compiled(load(name))
    for name in ("gregorian-seconds", "alternating-years", "intercalary-exceptions")
}
GREGORIAN = CALENDARS["gregorian-seconds"]
names = st.sampled_from(sorted(CALENDARS))
moments = st.one_of(
    st.integers(0, 10**15),
    st.integers(435 * 10**15 - 10**12, 435 * 10**15 + 10**12),
    st.integers(0, 10**110),
)


def as_input(date: DateFields) -> dict[str, str]:
    """Fields as a user would store them: slot ids for named units, numbers otherwise."""
    return {level: value.slot_id or str(value.n) for level, value in date.levels.items()}


# --- properties ----------------------------------------------------------------------------------


@given(names, moments)
def test_round_trip_to_the_level0_unit(name: str, t: int) -> None:
    calendar = CALENDARS[name]
    date = to_fields(calendar, t)
    assert from_fields(calendar, as_input(date), calendar.levels[0]) == t - date.base
    assert 0 <= date.base < calendar.regimes[0].templates[calendar.levels[0]].length


@given(names, st.one_of(st.integers(-3000, 3000), st.integers(-(10**300), 10**300)))
def test_year_starts_strictly_increase(name: str, year: int) -> None:
    regime = CALENDARS[name].regimes[0]
    assert regime.year_start(year + 1) > regime.year_start(year)


@given(names, moments, st.data())
def test_fields_round_trip(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    levels = calendar.levels
    date = to_fields(calendar, t)
    precision = data.draw(st.sampled_from(levels))
    by_number = data.draw(st.booleans())
    kept = levels[levels.index(precision) :]
    fields = {
        level: (
            str(value.n) if by_number and value.n is not None else value.slot_id or str(value.n)
        )
        for level, value in date.levels.items()
        if level in kept
    }
    start = from_fields(calendar, fields, precision)
    back = to_fields(calendar, start)
    for level in kept:
        value = back.levels[level]
        assert fields[level] in (str(value.n), value.slot_id)
    assert back.base == 0
    for index in range(levels.index(precision)):  # finer levels: the first unit
        assert back.levels[levels[index]].n in (calendar.numbering_starts[index], None)
    assert normalize_fields(calendar, fields) == {
        level: value.slot_id or str(value.n)
        for level, value in date.levels.items()
        if level in kept
    }


# --- examples ------------------------------------------------------------------------------------


def test_as_json_shape() -> None:
    date = to_fields(CALENDARS["intercalary-exceptions"], 1_000_000 + 30 * 24 + 5)
    assert date.as_json() == {
        "regime": "shire",
        "levels": {
            "year": {"n": "1"},
            "month": {"n": None, "id": "yule", "name": "Yule", "intercalary": True},
            "day": {"n": "1"},
        },
        "base": "5",
        "era": None,
        "cycles": {},
        "overlays": {},
    }


def test_errors_name_the_offending_level() -> None:
    cases = [
        ({"year": "2023", "month": "feb", "day": "29"}, "day", "day"),
        ({"year": "2023", "month": "frostfall"}, "month", "month"),
        ({"year": "2023", "day": "1"}, "day", "month"),
        ({"year": "2023", "month": "jan"}, "year", "month"),
        ({"year": "x"}, "year", "year"),
        ({"year": "1", "week": "1"}, "year", "week"),
        ({"year": "1"}, "week", "week"),
    ]
    for fields, precision, level in cases:
        with pytest.raises(DateError) as error:
            from_fields(GREGORIAN, fields, precision)
        assert (error.value.code, error.value.level) == ("invalid_date", level)


def test_normalize_fields() -> None:
    shire = CALENDARS["intercalary-exceptions"]
    assert normalize_fields(shire, {"year": "4", "month": "12", "day": "05"}) == {
        "year": "4",
        "month": "lastmonth",
        "day": "5",
    }
    assert normalize_fields(shire, {"year": "4", "month": "2"}) == {"year": "4", "month": "2"}
    assert normalize_fields(GREGORIAN, {"year": "2024", "month": "3"}) == {
        "year": "2024",
        "month": "mar",
    }
    for invalid in ({}, {"year": "2023", "month": "2", "day": "29"}):
        with pytest.raises(DateError):
            normalize_fields(GREGORIAN, invalid)


# --- regimes (single-regime engine; full reform semantics arrive with #14) -----------------------


def reformed(start_shift_days: int) -> CompiledCalendar:
    """Gregorian, plus a regime from 2000-01-01 (regime 0) whose 2000-01-01 is shifted."""
    document = copy.deepcopy(load("gregorian-seconds"))
    definition, context = document["definition"], document["context"]
    second = copy.deepcopy(definition["regimes"][0])
    second["id"] = "reformed"
    second["name"] = "Reformed"
    switch = 10**14  # 2000-01-01 in regime 0
    second["starts_at"] = {"anchor": {"kind": "absolute", "t": str(switch)}, "precision": "base"}
    aligned = switch + start_shift_days * DAY
    second["alignment"]["at"] = {
        "anchor": {"kind": "absolute", "t": str(aligned)},
        "precision": "base",
    }
    definition["regimes"].append(second)
    context["resolved"] |= {
        "/regimes/1/starts_at": str(switch),
        "/regimes/1/alignment/at": str(aligned),
    }
    return compiled(document)


def test_reform_gap_and_regime_choice() -> None:
    calendar = reformed(-10)  # 2000-01-11 (reformed) is the switch moment: 1-10 January are skipped
    switch = 10**14
    assert to_fields(calendar, switch).levels["day"].n == 11
    assert to_fields(calendar, switch).regime == "reformed"
    assert to_fields(calendar, switch - 1).regime == "gregorian"
    jan = {"year": "2000", "month": "jan"}
    assert from_fields(calendar, jan | {"day": "15"}, "day") == switch + 4 * DAY
    assert (
        from_fields(calendar, {"year": "1999", "month": "dec", "day": "31"}, "day") == switch - DAY
    )
    with pytest.raises(DateError) as error:
        from_fields(calendar, jan | {"day": "5"}, "day")
    assert error.value.code == "reform_gap"
    assert from_fields(calendar, jan | {"day": "5"}, "day", regime="gregorian") == switch + 4 * DAY
    with pytest.raises(DateError) as error:
        from_fields(calendar, jan | {"day": "5"}, "day", regime="julian")
    assert error.value.code == "invalid_date"
    with pytest.raises(DateError) as error:
        from_fields(calendar, {"year": "2001", "month": "feb", "day": "30"}, "day")
    assert error.value.code == "invalid_date"  # invalid in every regime
    assert normalize_fields(calendar, jan | {"day": "15"}) == jan | {"day": "15"}
    assert normalize_fields(calendar, jan | {"day": "5"}, regime="gregorian") == jan | {"day": "5"}


def test_reform_overlap_is_ambiguous() -> None:
    calendar = reformed(10)  # the reformed 2000-01-01 is 10 days after the switch: dates repeat
    with pytest.raises(DateError) as error:
        from_fields(calendar, {"year": "1999", "month": "dec", "day": "25"}, "day")
    assert error.value.code == "reform_ambiguous"


def test_local_start_regimes_wait_for_local_resolution() -> None:
    document = copy.deepcopy(load("gregorian-seconds"))
    second = copy.deepcopy(document["definition"]["regimes"][0])
    second["id"] = "later"
    second["starts_at"] = {
        "anchor": {"kind": "local", "fields": {"year": "2100"}},
        "precision": "year",
    }
    document["definition"]["regimes"].append(second)
    document["context"]["resolved"]["/regimes/1/alignment/at"] = "0"
    calendar = compiled(document)
    assert to_fields(calendar, 10**16).regime == "gregorian"
    assert from_fields(calendar, {"year": "2200"}, "year") == calendar.regimes[0].year_start(2200)


# --- performance ---------------------------------------------------------------------------------


@pytest.mark.perf
def test_gregorian_throughput() -> None:
    rng = random.Random(20261002)
    moments_ = [rng.randrange(0, 2 * 10**14) for _ in range(20_000)]
    started = time.perf_counter()
    dates = [to_fields(GREGORIAN, t) for t in moments_]
    to_rate = len(moments_) / (time.perf_counter() - started)
    inputs = [as_input(date) for date in dates]
    started = time.perf_counter()
    for fields in inputs:
        from_fields(GREGORIAN, fields, "second")
    from_rate = len(inputs) / (time.perf_counter() - started)
    assert to_rate >= 50_000, f"to_fields: {to_rate:.0f}/s"
    assert from_rate >= 50_000, f"from_fields: {from_rate:.0f}/s"
