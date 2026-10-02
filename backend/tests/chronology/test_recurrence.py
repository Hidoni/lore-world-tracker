"""Recurrence I: validation, interval and simple calendar rules, keys, expansion (recurrence.md)."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter

from lore.chronology.calendar import CompiledCalendar, from_fields, validate_calendar
from lore.chronology.recurrence import (
    RecurrenceContext,
    RecurrenceError,
    count_in_window,
    expand,
    next_occurrences,
    occurrence,
    occurrence_at,
    occurrence_number,
    series_bounds,
    validate_rule,
)
from lore.chronology.recurrence.calendar_rules import CalendarPlan
from lore.chronology.schema import CalendarRule, EndSpec, RecurrenceRule

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
RULE: TypeAdapter[RecurrenceRule] = TypeAdapter(RecurrenceRule)
END: TypeAdapter[EndSpec] = TypeAdapter(EndSpec)
DAY = 86400


def compiled(name: str) -> CompiledCalendar:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


CALENDARS = {
    name: compiled(name)
    for name in (
        "gregorian-seconds",
        "alternating-years",
        "intercalary-exceptions",
        "intercalary-day",
        "gregorian-week",
        "shire-week",
    )
}
GREGORIAN = CALENDARS["gregorian-seconds"]
D = 10**120


def rule(**members: Any) -> RecurrenceRule:
    data = {"kind": "calendar", "calendar_id": "cal", "limit": {"kind": "never"}} | members
    if data["kind"] == "interval":
        data.pop("calendar_id")
    return RULE.validate_python(data)


def end(spec: dict[str, Any] | None = None) -> EndSpec:
    return END.validate_python(spec or {"kind": "instant"})


def context(
    start: int,
    calendar: CompiledCalendar | None = GREGORIAN,
    end_spec: dict[str, Any] | None = None,
    **resolved: int,
) -> RecurrenceContext:
    pointers = {f"/limit/{key}": value for key, value in resolved.items()}
    return RecurrenceContext(start, end(end_spec), D, calendar, pointers)


def g(year: int, month: str, day: int, hour: int = 0) -> int:
    fields = {"year": str(year), "month": month, "day": str(day), "hour": str(hour)}
    return from_fields(GREGORIAN, fields, "hour")


UNTIL = {"kind": "until", "until": {"anchor": {"kind": "absolute", "t": "0"}, "precision": "base"}}


# --- properties ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Series:
    """A drawn series; examples print the calendar's name, not the compiled calendar."""

    rule: RecurrenceRule
    calendar: str
    start: int
    end: dict[str, Any]

    @property
    def context(self) -> RecurrenceContext:
        return RecurrenceContext(self.start, end(self.end), 10**30, CALENDARS[self.calendar])


def _day(values: list[str]) -> dict[str, Any]:
    return {"level": "day", "values": values}


def _week(values: list[str], nth: list[str] | None = None) -> dict[str, Any]:
    match: dict[str, Any] = {"id": "week", "values": values}
    if nth is not None:
        match["nth"] = nth
    return {"level": "day", "cycle": match}


ADVANCED: list[dict[str, Any]] = [
    {"freq": {"level": "month"}, "select": {"path": [_week(["1"], ["1"])]}},
    {"freq": {"level": "month"}, "select": {"path": [_week(["2", "6"], ["-1", "2"])]}},
    {"freq": {"cycle": "week"}, "select": {"path": [_day(["1", "5"])]}},
    {"freq": {"cycle": "week"}},
    {"freq": {"level": "year"}, "select": {"path": [_day(["100", "-1"])]}},
    {"freq": {"level": "year"}, "select": {"path": [_week(["5"], ["1", "-1"])]}},
    {"freq": {"level": "month"}, "select": {"path": [{"level": "day", "all": True}]}},
    {
        "freq": {"level": "year"},
        "filters": [{"mod": "2", "eq": "1"}],
        "select": {"path": [{"level": "month", "values": ["2"]}, _day(["3"])]},
    },
    {"freq": {"level": "month"}, "filters": [{"not": {"in": ["1"]}}]},
    {"freq": {"level": "day"}, "filters": [{"any": [{"cycle": "week", "in": ["1", "2", "3"]}]}]},
]
"""Rules for calendars with a 7-day ``week`` cycle at the ``day`` level (dense enough that
property windows don't visit thousands of empty periods)."""


@st.composite
def series(draw: st.DrawFn) -> Series:
    name = draw(st.sampled_from(sorted(CALENDARS)))
    calendar = CALENDARS[name]
    start = draw(st.integers(0, 10**18))
    duration: dict[str, Any] = draw(
        st.sampled_from(
            [
                {"kind": "instant"},
                {"kind": "duration", "duration": {"kind": "base", "units": "100000"}},
                {
                    "kind": "duration",
                    "duration": {
                        "kind": "calendar",
                        "calendar_id": "cal",
                        "amounts": {calendar.levels[-2]: "1"},
                        "sign": 1,
                    },
                },
            ]
        )
    )
    kind = draw(st.sampled_from(["interval", "simple", "advanced"]))
    if kind == "interval":
        found = rule(kind="interval", every=str(draw(st.integers(1, 10**12))))
    elif kind == "advanced" and "week" in name:
        members = draw(st.sampled_from(ADVANCED))
        # An interval can starve a filter forever (every 2nd year, odd years only): searches then
        # scan their whole limit, which is correct but slow, so filtered rules keep interval 1.
        interval = 1 if "filters" in members else draw(st.integers(1, 3))
        found = rule(
            **members,
            interval=str(interval),
            missing=draw(st.sampled_from(["skip", "constrain"])),
        )
    else:
        found = rule(
            freq={"level": draw(st.sampled_from(calendar.levels))},
            interval=str(draw(st.integers(1, 30))),
            missing=draw(st.sampled_from(["skip", "constrain"])),
        )
    return Series(found, name, start, duration)


@settings(deadline=None)  # the first count of a rule may build its super-period counter
@given(series(), st.integers(0, 10**19), st.integers(0, 10**17))
def test_expanded_items_are_their_occurrences(found: Series, w0: int, width: int) -> None:
    recurrence, ctx = found.rule, found.context
    result = expand(recurrence, ctx, (w0, w0 + width), 50)
    starts = [item.start for item in result.items]
    assert starts == sorted(starts)
    for item in result.items:
        assert occurrence(recurrence, ctx, item.key) == item
        assert item.start >= ctx.series_start
        assert item.start < w0 + width or item.start == w0
    if result.truncated:
        assert result.items == []
        assert result.estimated_count is not None


@settings(deadline=None)  # the first count of a rule may build its super-period counter
@given(series(), st.integers(0, 10**19))
def test_next_occurrences_agree_with_expand(found: Series, after: int) -> None:
    recurrence, ctx = found.rule, found.context
    upcoming = next_occurrences(recurrence, ctx, after, 3)
    for item in upcoming:
        assert item.start >= after
        assert occurrence(recurrence, ctx, item.key) == item
    if len(upcoming) >= 2:
        window = expand(recurrence, ctx, (upcoming[0].start, upcoming[-1].start), 1000)
        if window.truncated:  # long occurrences (e.g. a month every base unit) overlap en masse
            assert window.estimated_count is not None
            assert window.estimated_count >= len(upcoming) - 1
        else:
            starts = {item.start for item in window.items}
            assert {item.start for item in upcoming[:-1]} <= starts


# --- examples ------------------------------------------------------------------------------------


def test_far_window_is_fast() -> None:
    """No iteration from the series start: a window 10^90 years away expands at once."""
    start = g(2023, "jan", 31, 8)
    monthly = rule(freq={"level": "month"}, time={"fields": {"hour": "9"}})
    ctx = context(start)
    far = start + 10**90 * 365 * DAY
    started = time.perf_counter()
    result = expand(monthly, ctx, (far, far + 400 * DAY), 100)
    elapsed = time.perf_counter() - started
    assert 7 <= len(result.items) <= 9
    assert elapsed < 0.05, f"far expansion took {elapsed * 1000:.1f} ms"


def test_next_occurrences() -> None:
    leap = rule(freq={"level": "year"})
    ctx = context(g(2024, "feb", 29, 10))
    found = next_occurrences(leap, ctx, g(2025, "jan", 1), 3)
    assert [item.key for item in found] == ["4", "8", "12"]
    bounded = rule(freq={"level": "year"}, limit=UNTIL)
    ctx = context(g(2024, "feb", 29, 10), until=g(2030, "jan", 1))
    assert [item.key for item in next_occurrences(bounded, ctx, 0, 5)] == ["0", "4"]
    assert next_occurrences(bounded, ctx, g(2031, "jan", 1), 5) == []


def test_series_without_occurrences() -> None:
    timed = rule(freq={"level": "year"}, time={"fields": {"hour": "9"}}, limit=UNTIL)
    start = g(2024, "mar", 1, 15)
    ctx = context(start, until=start)
    bounds = series_bounds(timed, ctx)
    assert (bounds.first_start, bounds.count) == (None, 0)
    assert expand(timed, ctx, (0, D), 10).items == []


def test_aperiodic_rules_count_only_nearby() -> None:
    """Year-number ``in`` filters aren't periodic: counting falls back to enumerating periods,
    which works near the start and is ``rule.too_complex_to_count`` far from it."""
    years = rule(freq={"level": "year"}, filters=[{"in": ["2001", "2003"]}], limit=UNTIL)
    start = g(2000, "jan", 1)
    near = series_bounds(years, context(start, until=g(2010, "jan", 1)))
    assert (near.first_start, near.last_start, near.count) == (
        g(2001, "jan", 1),
        g(2003, "jan", 1),
        2,
    )
    far = context(start, until=start + 10**30)
    with pytest.raises(RecurrenceError) as raised:
        series_bounds(years, far)
    assert raised.value.code == "rule.too_complex_to_count"


def test_reversed_and_empty_windows() -> None:
    yearly = rule(freq={"level": "year"})
    ctx = context(g(2000, "jan", 1))
    assert expand(yearly, ctx, (g(2010, "jan", 1), g(2005, "jan", 1))).items == []
    assert expand(yearly, ctx, (g(2010, "jan", 1), g(2010, "jan", 1))).items[0].key == "10"


def test_validation_errors() -> None:
    def codes(found: RecurrenceRule, ctx: RecurrenceContext) -> list[tuple[str, str]]:
        return [(e.code, e.path) for e in validate_rule(found, ctx)]

    start = g(2000, "jan", 1)
    assert codes(rule(freq={"level": "year"}), context(start, None)) == [
        ("rule.unknown_calendar", "/calendar_id")
    ]
    assert codes(rule(freq={"level": "week"}), context(start)) == [
        ("rule.bad_freq_level", "/freq/level")
    ]
    assert codes(rule(freq={"level": "day"}, time={"fields": {"month": "1"}}), context(start)) == [
        ("rule.bad_time_fields", "/time/fields/month")
    ]
    gap = rule(freq={"level": "day"}, time={"fields": {"hour": "9", "second": "0"}})
    assert codes(gap, context(start)) == [("rule.bad_time_fields", "/time/fields")]
    assert codes(rule(freq={"level": "year"}, limit=UNTIL), context(start)) == [
        ("anchor.unresolved", "/limit/until")
    ]
    assert codes(rule(freq={"level": "year"}, limit=UNTIL), context(start, until=start - 1)) == [
        ("rule.until_before_start", "/limit/until")
    ]
    explicit = {"kind": "time_point", "time_point": UNTIL["until"]}
    assert codes(rule(freq={"level": "year"}), context(start, end_spec=explicit)) == [
        ("rule.series_end_not_duration", "/end")
    ]
    month = {
        "kind": "duration",
        "duration": {"kind": "calendar", "calendar_id": "c", "amounts": {"month": "1"}, "sign": 1},
    }
    interval = rule(kind="interval", every="10")
    assert codes(interval, context(start, None, month)) == [
        ("rule.unknown_calendar", "/end/duration/calendar_id")
    ]
    with pytest.raises(RecurrenceError) as raised:
        expand(interval, context(start, None, month), (0, 1))
    assert raised.value.code == "rule.invalid"
    assert raised.value.errors[0].code == "rule.unknown_calendar"


def test_start_mismatch_is_a_warning() -> None:
    timed = rule(freq={"level": "month"}, time={"fields": {"hour": "9", "minute": "0"}})
    found = validate_rule(timed, context(g(2023, "jan", 31, 15)))
    assert [(e.code, e.severity) for e in found] == [
        ("rule.series_start_not_occurrence", "warning")
    ]
    assert validate_rule(timed, context(g(2023, "jan", 31, 9))) == []


WEEK = CALENDARS["gregorian-week"]


def test_advanced_validation_errors() -> None:
    def codes(**members: Any) -> list[tuple[str, str]]:
        found = rule(**members)
        found_errors = validate_rule(found, context(g(2000, "jan", 3), WEEK))
        return [(e.code, e.path) for e in found_errors if e.severity == "error"]

    day = {"level": "day", "values": ["1"]}
    assert codes(freq={"cycle": "fortnight"}) == [("rule.bad_freq_level", "/freq/cycle")]
    assert codes(freq={"level": "month"}, filters=[{"mod": "2", "eq": "2"}]) == [
        ("rule.bad_filter", "/filters/0/eq")
    ]
    assert codes(freq={"cycle": "week"}, filters=[{"in": ["1"]}]) == [
        ("rule.bad_filter", "/filters/0")
    ]
    assert codes(freq={"level": "month"}, filters=[{"cycle": "week", "in": ["mon"]}]) == [
        ("rule.bad_filter", "/filters/0/cycle")
    ]
    assert codes(freq={"level": "day"}, filters=[{"not": {"cycle": "week", "in": ["moon"]}}]) == [
        ("rule.unknown_slot", "/filters/0/not/in/0")
    ]
    assert codes(freq={"level": "month"}, filters=[{"any": [{"in": ["frostfall"]}]}]) == [
        ("rule.unknown_slot", "/filters/0/any/0/in/0")
    ]
    assert codes(freq={"level": "month"}, select={"path": [{"level": "month", "all": True}]}) == [
        ("rule.bad_selector_level", "/select/path/0/level")
    ]
    assert codes(
        freq={"level": "year"}, select={"path": [day, {"level": "month", "all": True}]}
    ) == [("rule.bad_selector_level", "/select/path/1/level")]
    assert codes(freq={"cycle": "week"}, select={"path": [{"level": "hour", "all": True}]}) == [
        ("rule.bad_selector_level", "/select/path/0/level")
    ]
    assert codes(
        freq={"level": "year"}, select={"path": [{"level": "month", "values": ["x"]}]}
    ) == [("rule.unknown_slot", "/select/path/0/values/0")]
    assert codes(freq={"cycle": "week"}, select={"path": [{"level": "day", "values": ["8"]}]}) == [
        ("rule.unknown_slot", "/select/path/0/values/0")
    ]
    bad_cycle = {"level": "month", "cycle": {"id": "week", "values": ["mon"]}}
    assert codes(freq={"level": "year"}, select={"path": [bad_cycle]}) == [
        ("rule.bad_selector_level", "/select/path/0/cycle/id")
    ]
    zeroth = {"level": "day", "cycle": {"id": "week", "values": ["mon"], "nth": ["1", "0"]}}
    assert codes(freq={"level": "month"}, select={"path": [zeroth]}) == [
        ("rule.bad_nth", "/select/path/0/cycle/nth/1")
    ]
    assert codes(freq={"level": "year"}, select={"path": [day]}, time={"fields": {"day": "2"}}) == [
        ("rule.bad_time_fields", "/time/fields/day")
    ]
    assert (
        codes(freq={"level": "year"}, select={"path": [day]}, time={"fields": {"hour": "9"}}) == []
    )


def test_reset_cycles_have_no_rounds() -> None:
    showcase = compiled("cycles-showcase")
    found = validate_rule(rule(freq={"cycle": "decan"}), context(1_000_000, showcase))
    assert [(e.code, e.path) for e in found] == [("rule.cycle_not_continuous", "/freq/cycle")]


def test_too_many_positions() -> None:
    document: dict[str, Any] = json.loads(
        (CONFORMANCE / "calendars" / "cycles-showcase.json").read_text()
    )
    regime = document["definition"]["regimes"][0]
    regime["templates"]["year"]["sequence"][0]["run"]["count"] = "6000"  # 6,000 x 20 days
    huge = validate_calendar(document["definition"], document["context"])
    assert isinstance(huge, CompiledCalendar)
    ctx = context(1_000_000, huge)
    every_day = rule(freq={"level": "year"}, select={"path": [{"level": "day", "all": True}]})
    with pytest.raises(RecurrenceError) as raised:
        expand(every_day, ctx, (1_000_000, 1_000_010))
    assert raised.value.code == "rule.too_many_positions"
    first_days = rule(freq={"level": "year"}, select={"path": [{"level": "day", "values": ["1"]}]})
    assert expand(first_days, ctx, (1_000_000, 1_000_010)).items[0].key == "0"


def test_keys_ignore_the_time_of_day() -> None:
    def keys(time_fields: dict[str, str]) -> list[str]:
        found = rule(
            freq={"cycle": "week"},
            select={"path": [{"level": "day", "values": ["mon", "fri"]}]},
            time={"fields": time_fields},
        )
        ctx = context(g(2024, "jan", 1), WEEK)
        window = (g(2024, "jan", 1), g(2024, "feb", 1))
        return [item.key for item in expand(found, ctx, window).items]

    assert keys({"hour": "6"}) == keys({"hour": "21", "minute": "45"})
    assert keys({"hour": "6"})[:3] == ["0.0", "0.1", "1.0"]


def test_round_filters_and_selectors() -> None:
    monday = g(2024, "jan", 1, 9)
    ctx = context(monday, WEEK)
    window = (monday, monday + 12 * 7 * DAY)

    def keys(**members: Any) -> list[str]:
        return [
            item.key for item in expand(rule(freq={"cycle": "week"}, **members), ctx, window).items
        ]

    filters = [{"all": [{"mod": "2", "eq": "0"}, {"not": {"mod": "3", "eq": "0"}}]}]
    round_numbers = [floor(key) for key in keys(filters=filters)]
    first = (monday - g(1999, "dec", 27, 9)) // (
        7 * DAY
    )  # round 0: the anchor (Sat 1 Jan 2000) week
    assert all((first + k) % 2 == 0 and (first + k) % 3 != 0 for k in round_numbers)
    assert keys(filters=[{"any": [{"mod": "4", "eq": str((first + 1) % 4)}]}]) == ["1", "5", "9"]
    sundays = keys(select={"path": [{"level": "day", "values": ["-1"]}]})
    assert sundays[:2] == ["0", "1"]
    found = expand(
        rule(freq={"cycle": "week"}, select={"path": [{"level": "day", "values": ["-1"]}]}),
        ctx,
        window,
    ).items
    assert found[0].start == g(2024, "jan", 7, 9)
    nth = {"id": "week", "values": ["sat", "sun"], "nth": ["1"]}
    weekend = expand(
        rule(freq={"cycle": "week"}, select={"path": [{"level": "day", "cycle": nth}]}), ctx, window
    ).items
    assert [item.start for item in weekend[:2]] == [g(2024, "jan", 6, 9), g(2024, "jan", 7, 9)]


def floor(key: str) -> int:
    return int(key.split(".", maxsplit=1)[0])


def test_selectors_can_skip_several_levels() -> None:
    hour_100 = rule(freq={"level": "year"}, select={"path": [{"level": "hour", "values": ["100"]}]})
    ctx = context(g(2024, "jan", 1), WEEK)
    found = expand(hour_100, ctx, (g(2024, "jan", 1), g(2025, "jan", 1))).items
    assert [item.start for item in found] == [g(2024, "jan", 5, 4)]  # hours count from 0


def test_sparse_windows_beyond_the_visit_limit_are_estimated() -> None:
    days = rule(freq={"level": "day"}, time={"fields": {"hour": "9"}})
    ctx = context(g(2000, "jan", 1, 9), WEEK)
    window = (g(2000, "jan", 1), g(2060, "jan", 1))
    result = expand(days, ctx, window, 10)
    assert result.truncated
    assert result.estimated_count is not None
    assert abs(result.estimated_count - 21915) <= 400  # sampled, not exact


def test_calendar_duration_ends() -> None:
    monthly = rule(freq={"level": "month"})
    month = {
        "kind": "duration",
        "duration": {"kind": "calendar", "calendar_id": "c", "amounts": {"month": "1"}, "sign": 1},
    }
    ctx = context(g(2024, "jan", 31), WEEK, month)
    found = expand(monthly, ctx, (g(2024, "feb", 20), g(2024, "feb", 21))).items
    assert [(item.start, item.end) for item in found] == [(g(2024, "jan", 31), g(2024, "feb", 29))]


def test_slot_ids_below_skipped_levels_use_sub_keys() -> None:
    """A slot id is unique only within its template: picked across months it gets k.j keys."""
    midyear_day = CALENDARS["intercalary-day"]
    by_slot = rule(
        freq={"level": "year"}, select={"path": [{"level": "day", "values": ["midyear"]}]}
    )
    ctx = context(0, midyear_day)
    found = expand(by_slot, ctx, (0, 91 * 3)).items
    assert [(item.key, item.start) for item in found] == [("0.0", 60), ("1.0", 151), ("2.0", 242)]
    by_number = rule(freq={"level": "year"}, select={"path": [{"level": "day", "values": ["61"]}]})
    assert [item.key for item in expand(by_number, ctx, (0, 91 * 3)).items] == ["0", "1", "2"]


# --- counting (recurrence III) -------------------------------------------------------------------


COUNTING_RULES: list[dict[str, Any]] = [
    {"freq": {"level": "month"}, "time": {"fields": {"day": "30"}}},
    {"freq": {"level": "month"}, "interval": "5", "filters": [{"mod": "3", "eq": "1"}]},
    {"freq": {"level": "year"}, "filters": [{"mod": "4", "eq": "2"}]},
    {
        "freq": {"level": "day"},
        "interval": "3",
        "filters": [{"mod": "7", "eq": "2", "of": "ordinal"}],
    },
    {"freq": {"level": "year"}, "select": {"path": [{"level": "month", "values": ["yule", "4"]}]}},
    {"freq": {"level": "year"}, "select": {"path": [{"level": "day", "values": ["-1", "100"]}]}},
]


@pytest.mark.parametrize("calendar_name", ["intercalary-exceptions", "void-years"])
@pytest.mark.parametrize("members", COUNTING_RULES)
def test_super_period_counts_match_enumeration(calendar_name: str, members: dict[str, Any]) -> None:
    """S(k) from super-periods (exception years included) equals counting period by period."""
    calendar = (
        CALENDARS["intercalary-exceptions"]
        if calendar_name == "intercalary-exceptions"
        else _void_years()
    )
    for start in (0, 1_000_000 - 9 * 24, 1_000_000 + 400 * 24):
        ctx = context(start, calendar)
        plan = CalendarPlan(calendar_rule(**members), ctx, calendar, D)
        counter = plan._counter()
        assert counter is not None
        running = 0
        for k in range(600):
            assert counter.count(k) == running, (start, k)
            running += plan._period_count(k)
        for i in (1, 7, running // 2, running):
            if i >= 1:
                found = counter.period_of(i)
                assert found is not None
                assert counter.count(found) < i <= counter.count(found + 1)


def calendar_rule(**members: Any) -> CalendarRule:
    found = rule(**members)
    assert isinstance(found, CalendarRule)
    return found


def _void_years() -> CompiledCalendar:
    document: dict[str, Any] = json.loads(
        (CONFORMANCE / "calendars" / "intercalary-exceptions.json").read_text()
    )
    regime = document["definition"]["regimes"][0]
    regime["templates"]["year_void"] = {
        "level": "year",
        "sequence": [{"id": "void", "template": "m30", "name": "Void", "intercalary": True}],
    }
    regime["top"]["exceptions"] += [
        {"year": "2", "template": "year_void"},
        {"year": "30", "template": "year_void"},
    ]
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar)
    return result


def test_weekly_counts_match_enumeration() -> None:
    shire = CALENDARS["shire-week"]
    members = {"freq": {"cycle": "week"}, "select": {"path": [{"level": "day", "values": ["-1"]}]}}
    plan = CalendarPlan(calendar_rule(**members), context(10_000_000, shire), shire, D)
    counter = plan._counter()
    assert counter is not None
    running = 0
    for k in range(400):
        assert counter.count(k) == running
        running += plan._period_count(k)


@settings(deadline=None)  # building a super-period counter takes up to seconds, once per rule
@given(series(), st.integers(0, 10**19), st.integers(0, 10**12))
def test_counts_agree_with_expansion(found: Series, w0: int, width: int) -> None:
    recurrence, ctx = found.rule, found.context
    window = (w0, w0 + width)
    try:
        counted, exact = count_in_window(recurrence, ctx, window)
    except RecurrenceError as error:
        code = error.code
        assert code == "rule.too_complex_to_count"
        return
    result = expand(recurrence, ctx, window, 200)
    if exact and not result.truncated:
        assert counted == len(result.items)
    numbers = [occurrence_number(recurrence, ctx, item.key) for item in result.items[:5]]
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers))) if numbers else True


def test_count_limit_far_is_fast() -> None:
    """Acceptance: count = 10^12 on a yearly rule computes series bounds in < 100 ms."""
    fresh = compiled("gregorian-week")  # no cached counters
    yearly = rule(freq={"level": "year"}, limit={"kind": "count", "count": str(10**12)})
    started = time.perf_counter()
    bounds = series_bounds(yearly, context(g(2024, "feb", 29, 9), fresh))
    elapsed = time.perf_counter() - started
    assert bounds.count == 10**12
    assert elapsed < 0.1, f"{elapsed * 1000:.1f} ms"


def test_rules_that_never_occur_are_found_at_once() -> None:
    """An interval that never meets the filter: no occurrence, and no long scan."""
    starved = rule(freq={"level": "year"}, interval="2", filters=[{"mod": "2", "eq": "1"}])
    ctx = context(g(2024, "jan", 1), WEEK)
    started = time.perf_counter()
    assert series_bounds(starved, ctx).first_start is None
    assert next_occurrences(starved, ctx, 0, 3) == []
    assert time.perf_counter() - started < 0.5


def test_too_complex_rules_are_estimated() -> None:
    showcase = compiled("cycles-showcase")
    huge = rule(freq={"level": "day"}, filters=[{"mod": "999983", "eq": "0", "of": "ordinal"}])
    ctx = context(1_000_000, showcase)
    count, exact = count_in_window(huge, ctx, (1_000_000, 1_000_000 + 10**12))
    assert not exact
    assert count >= 0
    with pytest.raises(RecurrenceError) as raised:
        occurrence_number(huge, ctx, str(10**9 * 999983))
    assert raised.value.code == "rule.too_complex_to_count"


def test_exclusion_validation() -> None:
    excluded = rule(
        freq={"level": "year"}, exclusions=[{"from": UNTIL["until"], "to": UNTIL["until"]}]
    )
    start = g(2000, "jan", 1)
    found = validate_rule(excluded, RecurrenceContext(start, end(None), D, WEEK, {}))
    assert [(e.code, e.path) for e in found] == [
        ("anchor.unresolved", "/exclusions/0/from"),
        ("anchor.unresolved", "/exclusions/0/to"),
    ]
    reversed_range = {"/exclusions/0/from": start + 10, "/exclusions/0/to": start}
    found = validate_rule(excluded, RecurrenceContext(start, end(None), D, WEEK, reversed_range))
    assert [(e.code, e.path) for e in found] == [("rule.bad_exclusion", "/exclusions/0")]
    empty = {"/exclusions/0/from": start, "/exclusions/0/to": start}
    assert (
        series_bounds(excluded, RecurrenceContext(start, end(None), D, WEEK, empty)).first_start
        == start
    )


def test_occurrence_at_without_occurrences() -> None:
    yearly = rule(freq={"level": "year"})
    ctx = context(g(2024, "jan", 1), WEEK)
    assert occurrence_at(yearly, ctx, g(2023, "jun", 1)) is None
    assert occurrence_at(yearly, ctx, g(2025, "jan", 1)) == "1"
    assert occurrence_at(yearly, ctx, g(2025, "jan", 1, 9)) is None  # instants: only at their start


def test_cycle_filters_count_like_enumeration() -> None:
    showcase = compiled("cycles-showcase")
    members = {
        "freq": {"level": "day"},
        "filters": [
            {"any": [{"cycle": "veintena", "in": ["0", "7"]}, {"cycle": "trecena", "in": ["13"]}]},
            {"not": {"mod": "2", "eq": "0", "of": "ordinal"}},
        ],
    }
    plan = CalendarPlan(calendar_rule(**members), context(1_000_000, showcase), showcase, D)
    counter = plan._counter()
    assert counter is not None
    # 365-day years: the 20-day veintena realigns after 4 years, the 13-day trecena after 13
    # (and the ordinal parity after 2): the super-period is 52 years of days.
    assert counter.q == 52 * 365
    running = 0
    for k in range(3000):
        assert counter.count(k) == running
        running += plan._period_count(k)
