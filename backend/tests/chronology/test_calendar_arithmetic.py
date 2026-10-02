"""Calendar arithmetic: add, diff, is_uniform and duration bounds (chronology-engine.md §9)."""

import copy
import json
import random
import time
from pathlib import Path
from typing import Any, Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    Difference,
    add,
    diff,
    duration_upper_bound,
    from_fields,
    is_uniform,
    to_fields,
    validate_calendar,
)
from lore.chronology.schema import BaseDuration, CalendarDuration

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
    for name in (
        "gregorian-seconds",
        "alternating-years",
        "intercalary-exceptions",
        "intercalary-day",
        "julian-gregorian",
    )
}
CALENDARS["void-years"] = with_void_years()
GREGORIAN = CALENDARS["gregorian-seconds"]
JULIAN_GREGORIAN = CALENDARS["julian-gregorian"]

calendars = st.sampled_from(sorted(CALENDARS))
moments = st.one_of(
    st.integers(0, 2 * 10**6),
    st.integers(99_000_000_000_000, 101_000_000_000_000),
    st.integers(435 * 10**15 - 10**12, 435 * 10**15 + 10**12),
    st.integers(0, 10**120),
)
amounts = st.one_of(st.integers(0, 30), st.integers(0, 10**40))


def duration(sign: Literal[1, -1] = 1, **levels: int) -> CalendarDuration:
    return CalendarDuration(
        kind="calendar",
        calendar_id="cal",
        amounts={level: str(n) for level, n in levels.items()},
        sign=sign,
    )


@st.composite
def durations(draw: st.DrawFn, calendar: CompiledCalendar) -> CalendarDuration:
    levels = draw(st.lists(st.sampled_from(calendar.levels), min_size=1, max_size=3, unique=True))
    sign: Literal[1, -1] = draw(st.sampled_from([1, -1]))
    return duration(sign, **{level: draw(amounts) for level in levels})


@st.composite
def level_range(draw: st.DrawFn, calendar: CompiledCalendar) -> tuple[str, str]:
    """(largest, smallest) with largest at least as coarse as smallest."""
    low, high = sorted(
        draw(st.lists(st.integers(0, len(calendar.levels) - 1), min_size=2, max_size=2))
    )
    return calendar.levels[high], calendar.levels[low]


def plus_one(found: CalendarDuration, level: str) -> CalendarDuration:
    amounts = dict(found.amounts) | {level: str(int(found.amounts[level]) + 1)}
    return duration(1, **{key: int(value) for key, value in amounts.items()})


# --- properties ----------------------------------------------------------------------------------


@given(calendars, moments, moments, st.data())
def test_diff_brackets_the_later_moment(name: str, a: int, b: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    largest, smallest = data.draw(level_range(calendar))
    t1, t2 = min(a, b), max(a, b)
    found = diff(calendar, t1, t2, largest, smallest)
    assert found.sign == 1
    high, low = calendar.levels.index(largest), calendar.levels.index(smallest)
    assert list(found.amounts) == [calendar.levels[i] for i in range(high, low - 1, -1)]
    reached = add(calendar, t1, found.duration("cal"))
    assert reached <= t2 < add(calendar, t1, plus_one(found.duration("cal"), smallest))
    assert found.base == t2 - reached
    reverse = diff(calendar, t2, t1, largest, smallest)
    assert reverse == Difference(found.amounts, found.base, -1 if t1 < t2 else 1)


@given(calendars, moments, st.data())
def test_upper_bound_holds(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    moved = data.draw(durations(calendar))
    assert abs(add(calendar, t, moved) - t) <= duration_upper_bound(calendar, moved)


@given(calendars, moments, st.data())
def test_steps_are_strictly_increasing(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    level = data.draw(st.sampled_from(calendar.levels))
    n = data.draw(st.integers(0, 50))
    here = add(calendar, t, duration(1, **{level: n}))
    assert add(calendar, t, duration(1, **{level: n + 1})) > here
    back = add(calendar, t, duration(-1, **{level: n}))
    assert add(calendar, t, duration(-1, **{level: n + 1})) < back


@given(calendars, moments, st.data())
def test_reject_agrees_with_constrain_or_refuses(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    moved = data.draw(durations(calendar))
    try:
        rejected: int | str = add(calendar, t, moved, "reject")
    except DateError as error:
        rejected = error.code
    assert rejected in {add(calendar, t, moved), "invalid_date"}


@given(calendars, moments, st.data())
def test_zero_amounts_are_the_identity(name: str, t: int, data: st.DataObject) -> None:
    calendar = CALENDARS[name]
    levels = data.draw(st.lists(st.sampled_from(calendar.levels), min_size=1, unique=True))
    assert add(calendar, t, duration(1, **dict.fromkeys(levels, 0)), "reject") == t


@given(st.integers(-(10**30), 10**30), moments)
def test_base_durations_are_exact(units: int, t: int) -> None:
    moved = BaseDuration(kind="base", units=str(units))
    assert add(GREGORIAN, t, moved) == t + units
    assert duration_upper_bound(GREGORIAN, moved) == abs(units)


# --- examples ------------------------------------------------------------------------------------


def test_uniform_levels() -> None:
    assert [is_uniform(GREGORIAN, level) for level in GREGORIAN.levels] == [
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    assert is_uniform(CALENDARS["intercalary-day"], "day")
    assert not is_uniform(CALENDARS["intercalary-day"], "month")
    # Julian and Gregorian days have the same length: still uniform across regimes.
    assert is_uniform(JULIAN_GREGORIAN, "day")
    with pytest.raises(DateError) as raised:
        is_uniform(GREGORIAN, "week")
    assert raised.value.level == "week"


def test_uniform_bounds_are_exact() -> None:
    assert duration_upper_bound(GREGORIAN, duration(day=3, hour=2)) == 3 * 86400 + 2 * 3600


def test_month_bound_covers_the_longest_month() -> None:
    bound = duration_upper_bound(GREGORIAN, duration(month=1))
    assert 31 * 86400 <= bound <= 62 * 86400


def test_year_without_regular_months_is_bounded() -> None:
    void = CALENDARS["void-years"]
    assert duration_upper_bound(void, duration(month=1)) > 0
    deepwinter = from_fields(void, {"year": "1", "month": "deepwinter", "day": "10"}, "day")
    moved = add(void, deepwinter, duration(year=1))
    assert to_fields(void, moved).levels["month"].slot_id == "void"


def test_reform_is_reckoned_in_the_starting_regime() -> None:
    start = from_fields(JULIAN_GREGORIAN, {"year": "1582", "month": "jan", "day": "1"}, "day")
    moved = to_fields(JULIAN_GREGORIAN, add(JULIAN_GREGORIAN, start, duration(year=1)))
    assert moved.regime == "gregorian"
    assert (moved.levels["year"].n, moved.levels["month"].slot_id, moved.levels["day"].n) == (
        1583,
        "jan",
        11,
    )


def test_errors() -> None:
    with pytest.raises(DateError) as raised:
        add(GREGORIAN, 0, duration(week=1))
    assert (raised.value.code, raised.value.level) == ("invalid_date", "week")
    with pytest.raises(DateError) as raised:
        diff(GREGORIAN, 0, 1, "day", "year")
    assert raised.value.code == "invalid_date"
    with pytest.raises(DateError):
        diff(GREGORIAN, 0, 1, "year", "week")


def test_reject_names_the_constrained_level() -> None:
    jan_31 = from_fields(GREGORIAN, {"year": "2023", "month": "jan", "day": "31"}, "day")
    with pytest.raises(DateError) as raised:
        add(GREGORIAN, jan_31, duration(month=1), "reject")
    assert raised.value.level == "day"


def test_base_remainder_is_constrained() -> None:
    """A level-0 unit shorter than the base remainder (variable level 0) constrains it."""
    document = copy.deepcopy(load("intercalary-exceptions"))
    templates = document["definition"]["regimes"][0]["templates"]
    templates["short_day"] = {"level": "day", "uniform": {"count": "10"}}
    templates["m30"] = {
        "level": "month",
        "sequence": [{"run": {"count": "29"}}, {"run": {"count": "1", "template": "short_day"}}],
    }
    calendar = compiled(document)
    assert not is_uniform(calendar, "day")
    day_29 = from_fields(calendar, {"year": "2", "month": "2", "day": "29"}, "day")
    assert add(calendar, day_29 + 20, duration(day=1)) == day_29 + 24 + 9
    with pytest.raises(DateError) as raised:
        add(calendar, day_29 + 20, duration(day=1), "reject")
    assert raised.value.level == "day"
    assert add(calendar, day_29 + 5, duration(day=1), "reject") == day_29 + 24 + 5


def test_nested_intercalary_units_are_bounded() -> None:
    """intercalary-day with a 2-unit Midyear's Day: the day level is variable and its intercalary
    day sits two levels below the year."""
    document = copy.deepcopy(load("intercalary-day"))
    templates = document["definition"]["regimes"][0]["templates"]
    templates["long_day"] = {"level": "day", "uniform": {"count": "2"}}
    templates["m30x"]["sequence"][1]["template"] = "long_day"
    calendar = compiled(document)
    assert not is_uniform(calendar, "day")
    rng = random.Random(16)
    for _ in range(500):
        t, n = rng.randrange(0, 10**4), rng.randrange(0, 200)
        moved = duration(rng.choice([1, -1]), day=n)
        assert abs(add(calendar, t, moved) - t) <= duration_upper_bound(calendar, moved)
    # 30 Second + 1 day skips the intercalary Midyear's Day at the variable day level.
    second_30 = from_fields(calendar, {"year": "3", "month": "second", "day": "30"}, "day")
    assert add(calendar, second_30, duration(day=1)) == second_30 + 3


# --- performance ---------------------------------------------------------------------------------


@pytest.mark.perf
def test_arithmetic_jumps_with_ordinals() -> None:
    rng = random.Random(16)
    pairs = [(rng.randrange(0, 10**200), rng.randrange(0, 10**200)) for _ in range(300)]
    started = time.perf_counter()
    for t1, t2 in pairs:
        found = diff(GREGORIAN, min(t1, t2), max(t1, t2), "year", "second")
        add(GREGORIAN, t1, found.duration("cal"))
    elapsed = time.perf_counter() - started
    assert elapsed < 3.0, f"300 diffs over 10^200 s took {elapsed:.2f} s"
