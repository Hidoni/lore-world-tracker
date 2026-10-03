"""Formatting (chronology-engine.md §3.11, §10); vectors: cases/formatting/."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    DisplayPoint,
    format_date,
    format_span,
    formats,
    validate_calendar,
)

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
LEAP_DAY_2024 = 100_000_762_523_200  # Thursday 29 February 2024 12:00 (cases/cycles/gregorian-week)
MARCH_1_2024 = LEAP_DAY_2024 + 12 * 3600
OVERLITHE_4 = 10_001_278  # cases/cycles/shire-week::to-fields-overlithe
DASH = " \u2013 "  # the default range separator


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(document: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


def with_formats(name: str, formats_: dict[str, Any]) -> CompiledCalendar:
    document = copy.deepcopy(load(name))
    document["definition"]["formats"] = formats_
    return compiled(document)


GREGORIAN = compiled(load("gregorian-seconds"))


def test_era_tokens_without_eras() -> None:
    calendar = with_formats(
        "gregorian-week", {"day": "{cycle.week}, {day} {month.name} {era_year} {era}{era.name}"}
    )
    assert format_date(calendar, LEAP_DAY_2024, "day") == "Thursday, 29 February 2024"


def test_excluded_cycle_renders_empty() -> None:
    calendar = with_formats("shire-week", {"intercalary": {"day": "[{cycle.week}] {month.name}"}})
    assert format_date(calendar, OVERLITHE_4, "day") == "[] Overlithe"


def test_span_with_interleaved_tokens_is_not_collapsed() -> None:
    calendar = with_formats("gregorian-week", {"day": "{day} {year} {month.name}"})
    start, end = DisplayPoint(LEAP_DAY_2024, "day"), DisplayPoint(MARCH_1_2024, "day")
    assert format_span(calendar, start, end) == "29 2024 February \u2013 1 2024 March"


def test_parse() -> None:
    assert formats.parse("{{{day:pad2}}} {era.name}") == [
        "{",
        formats.Token("level", "day", modifier="pad2"),
        "} ",
        formats.Token("era", attr="name"),
    ]
    with pytest.raises(formats.PatternError):
        formats.parse("{day.name:pad2}")


@given(
    st.integers(0, 10**16),
    st.integers(0, 10**10),
    st.sampled_from(["second", "minute", "hour", "day", "month", "year", "base"]),
)
def test_span_shortens_at_most_one_end(t: int, length: int, precision: str) -> None:
    start, end = DisplayPoint(t, precision), DisplayPoint(t + length, precision)
    first = format_date(GREGORIAN, start.t, precision)
    last = format_date(GREGORIAN, end.t, precision)
    text = format_span(GREGORIAN, start, end)
    assert text == first or text.startswith(f"{first}{DASH}") or text.endswith(f"{DASH}{last}")
    assert (text == first) == (first == last)
