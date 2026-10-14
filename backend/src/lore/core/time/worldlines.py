"""Worldlines (personal timelines, ``time-model.md`` §11, D7): the time-bound registration of
``worldline_segments`` and the exact subjective-time math. The worldlines module is the API.

- Subjective time is measured in base units of the entity's **personal clock dimension** (its
  home dimension, or segment 1's for a multiversal entity). ``subj_start(seg_1) = 0`` and each
  segment adds ``(end - start) * rate``; a moment inside a segment is ``subj_start + (t -
  start) * rate``. All of it is exact (``Fraction``); displays floor.
- A segment covers ``t`` when ``start ≤ t ≤ end`` (both ends: a jump's departure and arrival
  moments belong to their segments).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from lore.core.time.models import WorldlineSegment
from lore.core.time.timeline_view import TimeBound, register_time_bound

register_time_bound(TimeBound(WorldlineSegment, start="start_t", end="end_t"))

ONE = {"num": "1", "den": "1"}


def rate_of(value: Any) -> Fraction:
    """A stored rate (``{"num", "den"}``; missing: 1)."""
    if not isinstance(value, dict):
        return Fraction(1)
    return Fraction(int(value["num"]), int(value["den"]))


@dataclass(frozen=True)
class Span:
    """A resolved segment: what the math needs."""

    id: str | None
    dimension_id: str
    timeline_id: str | None
    start: int
    end: int
    rate: Fraction

    def covers(self, t: int) -> bool:
        return self.start <= t <= self.end


def subjective_starts(spans: Sequence[Span]) -> list[Fraction]:
    """``subj_start`` of each span, in worldline order (§11.3)."""
    starts: list[Fraction] = []
    current = Fraction(0)
    for span in spans:
        starts.append(current)
        current += (span.end - span.start) * span.rate
    return starts


def subjective_at(span: Span, start: Fraction, t: int) -> Fraction:
    """The subjective time at world moment ``t`` of ``span`` (whose subjective start is
    ``start``)."""
    return start + (t - span.start) * span.rate


__all__ = ["ONE", "Span", "rate_of", "subjective_at", "subjective_starts"]
