"""Recurrence I: validation, interval and simple calendar rules, keys, expansion (recurrence.md)."""

import json
import time
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from lore.chronology.calendar import CompiledCalendar, from_fields, validate_calendar
from lore.chronology.recurrence import (
    RecurrenceContext,
    RecurrenceError,
    expand,
    next_occurrences,
    occurrence,
    series_bounds,
    validate_rule,
)
from lore.chronology.recurrence.engine import SCAN_LIMIT
from lore.chronology.schema import EndSpec, RecurrenceRule

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


@st.composite
def series(draw: st.DrawFn) -> tuple[RecurrenceRule, RecurrenceContext]:
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
    if draw(st.booleans()):
        found = rule(kind="interval", every=str(draw(st.integers(1, 10**12))))
    else:
        found = rule(
            freq={"level": draw(st.sampled_from(calendar.levels))},
            interval=str(draw(st.integers(1, 30))),
            missing=draw(st.sampled_from(["skip", "constrain"])),
        )
    return found, RecurrenceContext(start, end(duration), 10**30, calendar)


@given(series(), st.integers(0, 10**19), st.integers(0, 10**17))
def test_expanded_items_are_their_occurrences(
    found: tuple[RecurrenceRule, RecurrenceContext], w0: int, width: int
) -> None:
    recurrence, ctx = found
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


@given(series(), st.integers(0, 10**19))
def test_next_occurrences_agree_with_expand(
    found: tuple[RecurrenceRule, RecurrenceContext], after: int
) -> None:
    recurrence, ctx = found
    upcoming = next_occurrences(recurrence, ctx, after, 3)
    for item in upcoming:
        assert item.start >= after
        assert occurrence(recurrence, ctx, item.key) == item
    if len(upcoming) >= 2:
        window = expand(recurrence, ctx, (upcoming[0].start, upcoming[-1].start), 1000)
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


def test_counting_skipped_periods_is_limited() -> None:
    leap = rule(freq={"level": "day"}, time={"fields": {"hour": "9"}}, limit=UNTIL)
    start = g(2000, "jan", 1, 8)
    ctx = context(start, until=start + (SCAN_LIMIT + 10) * DAY)
    with pytest.raises(RecurrenceError) as raised:
        series_bounds(leap, ctx)
    assert raised.value.code == "rule.too_complex_to_count"
    small = context(start, until=start + 10 * DAY)
    assert series_bounds(leap, small).count == 10


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


@pytest.mark.parametrize(
    ("members", "issue"),
    [
        ({"freq": {"cycle": "week"}}, "#20"),
        ({"freq": {"level": "year"}, "filters": [{"mod": "2", "eq": "1"}]}, "#20"),
        ({"freq": {"level": "year"}, "select": {"path": [{"level": "month", "all": True}]}}, "#20"),
        ({"freq": {"level": "year"}, "limit": {"kind": "count", "count": "3"}}, "#21"),
        (
            {
                "freq": {"level": "year"},
                "exclusions": [{"from": UNTIL["until"], "to": UNTIL["until"]}],
            },
            "#21",
        ),
    ],
)
def test_later_features_are_not_implemented_yet(members: dict[str, Any], issue: str) -> None:
    found = rule(**members)
    ctx = context(g(2000, "jan", 1))
    assert validate_rule(found, ctx) == []
    with pytest.raises(NotImplementedError, match=issue):
        expand(found, ctx, (0, 1))
