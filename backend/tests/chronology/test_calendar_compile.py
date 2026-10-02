"""Calendar compilation (chronology-engine.md §4, §5.1-§5.4); error codes: see the vectors."""

import copy
import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    ValidationError,
    compile_calendar,
    formats,
    validate_calendar,
)
from lore.chronology.calendar.compile import pointer
from lore.chronology.schema import CalendarDefinition, CompileContext

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"
DAY = 86_400


def load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    return document


def compiled(definition: dict[str, Any], context: dict[str, Any]) -> CompiledCalendar:
    result = validate_calendar(definition, context)
    assert isinstance(result, CompiledCalendar), result
    return result


GREGORIAN = load("gregorian-seconds")
ALTERNATING = load("alternating-years")


def gregorian_with_exceptions() -> CompiledCalendar:
    """Gregorian plus exception years with longer, shorter and equal lengths, around year 0."""
    document = copy.deepcopy(GREGORIAN)
    regime = document["definition"]["regimes"][0]
    regime["templates"]["year_short"] = {
        "level": "year",
        "sequence": [{"id": "jan", "template": "m31", "name": "January"}],
    }
    regime["top"]["exceptions"] = [
        {"year": "-401", "template": "year_leap"},
        {"year": "-4", "template": "year_short"},
        {"year": "0", "template": "year_common"},
        {"year": "7", "template": "year_short"},
        {"year": "1582", "template": "year_short"},
        {"year": "2000", "template": "year_leap"},
    ]
    return compiled(document["definition"], document["context"])


EXCEPTIONS = gregorian_with_exceptions()


# --- compiled structure --------------------------------------------------------------------------


def test_gregorian_structure() -> None:
    calendar = compiled(GREGORIAN["definition"], GREGORIAN["context"])
    regime = calendar.regimes[0]
    assert calendar.levels == ("second", "minute", "hour", "day", "month", "year")
    assert calendar.numbering_starts == (0, 0, 0, 1, 1, 1)
    assert (regime.period, regime.cycle_length) == (400, 146_097 * DAY)
    assert regime.epoch == 10**14 - 730_485 * DAY  # 0000-01-01 → 2000-01-01 is 730,485 days
    assert regime.year_start(2000) == 10**14
    assert regime.year_of(10**14) == 2000
    assert regime.year_of(10**14 - 1) == 1999
    assert [regime.regular_template(y) for y in (1900, 2000, 2024, 2023, -4)] == [
        "year_common",
        "year_leap",
        "year_leap",
        "year_common",
        "year_leap",
    ]
    leap = regime.templates["year_leap"]
    assert (leap.length, leap.total_count, leap.regular_count) == (366 * DAY, 12, 12)
    assert leap.units[calendar.level_index("day")] == (366, 366)
    assert leap.units[0] == (366 * DAY, 366 * DAY)
    assert regime.templates["second"].units == {}


def test_alternating_structure() -> None:
    regime = compiled(ALTERNATING["definition"], ALTERNATING["context"]).regimes[0]
    assert (regime.period, regime.cycle_length) == (2, 183 * DAY)
    assert regime.epoch == 435_000_000_000_000_000 - 92 * DAY
    assert [regime.regular_template(y) for y in (-1, 0, 1, 2)] == [
        "year_odd",
        "year_even",
        "year_odd",
        "year_even",
    ]


def test_template_children() -> None:
    document = copy.deepcopy(GREGORIAN)
    year = {
        "level": "year",
        "sequence": [
            {"id": "jan", "template": "m31", "name": "January", "abbr": "Jan"},
            {"id": "midyear", "template": "m1", "name": "Midyear", "intercalary": True},
            {"run": {"count": "3", "template": "m30"}},
            {"id": "dec", "template": "m31", "name": "December"},
        ],
    }
    regime = document["definition"]["regimes"][0]
    regime["templates"]["m1"] = {"level": "month", "uniform": {"count": "1"}}
    regime["templates"]["year_common"] = year
    document["definition"]["levels"][4]["default_template"] = "m30"
    template = (
        compiled(document["definition"], document["context"]).regimes[0].templates["year_common"]
    )
    assert (template.total_count, template.regular_count) == (6, 5)
    assert template.units[4] == (6, 5)  # months: Midyear is intercalary
    assert template.units[3] == (31 + 1 + 90 + 31, 31 + 1 + 90 + 31)  # its day is regular
    midyear = template.child_by_slot("midyear")
    assert midyear is not None
    assert (midyear.offset, midyear.regular_index, midyear.length) == (31 * DAY, None, DAY)
    assert template.child_by_slot("feb") is None
    third = template.child_by_regular_index(3)  # 0-based: jan, run[0], run[1], run[2]
    assert third is not None
    assert (third.offset, third.index, third.regular_index) == (32 * DAY + 60 * DAY, 2, 3)
    assert template.child_by_regular_index(5) is None
    assert template.child_by_regular_index(-1) is None
    inside = template.child_at(32 * DAY + 45 * DAY)
    assert (inside.offset, inside.template) == (32 * DAY + 30 * DAY, "m30")
    assert template.child_at(31 * DAY).segment.slot_id == "midyear"


def test_hash_and_equality() -> None:
    a = compiled(GREGORIAN["definition"], GREGORIAN["context"])
    b = compiled(copy.deepcopy(GREGORIAN["definition"]), GREGORIAN["context"])
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    other_context = GREGORIAN["context"] | {"dimension_duration": "10"}
    c = compiled(GREGORIAN["definition"], other_context)
    assert c != a
    assert c.definition_hash == a.definition_hash
    assert a != "calendar"


def test_compile_calendar_takes_models() -> None:
    definition = CalendarDefinition.model_validate(GREGORIAN["definition"])
    context = CompileContext.model_validate(GREGORIAN["context"])
    assert isinstance(compile_calendar(definition, context), CompiledCalendar)
    broken = CompileContext.model_validate(GREGORIAN["context"] | {"resolved": {}})
    errors = compile_calendar(definition, broken)
    assert errors == [
        ValidationError(
            "anchor.unresolved", "/regimes/0/alignment/at", "no resolved moment in the context"
        )
    ]
    assert isinstance(errors, list)
    assert errors[0].as_json() == {"code": "anchor.unresolved", "path": "/regimes/0/alignment/at"}


def test_cycle_pattern_with_exceptions_and_many_templates() -> None:
    document = copy.deepcopy(ALTERNATING)
    regime = document["definition"]["regimes"][0]
    templates = []
    for i in range(300):  # more than fit one byte: the sequence falls back to a list
        regime["templates"][f"y{i}"] = {
            "level": "year",
            "sequence": [{"run": {"count": str(1 + i % 3), "template": "m30"}}],
        }
        templates.append(f"y{i}")
    document["definition"]["levels"][4]["default_template"] = "m30"
    regime["top"]["pattern"] = {"kind": "cycle", "templates": templates, "start": "-5"}
    regime["alignment"]["fields"] = {"year": "1"}
    result = compiled(document["definition"], document["context"]).regimes[0]
    assert result.period == 300
    assert isinstance(result.top_sequence, list)
    assert [result.regular_template(y) for y in (-5, -4, 294, 295)] == ["y0", "y1", "y299", "y0"]
    for year in range(-310, 310, 7):
        assert (
            result.rel_start(year + 1) - result.rel_start(year) == result.year_template(year).length
        )


def test_rules_with_many_templates_match_per_year_evaluation() -> None:
    document = copy.deepcopy(GREGORIAN)
    regime = document["definition"]["regimes"][0]
    rules: list[dict[str, Any]] = []
    for i in range(260):
        regime["templates"][f"y{i}"] = copy.deepcopy(regime["templates"]["year_common"])
        rules.append({"when": {"mod": str(2 + i % 7), "eq": str(i % 2)}, "template": f"y{i}"})
    rules.append(
        {
            "when": {"all": [{"not": {"any": [{"mod": "4", "eq": "1"}]}}, {"mod": "1", "eq": "0"}]},
            "template": "year_leap",
        }
    )
    regime["top"]["pattern"] = {"kind": "rules", "default": "year_common", "rules": rules}
    result = compiled(document["definition"], document["context"]).regimes[0]
    assert result.period == 840  # lcm(2, …, 8)
    assert isinstance(result.top_sequence, list)

    def expected(year: int) -> str:
        for rule in rules[:-1]:
            if year % int(rule["when"]["mod"]) == int(rule["when"]["eq"]):
                return str(rule["template"])
        return "year_leap" if year % 4 != 1 else "year_common"

    assert all(result.regular_template(y) == expected(y) for y in range(-840, 840))


def test_rules_bit_parallel_matches_per_year_evaluation() -> None:
    document = copy.deepcopy(GREGORIAN)
    regime = document["definition"]["regimes"][0]
    regime["top"]["pattern"]["rules"].append(
        {
            "when": {"all": [{"mod": "3", "eq": "2"}, {"not": {"mod": "5", "eq": "0"}}]},
            "template": "year_short",
        }
    )
    regime["templates"]["year_short"] = {
        "level": "year",
        "sequence": [{"id": "jan", "template": "m31", "name": "January"}],
    }
    result = compiled(document["definition"], document["context"]).regimes[0]
    assert result.period == 1200  # lcm(4, 100, 400, 3, 5)
    assert isinstance(result.top_sequence, bytes)

    def expected(year: int) -> str:
        if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0:
            return "year_leap"
        if year % 3 == 2 and year % 5 != 0:
            return "year_short"
        return "year_common"

    assert all(result.regular_template(y) == expected(y) for y in range(-6000, 6000, 7))


# --- properties (chronology-engine §5.2, §5.3) ----------------------------------------------------

years = st.one_of(
    st.integers(-2100, 2100),
    st.sampled_from(
        [-402, -401, -400, -5, -4, -3, -1, 0, 1, 6, 7, 8, 1581, 1582, 1583, 1999, 2000, 2001]
    ),
    st.integers(-(10**200), 10**200),
)


@given(years)
def test_consecutive_year_starts_differ_by_the_year_length(year: int) -> None:
    regime = EXCEPTIONS.regimes[0]
    assert regime.rel_start(year + 1) - regime.rel_start(year) == regime.year_template(year).length


@given(years, st.integers(0, 400 * DAY))
def test_year_of_inverts_year_starts(year: int, offset: int) -> None:
    regime = EXCEPTIONS.regimes[0]
    rel = regime.rel_start(year) + offset
    found = regime.year_of_rel(rel)
    assert (
        regime.rel_start(found)
        <= rel
        < regime.rel_start(found) + regime.year_template(found).length
    )


def test_year_zero_starts_at_the_epoch() -> None:
    regime = EXCEPTIONS.regimes[0]
    assert regime.rel_start(0) == 0
    assert regime.year_of_rel(-1) == -1
    assert regime.year_template(7).id == "year_short"
    assert regime.year_template(0).id == "year_common"  # exception equal to... a common year
    assert regime.year_template(4).id == "year_leap"


# --- format tokens -------------------------------------------------------------------------------


def test_format_tokens() -> None:
    assert list(formats.tokens("{{literal}} {day:pad2}, {month.name}")) == [
        "day:pad2",
        "month.name",
    ]
    known = {
        "levels": frozenset({"day", "month"}),
        "cycles": frozenset({"week"}),
        "overlays": frozenset(),
    }
    assert formats.unknown_tokens(
        "{day.name:pad2} {cycle.moon} {overlay.x} {year.name} {}", **known
    ) == [
        "day.name:pad2",
        "cycle.moon",
        "overlay.x",
        "year.name",
        "",
    ]
    assert formats.unknown_tokens("}{day}", **known) == ["{"]
    assert formats.unknown_tokens("{day", **known) == ["{"]


# --- raw documents -------------------------------------------------------------------------------


def test_validate_reports_schema_errors_with_pointers() -> None:
    definition = copy.deepcopy(GREGORIAN["definition"])
    definition["regimes"][0]["alignment"]["at"]["anchor"]["t"] = "01"
    definition["regimes"][0]["templates"]["m30"]["uniform"]["count"] = "x"
    errors = validate_calendar(definition, {"base_unit": "s", "dimension_duration": "0"})
    assert isinstance(errors, list)
    assert [e.as_json() for e in errors] == [
        {"code": "schema.invalid", "path": "/$context/base_unit"},
        {"code": "schema.invalid", "path": "/$context/dimension_duration"},
        {"code": "schema.invalid", "path": "/regimes/0/alignment/at/anchor/t"},
        {"code": "schema.invalid", "path": "/regimes/0/templates/m30/uniform/count"},
    ]


def test_validate_rejects_non_objects() -> None:
    errors = validate_calendar([], GREGORIAN["context"])
    assert isinstance(errors, list)
    assert [e.as_json() for e in errors] == [{"code": "schema.invalid", "path": ""}]
    nested = {
        "schema_version": 1,
        "levels": [],
        "regimes": ["x", {"templates": {"t": "x"}}],
        "eras": ["x"],
    }
    errors = validate_calendar(nested, GREGORIAN["context"])
    assert isinstance(errors, list)
    assert {e.path for e in errors} >= {"/levels", "/regimes/0", "/eras/0"}


def test_too_many_templates() -> None:
    definition = copy.deepcopy(GREGORIAN["definition"])
    templates = definition["regimes"][0]["templates"]
    for i in range(501 - len(templates)):
        templates[f"extra{i}"] = {"level": "day", "uniform": {"count": "24"}}
    errors = validate_calendar(definition, GREGORIAN["context"])
    assert isinstance(errors, list)
    assert [e.as_json() for e in errors] == [
        {"code": "template.too_large", "path": "/regimes/0/templates"}
    ]


def test_pointer_escapes() -> None:
    assert pointer("formats", "a/b", "c~d", 3) == "/formats/a~1b/c~0d/3"


# --- performance (testing.md §4) -----------------------------------------------------------------


@pytest.mark.perf
def test_compiling_a_million_year_period_is_fast_and_small() -> None:
    document = copy.deepcopy(GREGORIAN)
    regime = document["definition"]["regimes"][0]
    regime["top"]["pattern"] = {
        "kind": "rules",
        "default": "year_common",
        "rules": [
            {"when": {"mod": "64", "eq": "0"}, "template": "year_leap"},
            {
                "when": {"any": [{"mod": "15625", "eq": "3"}, {"not": {"mod": "8", "eq": "1"}}]},
                "template": "year_leap",
            },
        ],
    }
    tracemalloc.start()
    started = time.perf_counter()
    result = compiled(document["definition"], document["context"])
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.regimes[0].period == 1_000_000
    assert elapsed < 2.0, f"compiled in {elapsed:.2f} s"
    assert peak < 300 * 2**20, f"peak memory {peak / 2**20:.0f} MB"
