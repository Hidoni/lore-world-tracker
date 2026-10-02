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

from lore.chronology.schema import CalendarDefinition, CompileContext

CONFORMANCE_DIR = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"

OPS = frozenset(
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

CALENDAR_FREE_OPS = frozenset({"validate", "preset_instantiate", "map"})

type CalendarFile = dict[str, Any]
type Handler = Callable[[CalendarFile | None, dict[str, Any]], Any]

HANDLERS: dict[str, Handler] = {}
"""op → engine call returning the result in the README's JSON shape (errors as ``{"error": …}``)."""

PENDING: dict[str, int] = {
    "validate": 10,
    "to_fields": 11,
    "from_fields": 11,
    "unit_bounds": 12,
    "ordinal": 12,
    "from_ordinal": 12,
    "options": 12,
    "cycle_value": 13,
    "era_of": 14,
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
    assert handler(calendar, case.input) == case.expected


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


def test_validate_vectors_use_schema_valid_definitions() -> None:
    for case in CASES:
        if case.op == "validate":
            CalendarDefinition.model_validate(case.input["definition"])
            CompileContext.model_validate(case.input["context"])
