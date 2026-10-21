"""Parsing typed dates (chronology-engine.md §10.1); vectors: cases/parsing/."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    format_date,
    parse_date,
    unit_bounds,
    validate_calendar,
)

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
NAMES = sorted(path.stem for path in (CONFORMANCE / "calendars").glob("*.json"))


def compiled(name: str) -> CompiledCalendar:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


CALENDARS = {name: compiled(name) for name in NAMES}
GREGORIAN = CALENDARS["gregorian-seconds"]
Y2K = 100_000_000_000_000  # 1 January 2000 00:00:00 (cases/conversions/gregorian-seconds)


@given(
    st.sampled_from(NAMES),
    st.integers(-(10**12), 10**12),
    st.integers(0, 6),
)
def test_formatted_text_reads_back_as_the_same_text(name: str, offset: int, level: int) -> None:
    """Whatever ``format`` writes parses to the unit containing the moment, or to another one
    ``format`` writes the same way (a text can name several units, like a reform year). Custom
    patterns can show finer values (``{base}``, overlays) that the parsed unit start lacks."""
    calendar = CALENDARS[name]
    precisions = [*calendar.levels, "base"]
    precision = precisions[min(level, len(precisions) - 1)]
    dated = name.startswith(("gregorian", "julian", "japanese"))
    t = max(Y2K + offset, 0) if dated else abs(offset)
    try:
        text = format_date(calendar, t, precision)
    except DateError:
        return
    if "\u00d7" in text:  # scientific notation is not exact (§10.1)
        return
    found = parse_date(calendar, text)
    if found.precision == "base":
        assert found.t == t
    elif format_date(calendar, found.t, found.precision) != text:
        bounds = unit_bounds(calendar, found.t, found.precision)
        assert bounds.start <= t < bounds.end


@given(st.integers(-(10**13), 10**13), st.sampled_from(["year", "month", "day", "hour", "minute"]))
def test_gregorian_round_trip_is_exact(offset: int, precision: str) -> None:
    t = Y2K + offset
    found = parse_date(GREGORIAN, format_date(GREGORIAN, t, precision))
    assert (found.precision, found.t) == (precision, unit_bounds(GREGORIAN, t, precision).start)


def test_result_shape() -> None:
    found = parse_date(GREGORIAN, "c.  15 Mar 2024, 14:30")
    assert found.as_json() == {
        "fields": {"year": "2024", "month": "mar", "day": "15", "hour": "14", "minute": "30"},
        "era": None,
        "precision": "minute",
        "approximate": True,
        "t": str(unit_bounds(GREGORIAN, found.t, "minute").start),
    }
    assert format_date(GREGORIAN, found.t, "minute") == "15 March 2024, 14:30"


@pytest.mark.parametrize("text", ["", "c.", "15 Mar", "March 2024 15", "15 March 2024,", "²⁰²⁴"])
def test_failures(text: str) -> None:
    with pytest.raises(DateError) as error:
        parse_date(GREGORIAN, text)
    assert error.value.code == "invalid_date"
