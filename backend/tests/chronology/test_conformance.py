"""Conformance runner: every vector in spec/chronology/conformance/ against the Python engine.

The format and the ops are documented in ``spec/chronology/conformance/README.md``. Ops that the
Python engine doesn't implement yet are listed in ``PENDING`` with the issue that implements them;
their cases are strict expected failures, so implementing an op means adding its handler to
``HANDLERS`` and removing it from ``PENDING``.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from lore.chronology import numbers
from lore.chronology.calendar import CompiledCalendar, validate_calendar
from lore.chronology.calendar.compiled import DateError
from lore.chronology.calendar.convert import from_fields, options, options_json, to_fields
from lore.chronology.calendar.cycles import cycle_value
from lore.chronology.calendar.eras import era_of
from lore.chronology.calendar.units import Bounds, from_ordinal, ordinal, unit_bounds
from lore.chronology.schema import CalendarDefinition, CompileContext

CONFORMANCE_DIR = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"

NUMBER_OPS = frozenset(
    {
        "parse_moment",
        "format_moment",
        "parse_signed",
        "format_signed",
        "sortable_key",
        "from_sortable_key",
        "floor_div",
        "floor_mod",
        "rational_normalize",
        "rational_from_int",
        "rational_add",
        "rational_sub",
        "rational_mul",
        "rational_div",
        "rational_compare",
        "rational_floor",
        "rational_frac",
        "format_integer",
    }
)

OPS = NUMBER_OPS | frozenset(
    {
        "validate",
        "to_fields",
        "from_fields",
        "unit_bounds",
        "ordinal",
        "from_ordinal",
        "options",
        "cycle_value",
        "era_of",
        "overlay_phase",
        "add",
        "diff",
        "format",
        "format_span",
        "preset_instantiate",
        "expand",
        "series_bounds",
        "occurrence",
        "count_in_window",
        "map",
    }
)
"""Every op documented in the conformance README."""

CALENDAR_FREE_OPS = NUMBER_OPS | {"validate", "preset_instantiate", "map"}

type CalendarFile = dict[str, Any]
type Handler = Callable[[CalendarFile | None, dict[str, Any]], Any]


def _rational(data: dict[str, str]) -> numbers.Rational:
    return numbers.parse_rational(data["num"], data["den"])


def _binary(operation: Callable[[numbers.Rational, numbers.Rational], numbers.Rational]) -> Handler:
    return lambda _, d: numbers.format_rational(operation(_rational(d["a"]), _rational(d["b"])))


def _format_integer(_: CalendarFile | None, d: dict[str, Any]) -> Any:
    options = {key: d[key] for key in d.keys() - {"n"}}
    return {"text": numbers.format_integer(int(d["n"]), **options)}


_COMPILED: dict[int, CompiledCalendar] = {}


def _compiled(calendar: CalendarFile | None) -> CompiledCalendar:
    assert calendar is not None, "this op needs the case file's calendar"
    key = id(calendar)
    if key not in _COMPILED:
        result = validate_calendar(calendar["definition"], calendar["context"])
        assert isinstance(result, CompiledCalendar), result
        _COMPILED[key] = result
    return _COMPILED[key]


def _from_fields(calendar: CalendarFile | None, d: dict[str, Any]) -> Any:
    options = {key: d[key] for key in ("era", "regime", "overflow") if key in d}
    return {"t": str(from_fields(_compiled(calendar), d["fields"], d["precision"], **options))}


def _bounds(bounds: Bounds) -> dict[str, str]:
    return {"start": str(bounds.start), "end": str(bounds.end)}


def _ordinal(calendar: CalendarFile | None, d: dict[str, Any]) -> Any:
    found = ordinal(_compiled(calendar), int(d["t"]), d["level"])
    return {"ordinal": str(found.value), "intercalary": not found.counted}


def _cycle_value(calendar: CalendarFile | None, d: dict[str, Any]) -> Any:
    value = cycle_value(_compiled(calendar), int(d["t"]), d["cycle"])
    return None if value is None else value.as_json()


def _era_of(calendar: CalendarFile | None, d: dict[str, Any]) -> Any:
    value = era_of(_compiled(calendar), int(d["t"]))
    return None if value is None else value.as_json()


def _validate(_: CalendarFile | None, d: dict[str, Any]) -> Any:
    result = validate_calendar(d["definition"], d["context"])
    errors = [] if isinstance(result, CompiledCalendar) else [e.as_json() for e in result]
    return {"errors": errors}


# Inputs named n/a/b are deliberately parsed without validation (they may be out of range).
HANDLERS: dict[str, Handler] = {
    "parse_moment": lambda _, d: {"value": str(numbers.parse_moment(d["text"]))},
    "parse_signed": lambda _, d: {"value": str(numbers.parse_signed(d["text"]))},
    "format_moment": lambda _, d: {"text": numbers.format_moment(int(d["n"]))},
    "format_signed": lambda _, d: {"text": numbers.format_signed(int(d["n"]))},
    "sortable_key": lambda _, d: {"key": numbers.sortable_key(int(d["n"]))},
    "from_sortable_key": lambda _, d: {"n": str(numbers.from_sortable_key(d["key"]))},
    "floor_div": lambda _, d: {"value": str(numbers.floor_div(int(d["a"]), int(d["b"])))},
    "floor_mod": lambda _, d: {"value": str(numbers.floor_mod(int(d["a"]), int(d["b"])))},
    "rational_normalize": lambda _, d: numbers.format_rational(_rational(d)),
    "rational_from_int": lambda _, d: numbers.format_rational(
        numbers.rational_from_int(int(d["n"]))
    ),
    "rational_add": _binary(lambda a, b: a + b),
    "rational_sub": _binary(lambda a, b: a - b),
    "rational_mul": _binary(lambda a, b: a * b),
    "rational_div": _binary(numbers.rational_div),
    "rational_compare": lambda _, d: {
        "value": numbers.rational_compare(_rational(d["a"]), _rational(d["b"]))
    },
    "rational_floor": lambda _, d: {"value": str(numbers.rational_floor(_rational(d["a"])))},
    "rational_frac": lambda _, d: numbers.format_rational(numbers.rational_frac(_rational(d["a"]))),
    "format_integer": _format_integer,
    "validate": _validate,
    "to_fields": lambda c, d: to_fields(_compiled(c), int(d["t"])).as_json(),
    "from_fields": _from_fields,
    "unit_bounds": lambda c, d: _bounds(unit_bounds(_compiled(c), int(d["t"]), d["level"])),
    "ordinal": _ordinal,
    "cycle_value": _cycle_value,
    "era_of": _era_of,
    "from_ordinal": lambda c, d: _bounds(from_ordinal(_compiled(c), d["level"], int(d["ordinal"]))),
    "options": lambda c, d: {
        "options": options_json(options(_compiled(c), d["fields"], d["level"]))
    },
}
"""op → engine call returning the result in the README's JSON shape (errors as ``{"error": …}``)."""

PENDING: dict[str, int] = {
    "overlay_phase": 15,
    "add": 16,
    "diff": 16,
    "format": 17,
    "format_span": 17,
    "preset_instantiate": 18,
    "expand": 19,
    "series_bounds": 19,
    "occurrence": 19,
    "count_in_window": 21,
    "map": 22,
}
"""op → issue that implements it in the Python engine."""

CASE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CASE_KEYS = {"id", "op", "input", "expected"}
FILE_KEYS = {"description", "calendar", "generated", "verification", "cases"}


@dataclass(frozen=True)
class Case:
    name: str
    calendar: str | None
    op: str
    input: dict[str, Any]
    expected: Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _calendar_files() -> dict[str, CalendarFile]:
    return {
        path.stem: _load(path) for path in sorted((CONFORMANCE_DIR / "calendars").glob("*.json"))
    }


def _case_files() -> dict[str, dict[str, Any]]:
    root = CONFORMANCE_DIR / "cases"
    return {
        path.relative_to(root).with_suffix("").as_posix(): _load(path)
        for path in sorted(root.rglob("*.json"))
    }


def _cases() -> list[Case]:
    return [
        Case(
            f"{file}::{case['id']}",
            document["calendar"],
            case["op"],
            case["input"],
            case["expected"],
        )
        for file, document in _case_files().items()
        for case in document["cases"]
    ]


CALENDARS = _calendar_files()
CASES = _cases()


def _not_implemented(calendar: CalendarFile | None, data: dict[str, Any]) -> Any:
    raise NotImplementedError


def _param(case: Case) -> Any:
    marks = []
    if case.op in PENDING:
        marks.append(
            pytest.mark.xfail(
                strict=True,
                raises=NotImplementedError,
                reason=f"{case.op} is implemented by #{PENDING[case.op]}",
            )
        )
    return pytest.param(case, id=case.name, marks=marks)


@pytest.mark.parametrize("case", [_param(case) for case in CASES])
def test_vector(case: Case) -> None:
    calendar = CALENDARS[case.calendar] if case.calendar is not None else None
    handler = HANDLERS.get(case.op, _not_implemented)
    try:
        result = handler(calendar, case.input)
    except (numbers.NumberError, DateError) as error:
        result = {"error": error.code}
    assert _normalized(case.op, result) == _normalized(case.op, case.expected)


def _normalized(op: str, value: Any) -> Any:
    """``validate`` errors compare as a set of (code, path) pairs (README)."""
    if op == "validate" and isinstance(value, dict) and isinstance(value.get("errors"), list):
        return {"errors": sorted(value["errors"], key=lambda e: (e["path"], e["code"]))}
    return value


# --- suite integrity (always executed) -----------------------------------------------------------


def test_every_op_is_handled_or_pending() -> None:
    assert HANDLERS.keys() | PENDING.keys() == OPS
    assert not HANDLERS.keys() & PENDING.keys()


def test_vectors_are_discovered() -> None:
    files = sorted((CONFORMANCE_DIR / "cases").rglob("*.json"))
    assert files, "no case files found"
    assert len(CASES) == sum(len(_load(path)["cases"]) for path in files)
    assert len(CALENDARS) == len(list((CONFORMANCE_DIR / "calendars").glob("*.json")))


def test_no_stray_files() -> None:
    allowed = {CONFORMANCE_DIR / "README.md"}
    for path in CONFORMANCE_DIR.rglob("*"):
        if path.is_file() and path not in allowed:
            assert path.suffix == ".json", f"unexpected file {path}"
            assert path.parent.name == "calendars" or "cases" in path.parts, path


@pytest.mark.parametrize("name", sorted(CALENDARS))
def test_calendar_file_is_schema_valid(name: str) -> None:
    calendar = CALENDARS[name]
    assert set(calendar) == {"description", "definition", "context"}
    CalendarDefinition.model_validate(calendar["definition"])
    CompileContext.model_validate(calendar["context"])


@pytest.mark.parametrize("file", sorted(_case_files()))
def test_case_file_shape(file: str) -> None:
    document = _case_files()[file]
    assert set(document) == FILE_KEYS
    assert isinstance(document["generated"], bool)
    calendar = document["calendar"]
    assert calendar is None or calendar in CALENDARS, f"unknown calendar {calendar!r}"
    ids = [case["id"] for case in document["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in document["cases"]:
        assert CASE_KEYS <= case.keys() <= CASE_KEYS | {"note"}, case
        assert CASE_ID.fullmatch(case["id"]), case["id"]
        assert case["op"] in OPS, f"unknown op {case['op']!r}"
        assert isinstance(case["input"], dict)
        if calendar is None:
            assert case["op"] in CALENDAR_FREE_OPS | {
                "expand",
                "series_bounds",
                "occurrence",
                "count_in_window",
            }
