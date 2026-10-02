"""Overlays: exact phases and next_phase_at (chronology-engine.md §3.9, §8)."""

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    next_phase_at,
    overlay_phase,
    to_fields,
    validate_calendar,
)

CONFORMANCE = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "conformance"


def compiled(name: str) -> CompiledCalendar:
    document: dict[str, Any] = json.loads((CONFORMANCE / "calendars" / f"{name}.json").read_text())
    result = validate_calendar(document["definition"], document["context"])
    assert isinstance(result, CompiledCalendar), result
    return result


MOON = compiled("gregorian-moon")
PERIODS = {"moon": Fraction(25514428, 10), "seasons": Fraction(31556925216, 1000)}
phases = st.one_of(
    st.sampled_from([Fraction(0), Fraction(7, 16), Fraction(1, 4), Fraction(15, 16)]),
    st.fractions(min_value=0, max_value=Fraction(999_999, 1_000_000), max_denominator=10**9),
)
moments = st.one_of(st.integers(0, 10**16), st.integers(0, 10**120))


@given(st.sampled_from(["moon", "seasons"]), moments, phases)
def test_next_phase_at_reaches_the_phase(overlay: str, t: int, phase: Fraction) -> None:
    """At the result the phase is exactly ``phase``, or the result is the first moment after the
    exact instant (the ceil rule); no earlier instant at or after ``t`` qualifies."""
    found = next_phase_at(MOON, t, overlay, phase)
    assert found >= t
    period = PERIODS[overlay]
    reached = overlay_phase(MOON, found, overlay).phase
    late = (reached - phase) % 1  # how far past the exact instant, in turns
    assert late * period < 1
    if late == 0:
        assert reached == phase
    instant = found - late * period
    assert math.ceil(instant - period) < t  # the previous instant was before t
    assert next_phase_at(MOON, found, overlay, phase) == found


@given(st.sampled_from(["moon", "seasons"]), moments)
def test_phases_are_in_range_and_named(overlay: str, t: int) -> None:
    value = overlay_phase(MOON, t, overlay)
    assert 0 <= value.phase < 1
    assert value.name
    assert to_fields(MOON, t).as_json()["overlays"][overlay] == value.as_json()  # type: ignore[index]


def test_phase_names_follow_the_last_start() -> None:
    epoch = 100000000497640
    assert overlay_phase(MOON, epoch, "moon").name == "New Moon"
    assert overlay_phase(MOON, epoch - 1, "moon").name == "New Moon"  # from 15/16
    assert overlay_phase(MOON, epoch + 3 * 86400, "moon").name == "Waxing Crescent"


def test_errors() -> None:
    with pytest.raises(DateError) as raised:
        overlay_phase(MOON, 0, "sun")
    assert raised.value.code == "unknown_overlay"
    with pytest.raises(DateError) as raised:
        next_phase_at(MOON, 0, "moon", Fraction(1))
    assert raised.value.code == "invalid_date"


def test_calendars_without_overlays() -> None:
    plain = compiled("gregorian-seconds")
    assert to_fields(plain, 0).as_json()["overlays"] == {}
    with pytest.raises(DateError):
        overlay_phase(plain, 0, "moon")
