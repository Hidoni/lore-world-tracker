"""Differential tests: random calendars and ops, run by both engines, must give equal results.

The conformance vectors cover the cases someone thought of; this suite looks for drift between
the Python and TypeScript engines everywhere else (chronology-engine.md §14, testing.md §6). Each
op goes to the Python engine (``tests.chronology.ops``) and to the TypeScript engine through the
Node CLI ``packages/chronology/bin/chrono-exec.ts``. Results are compared exactly, like vectors.

Run with ``make test-differential``. ``DIFFERENTIAL_CASES`` sets the number of cases (default 200;
CI: 1,000 on chronology changes, 10,000 nightly); ``DIFFERENTIAL_RANDOM=1`` explores new examples
instead of the fixed derandomized ones. A discrepancy is reported as a ready-made conformance case:
add it to a case file (with its calendar), then fix the engine that is wrong.
"""

import json
import os
import subprocess
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.chronology.differential.strategies import (
    Calendar,
    Json,
    calendar_ops,
    calendars,
    compile_document,
    correspondence_ops,
    corrupted,
    interval_ops,
    number_ops,
)
from tests.chronology.ops import run_op

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "chronology"
CASES = int(os.environ.get("DIFFERENTIAL_CASES", "200"))
OPS_PER_EXAMPLE = 10


# 70% of the cases on random calendars (`validate` on it and on a corrupted copy, plus
# OPS_PER_EXAMPLE ops),
# 10% each on interval rules, correspondences and numbers.
def _settings(share: float) -> settings:
    return settings(
        max_examples=max(1, round(CASES * share / OPS_PER_EXAMPLE)),
        deadline=None,
        derandomize=os.environ.get("DIFFERENTIAL_RANDOM") != "1",
        print_blob=True,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )


class NodeEngine:
    """The TypeScript engine in a Node process speaking chrono-exec's JSON lines."""

    def __init__(self, bundle: Path) -> None:
        self.process = subprocess.Popen(
            ["node", str(bundle)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def run(self, op: str, calendar: Json | None, data: Json) -> Json:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        request = {"op": op, "calendar": calendar, "input": data}
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"chrono-exec exited with {self.process.wait()}")
        answer: Json = json.loads(line)
        return answer

    def close(self) -> None:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.close()
        self.process.wait(timeout=10)
        self.process.stdout.close()


@pytest.fixture(scope="module")
def node() -> Iterator[NodeEngine]:
    """Bundle the CLI (so it always matches the source), then start one Node process."""
    subprocess.run(["node", "scripts/build-exec.ts"], cwd=PACKAGE, check=True)
    engine = NodeEngine(PACKAGE / "dist" / "chrono-exec.mjs")
    yield engine
    engine.close()
    summary = ", ".join(f"{op} {count}" for op, count in CHECKED.most_common())
    print(f"\ndifferential: {CHECKED.total() - CHECKED['error']} cases ({summary})")


def _python(op: str, calendar: Json | None, data: Json) -> Json:
    try:
        result = run_op(op, calendar, data)
    except Exception as error:  # a crash of the Python engine is a finding too
        return {"crash": f"{type(error).__name__}: {error}"}
    # Through JSON, like the Node side (tuples become lists).
    answer: Json = json.loads(json.dumps({"result": result}))
    return answer


def _normalized(op: str, answer: Json) -> Any:
    """``validate`` errors compare as a set of (code, path) pairs (conformance README)."""
    result = answer.get("result")
    if op == "validate" and isinstance(result, dict) and isinstance(result.get("errors"), list):
        errors = sorted((e["code"], e["path"]) for e in result["errors"])
        return {"result": {"errors": errors}}
    return answer


CHECKED: Counter[str] = Counter()
"""Cases run so far, by op (and `error` for results that are errors), for the summary."""


def check(node: NodeEngine, op: str, calendar: Json | None, data: Json) -> None:
    """Run one case on both engines; fail with a ready-made conformance case on a mismatch."""
    CHECKED[op] += 1
    python = _python(op, calendar, data)
    typescript = node.run(op, calendar, data)
    if "crash" not in python and _normalized(op, python) == _normalized(op, typescript):
        result = python["result"]
        if isinstance(result, dict) and "error" in result:
            CHECKED["error"] += 1
        return
    case = {"id": "differential-<describe-it>", "op": op, "input": data}
    report = {
        "python": python,
        "typescript": typescript,
        "case": case,
        "calendar": calendar,
    }
    pytest.fail(
        "the engines disagree (or one crashed). Add `case` to a conformance case file (with "
        "`calendar` as a calendar file when it has one), set `expected` from the spec, and fix "
        "the engine that is wrong:\n" + json.dumps(report, indent=2),
        pytrace=False,
    )


@_settings(0.7)
@given(data=st.data())
def test_calendars(node: NodeEngine, data: st.DataObject) -> None:
    document = data.draw(calendars(), label="calendar")
    check(node, "validate", None, document)
    check(node, "validate", None, data.draw(corrupted(document), label="corrupted"))
    if compile_document(document) is None:
        return
    calendar = Calendar(document)
    for _ in range(OPS_PER_EXAMPLE):
        case = data.draw(calendar_ops(calendar))
        check(node, case["op"], document, case["input"])


@_settings(0.1)
@given(cases=st.lists(interval_ops(), min_size=OPS_PER_EXAMPLE, max_size=OPS_PER_EXAMPLE))
def test_interval_rules(node: NodeEngine, cases: list[Json]) -> None:
    for case in cases:
        check(node, case["op"], None, case["input"])


@_settings(0.1)
@given(cases=st.lists(correspondence_ops(), min_size=OPS_PER_EXAMPLE, max_size=OPS_PER_EXAMPLE))
def test_correspondences(node: NodeEngine, cases: list[Json]) -> None:
    for case in cases:
        check(node, case["op"], None, case["input"])


@_settings(0.1)
@given(cases=st.lists(number_ops(), min_size=OPS_PER_EXAMPLE, max_size=OPS_PER_EXAMPLE))
def test_numbers(node: NodeEngine, cases: list[Json]) -> None:
    for case in cases:
        check(node, case["op"], None, case["input"])
