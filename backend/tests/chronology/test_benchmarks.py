"""Benchmarks of the Python engine's hot paths, with their budgets (testing.md §4.1).

Marked ``perf``: run them with ``make bench`` (nightly in CI). Each benchmark asserts its budget on
the median, and pytest-benchmark prints the timing table. The TypeScript twins are in
``packages/chronology/test/engine.bench.ts``.
"""

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter
from pytest_benchmark.fixture import BenchmarkFixture

from lore.chronology.calendar import CompiledCalendar, validate_calendar
from lore.chronology.calendar.arithmetic import add, diff
from lore.chronology.calendar.convert import from_fields, to_fields
from lore.chronology.calendar.units import from_ordinal, ordinal
from lore.chronology.recurrence import RecurrenceContext, expand, series_bounds
from lore.chronology.schema import EndSpec, RecurrenceRule

pytestmark = pytest.mark.perf

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
DAY = 86_400
RULE: TypeAdapter[RecurrenceRule] = TypeAdapter(RecurrenceRule)
END: TypeAdapter[EndSpec] = TypeAdapter(EndSpec)


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(document: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


PRESET_DOCUMENT = load("preset-gregorian")
GREGORIAN_DOCUMENT = load("gregorian-seconds")  # the calendar the budgets were set on
GREGORIAN = compiled(GREGORIAN_DOCUMENT)
WEEK_DOCUMENT = load("gregorian-week")
END_INSTANT = END.validate_python({"kind": "instant"})


def per_item(benchmark: BenchmarkFixture, items: int, budget: float) -> None:
    """Assert the median per item (``budget`` in seconds) of a benchmark over ``items`` items."""
    assert benchmark.stats is not None, "the benchmark didn't run"
    median = benchmark.stats.stats.median / items
    assert median < budget, f"{median * 1e6:.1f} µs per item (budget {budget * 1e6:.0f} µs)"


def moments(count: int, high: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.randrange(0, high) for _ in range(count)]


def as_input(found: Any) -> dict[str, str]:
    """``to_fields`` output as ``from_fields`` input (slot ids, else numbers)."""
    levels = found.as_json()["levels"]
    return {level: value.get("id") or value["n"] for level, value in levels.items()}


# --- compile -------------------------------------------------------------------------------------


def test_compile_gregorian(benchmark: BenchmarkFixture) -> None:
    """Budget: 20 ms for the Gregorian preset (a calendar is compiled for every edit preview)."""
    definition, context = PRESET_DOCUMENT["definition"], PRESET_DOCUMENT["context"]
    benchmark(validate_calendar, definition, context)
    per_item(benchmark, 1, 0.02)


def test_compile_million_year_period(benchmark: BenchmarkFixture) -> None:
    """Budget (#10): a 1,000,000-year top period compiles in < 2 s."""
    document = copy.deepcopy(load("gregorian-seconds"))
    document["definition"]["regimes"][0]["top"]["pattern"] = {
        "kind": "rules",
        "default": "year_common",
        "rules": [
            {"when": {"mod": "64", "eq": "0"}, "template": "year_leap"},
            {"when": {"mod": "15625", "eq": "3"}, "template": "year_leap"},
        ],
    }
    result = benchmark.pedantic(  # type: ignore[no-untyped-call]
        compiled, args=(document,), rounds=3, iterations=1
    )
    assert result.regimes[0].period == 1_000_000
    per_item(benchmark, 1, 2.0)


# --- conversions ---------------------------------------------------------------------------------

BATCH = 1000


def test_to_fields(benchmark: BenchmarkFixture) -> None:
    """Budget (#11): ≥ 50,000 conversions/s, i.e. < 20 µs each (years 0 to ~6 million)."""
    batch = moments(BATCH, 2 * 10**14, 1)
    benchmark(lambda: [to_fields(GREGORIAN, t) for t in batch])
    per_item(benchmark, BATCH, 20e-6)


def test_from_fields(benchmark: BenchmarkFixture) -> None:
    """Budget (#11): ≥ 50,000 conversions/s, i.e. < 20 µs each (years 0 to ~6 million)."""
    inputs = [as_input(to_fields(GREGORIAN, t)) for t in moments(BATCH, 2 * 10**14, 2)]
    benchmark(lambda: [from_fields(GREGORIAN, fields, "second") for fields in inputs])
    per_item(benchmark, BATCH, 20e-6)


def test_ordinal_round_trip(benchmark: BenchmarkFixture) -> None:
    """Budget (#12): ≥ 10,000 ``ordinal`` + ``from_ordinal`` pairs/s, i.e. < 100 µs each."""
    batch = moments(BATCH, 10**30, 3)

    def run() -> None:
        for t in batch:
            from_ordinal(GREGORIAN, "day", ordinal(GREGORIAN, t, "day").value)

    benchmark(run)
    per_item(benchmark, BATCH, 100e-6)


# --- arithmetic ----------------------------------------------------------------------------------


def test_add_diff_far(benchmark: BenchmarkFixture) -> None:
    """Budget (#16): a ``diff`` (years to seconds) and the ``add`` back over 10^200 s in < 10 ms."""
    rng = random.Random(4)
    pairs = [sorted((rng.randrange(0, 10**200), rng.randrange(0, 10**200))) for _ in range(30)]

    def run() -> None:
        for t1, t2 in pairs:
            found = diff(GREGORIAN, t1, t2, "year", "second")
            add(GREGORIAN, t1, found.duration("cal"))

    benchmark(run)
    per_item(benchmark, len(pairs), 0.01)


# --- recurrence ----------------------------------------------------------------------------------


def _rule(**members: Any) -> RecurrenceRule:
    data = {"kind": "calendar", "calendar_id": "cal", "limit": {"kind": "never"}} | members
    return RULE.validate_python(data)


def _start(calendar: CompiledCalendar) -> int:
    fields = {"year": "2024", "month": "feb", "day": "29", "hour": "9"}
    return from_fields(calendar, fields, "hour")


def test_expand_far_window(benchmark: BenchmarkFixture) -> None:
    """Budget (#19): a window 10^90 years after the series start expands in < 50 ms."""
    monthly = _rule(freq={"level": "month"}, time={"fields": {"hour": "9"}})
    start = _start(GREGORIAN)
    duration = int(GREGORIAN_DOCUMENT["context"]["dimension_duration"])
    context = RecurrenceContext(
        start, END.validate_python({"kind": "instant"}), duration, GREGORIAN
    )
    far = start + 10**90 * 365 * DAY
    result = benchmark(expand, monthly, context, (far, far + 400 * DAY), 100)
    assert 12 <= len(result.items) <= 14
    per_item(benchmark, 1, 0.05)


def test_series_bounds_far_count(benchmark: BenchmarkFixture) -> None:
    """Budget (#21): count = 10^12 on a yearly rule gives the series bounds in < 100 ms, with a
    freshly compiled calendar (no cached counters)."""
    yearly = _rule(freq={"level": "year"}, limit={"kind": "count", "count": str(10**12)})

    def fresh() -> tuple[tuple[RecurrenceRule, RecurrenceContext], dict[str, Any]]:
        calendar = compiled(WEEK_DOCUMENT)
        duration = int(WEEK_DOCUMENT["context"]["dimension_duration"])
        return (yearly, RecurrenceContext(_start(calendar), END_INSTANT, duration, calendar)), {}

    bounds = benchmark.pedantic(series_bounds, setup=fresh, rounds=5)  # type: ignore[no-untyped-call]
    assert bounds.count == 10**12
    per_item(benchmark, 1, 0.1)
