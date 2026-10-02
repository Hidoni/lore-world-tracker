"""Correspondence mapping (time-model.md §12)."""

from fractions import Fraction
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.correspondence import (
    Correspondence,
    CorrespondenceError,
    Step,
    compile_correspondence,
    compose,
    correspondence,
)
from lore.chronology.schema import CorrespondenceDef

D = 10**40


@st.composite
def correspondences(draw: st.DrawFn) -> Correspondence:
    """Random strictly increasing sync points (2-6), extrapolating by default or random rates."""
    count = draw(st.integers(2, 6))
    a_steps = draw(st.lists(st.integers(1, 10**9), min_size=count, max_size=count))
    b_steps = draw(st.lists(st.integers(1, 10**12), min_size=count, max_size=count))
    a0 = draw(st.integers(10**12, 10**15))
    b0 = draw(st.integers(10**15, 10**18))
    points = list(zip(_cumulative(a0, a_steps), _cumulative(b0, b_steps), strict=True))
    rates = st.none() | st.fractions(min_value=Fraction(1, 10**6), max_value=10**6)
    return correspondence(
        points, extrapolation="rate", rate_before=draw(rates), rate_after=draw(rates)
    )


def _cumulative(start: int, steps: list[int]) -> list[int]:
    values = [start]
    for step in steps[1:]:
        values.append(values[-1] + step)
    return values


def _slopes(found: Correspondence) -> list[Fraction]:
    """Every slope the mapping uses (B units per A unit)."""
    pts = found.points
    slopes = [Fraction(b1 - b0, a1 - a0) for (a0, b0), (a1, b1) in pairwise(pts)]
    assert found.rate_before is not None
    assert found.rate_after is not None
    return [*slopes, found.rate_before, found.rate_after]


@given(correspondences(), st.integers(0, 10**20), st.integers(0, 10**12))
def test_mapping_is_monotonic(found: Correspondence, t: int, step: int) -> None:
    for direction in ("ab", "ba"):
        low, high = found.map(t, direction, D), found.map(t + step, direction, D)
        if low is not None and high is not None:
            assert low <= high


@given(correspondences(), st.integers(0, 10**20))
def test_round_trips_stay_close(found: Correspondence, a: int) -> None:
    """A → B → A lands at or before ``a``, by less than one B unit (``1/slope`` A units) plus one
    A unit: both directions floor."""
    b = found.map(a, "ab", D)
    if b is None:
        return
    back = found.map(b, "ba", D)
    worst = max(1 / s for s in _slopes(found))
    if back is None:  # below 0, outside A's bounds: only possible right after A's inception
        assert a < 1 + worst
        return
    assert back <= a
    assert a - back < 1 + worst
    again = found.map(back, "ab", D)  # mapping the round trip again lands back on b or below
    assert again is not None
    assert again <= b


def test_round_trip_example() -> None:
    """Slope 5/2: 1 → 2 → 0, off by one A unit (less than one B unit plus one A unit)."""
    found = correspondence([(0, 0), (2, 5)])
    assert found.map(1, "ab", D) == 2
    assert found.map(2, "ba", D) == 0


def test_compile_from_a_document() -> None:
    definition = CorrespondenceDef.model_validate(
        {
            "extrapolation": "rate",
            "rate_after": {"num": "365", "den": "1"},
            "rate_before": {"num": "365", "den": "1"},
            "points": [
                {
                    "a": {"anchor": {"kind": "absolute", "t": "0"}, "precision": "base"},
                    "b": {"anchor": {"kind": "absolute", "t": "0"}, "precision": "base"},
                }
            ],
        }
    )
    found = compile_correspondence(definition, {"/points/0/a": 1000, "/points/0/b": 7})
    assert found.map(1001, "ab", D) == 372
    assert found.map(372, "ba", D) == 1001


def test_validation_reports_every_error() -> None:
    with pytest.raises(CorrespondenceError) as raised:
        correspondence([(10, 5), (20, 5), (30, 1)], rate_before=Fraction(-1))
    assert [(e.code, e.path) for e in raised.value.errors] == [
        ("correspondence.non_monotonic", "/points/1"),
        ("correspondence.non_monotonic", "/points/2"),
        ("correspondence.bad_rate", "/rate_before"),
    ]
    with pytest.raises(CorrespondenceError) as raised:
        correspondence([(10, 5)], extrapolation="rate")
    assert [e.path for e in raised.value.errors] == ["/rate_before", "/rate_after"]


def test_compose_through_dimensions() -> None:
    seconds_days = correspondence([(0, 0), (8_640_000, 100)], extrapolation="rate")
    days_years = correspondence([(0, 0), (36_500, 100)], extrapolation="rate")
    path = [Step(seconds_days, "ab", D), Step(days_years, "ab", D)]
    assert compose(path, 365 * 86_400 * 3) == 3
    assert compose([Step(days_years, "ba", D), Step(seconds_days, "ba", D)], 3) == 3 * 365 * 86_400
    assert compose([Step(seconds_days, "ab", 10)], 8_640_000) is None  # 100 days > D = 10
    assert compose([], 5) == 5
