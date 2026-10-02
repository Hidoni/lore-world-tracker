"""Unit bounds, ordinals, from_ordinal and options (chronology-engine.md §5.8, §6)."""

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
from lore.chronology.calendar.convert import to_fields
from lore.chronology.calendar.units import (
    REGULAR,
    Bounds,
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

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(document: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


def with_void_years() -> CompiledCalendar:
    """intercalary-exceptions plus exception years 2 and -7 whose only month is intercalary."""
    document = copy.deepcopy(load("intercalary-exceptions"))
    regime = document["definition"]["regimes"][0]
    regime["templates"]["year_void"] = {
        "level": "year",
        "sequence": [{"id": "void", "template": "m30", "name": "Void", "intercalary": True}],
    }
    regime["top"]["exceptions"] += [
        {"year": "2", "template": "year_void"},
        {"year": "-7", "template": "year_void"},
    ]
    return compiled(document)


CALENDARS = {
    name: compiled(load(name))
    for name in ("gregorian-seconds", "alternating-years", "intercalary-exceptions")
}
CALENDARS["void-years"] = with_void_years()
SHIRE = CALENDARS["intercalary-exceptions"]

NO_YULE = UnitFilter(
    "no-yule",
    counts=lambda segment: True,
    excludes=lambda segment: segment.slot_id == "yule",
)
"""Counts every unit (intercalary ones too) except Yule and everything inside it."""

calendars = st.sampled_from(sorted(CALENDARS))
moments = st.one_of(
    st.integers(0, 2 * 10**6),
    st.integers(0, 10**15),
    st.integers(435 * 10**15 - 10**12, 435 * 10**15 + 10**12),
    st.integers(0, 10**120),
)


# --- properties ----------------------------------------------------------------------------------


@given(calendars, moments, st.data())
def test_from_ordinal_inverts_ordinal(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    level = data.draw(st.sampled_from(calendar.levels))
    found = ordinal(calendar, t, level)
    bounds = from_ordinal(calendar, level, found.value)
    assert bounds.start <= t
    containing = unit_bounds(calendar, t, level)
    assert containing.start <= t < containing.end
    if found.counted:
        assert bounds == containing
        assert ordinal(calendar, bounds.start, level) == found
    else:  # t is in an intercalary unit: the preceding regular unit ends before it
        assert bounds.end <= containing.start


@given(calendars, st.one_of(st.integers(-5000, 5000), st.integers(-(10**200), 10**200)), st.data())
def test_ordinal_inverts_from_ordinal(name: str, m: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    level = data.draw(st.sampled_from(calendar.levels))
    bounds = from_ordinal(calendar, level, m)
    assert ordinal(calendar, bounds.start, level).value == m
    assert ordinal(calendar, bounds.end - 1, level).value == m
    assert from_ordinal(calendar, level, m + 1).start >= bounds.end


@given(
    st.sampled_from(["intercalary-exceptions", "void-years"]),
    moments,
    st.sampled_from(["day", "month"]),
)
def test_counted_ordinals_with_an_excluding_filter(name: str, t: int, level: str) -> None:
    calendar = CALENDARS[name]
    found = counted_ordinal(calendar, t, level, NO_YULE)
    bounds = from_counted_ordinal(calendar, level, found.value, NO_YULE)
    assert bounds.start <= t
    in_yule = to_fields(calendar, t).levels["month"].slot_id == "yule"
    assert found.counted is not in_yule
    if found.counted:
        assert bounds == unit_bounds(calendar, t, level)
    assert counted_ordinal(calendar, bounds.start, level, NO_YULE).value == found.value


# --- examples ------------------------------------------------------------------------------------


def test_excluding_filter_counts() -> None:
    year_1 = 1_000_000
    yule = year_1 + 30 * 24
    assert counted_ordinal(SHIRE, yule, "day", NO_YULE).counted is False
    # Year 0 has 363 days, one of them Yule: 362 counted days before year 1.
    assert counted_ordinal(SHIRE, year_1, "day", NO_YULE).value == 362
    assert counted_ordinal(SHIRE, yule + 24, "day", NO_YULE).value == 362 + 30
    # Months: NO_YULE counts Lithe (intercalary) but not Yule: 13 months per common year.
    assert counted_ordinal(SHIRE, year_1, "month", NO_YULE).value == 13
    assert from_counted_ordinal(SHIRE, "month", 13, NO_YULE).start == year_1


def test_void_exception_years() -> None:
    calendar = CALENDARS["void-years"]
    year_2 = calendar.regimes[0].year_start(2)
    found = ordinal(calendar, year_2, "month")
    assert not found.counted  # the Void month is intercalary
    last_of_year_1 = from_ordinal(calendar, "month", found.value)
    assert last_of_year_1.end == year_2
    assert from_ordinal(calendar, "month", found.value + 1).start == calendar.regimes[0].year_start(
        3
    )


def test_no_counted_units_at_all() -> None:
    document = copy.deepcopy(load("intercalary-exceptions"))
    regime = document["definition"]["regimes"][0]
    regime["templates"]["year_void"] = {
        "level": "year",
        "sequence": [{"id": "void", "template": "m30", "name": "Void", "intercalary": True}],
    }
    regime["top"] = {"pattern": {"kind": "fixed", "template": "year_void"}}
    regime["alignment"]["fields"] = {"year": "1"}
    calendar = compiled(document)
    assert ordinal(calendar, 0, "month").counted is False
    with pytest.raises(DateError) as error:
        from_ordinal(calendar, "month", 0)
    assert (error.value.code, error.value.level) == ("invalid_date", "month")
    assert from_ordinal(calendar, "day", 0) == Bounds(
        calendar.regimes[0].epoch, calendar.regimes[0].epoch + 24
    )


def test_options_examples() -> None:
    assert options(SHIRE, {}, "year") == [RangeOption(None, None)]
    found = options(SHIRE, {"year": "1"}, "month")
    assert found[1] == SlotOption("yule", None, "Yule", True)
    assert found[2] == RangeOption(2, 11)
    assert options(SHIRE, {"year": "1"}, "month", regime="shire") == found
    with pytest.raises(DateError):
        options(SHIRE, {"year": "1"}, "week")
    with pytest.raises(DateError):
        options(SHIRE, {"year": "1"}, "month", regime="nope")


def reformed() -> CompiledCalendar:
    document = copy.deepcopy(load("gregorian-seconds"))
    definition, context = document["definition"], document["context"]
    second = copy.deepcopy(definition["regimes"][0])
    second["id"] = "reformed"
    switch = 10**14 + 12 * 3600  # noon, 1 January 2000
    second["starts_at"] = {"anchor": {"kind": "absolute", "t": str(switch)}, "precision": "base"}
    second["alignment"]["at"] = {
        "anchor": {"kind": "absolute", "t": str(switch)},
        "precision": "base",
    }
    definition["regimes"].append(second)
    context["resolved"] |= {
        "/regimes/1/starts_at": str(switch),
        "/regimes/1/alignment/at": str(switch),
    }
    return compiled(document)


def test_bounds_are_clipped_at_regime_boundaries() -> None:
    calendar = reformed()
    switch = 10**14 + 12 * 3600
    before = unit_bounds(calendar, switch - 1, "day")
    after = unit_bounds(calendar, switch, "day")
    assert before == Bounds(10**14, switch)  # regime 0's 1 January ends at the switch
    assert after == Bounds(switch, switch + 86_400)  # the reformed 1 January starts at noon
    assert ordinal(calendar, switch, "year").value == 2000
    shift = (
        from_ordinal(calendar, "day", 0, regime="reformed").start
        - from_ordinal(calendar, "day", 0).start
    )
    assert shift == 12 * 3600  # each regime counts in its own structure (§7)
    with pytest.raises(DateError):
        from_ordinal(calendar, "day", 0, regime="julian")


def test_unknown_levels() -> None:
    for call in (
        lambda: ordinal(SHIRE, 0, "week"),
        lambda: unit_bounds(SHIRE, 0, "week"),
        lambda: from_ordinal(SHIRE, "week", 0),
        lambda: counted_ordinal(SHIRE, 0, "week", REGULAR),
    ):
        with pytest.raises(DateError):
            call()


# --- performance ---------------------------------------------------------------------------------


@pytest.mark.perf
def test_navigation_is_logarithmic_in_the_period() -> None:
    document = copy.deepcopy(load("gregorian-seconds"))
    regime = document["definition"]["regimes"][0]
    regime["top"]["pattern"] = {
        "kind": "rules",
        "default": "year_common",
        "rules": [
            {"when": {"mod": "64", "eq": "0"}, "template": "year_leap"},
            {"when": {"mod": "15625", "eq": "3"}, "template": "year_leap"},
        ],
    }
    calendar = compiled(document)
    assert calendar.regimes[0].period == 1_000_000
    started = time.perf_counter()
    ordinal(calendar, 0, "day")  # builds the per-period day counts once
    setup = time.perf_counter() - started
    rng = random.Random(7)
    moments_ = [rng.randrange(0, 10**30) for _ in range(10_000)]
    started = time.perf_counter()
    for t in moments_:
        found = ordinal(calendar, t, "day")
        from_ordinal(calendar, "day", found.value)
    rate = len(moments_) / (time.perf_counter() - started)
    assert setup < 2.0, f"count setup took {setup:.2f} s"
    assert rate >= 10_000, f"{rate:.0f} ordinal + from_ordinal pairs/s"
