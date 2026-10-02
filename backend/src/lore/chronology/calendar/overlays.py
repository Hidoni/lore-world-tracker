"""Overlays: astronomical cycles shown alongside dates (``chronology-engine.md`` §3.9, §8).

An overlay never affects the date structure. Its phase at ``t`` is the exact rational
``frac((t - epoch) / period)`` in ``[0, 1)``; the phase name is the last phase whose ``from`` is
at most that value. Everything is exact (``fractions.Fraction``), whatever the magnitudes.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction

from lore.chronology.calendar.compiled import CompiledCalendar, DateError
from lore.chronology.numbers import Rational, format_rational
from lore.chronology.schema import Overlay


@dataclass(frozen=True, slots=True)
class OverlayValue:
    phase: Rational
    """``0 ≤ phase < 1``."""
    name: str

    def as_json(self) -> dict[str, object]:
        return {"phase": format_rational(self.phase), "name": self.name}


def _overlay(calendar: CompiledCalendar, overlay_id: str) -> tuple[Overlay, int]:
    """The overlay with its resolved epoch; ``unknown_overlay`` if the calendar has none."""
    for overlay, epoch in zip(calendar.definition.overlays, calendar.overlay_epochs, strict=True):
        if overlay.id == overlay_id:
            return overlay, epoch
    raise DateError("unknown_overlay", f"no overlay {overlay_id!r}")


def _period(overlay: Overlay) -> Fraction:
    num, den = overlay.period.as_pair()
    return Fraction(num, den)


def _value(overlay: Overlay, epoch: int, t: int) -> OverlayValue:
    turns = (t - epoch) / _period(overlay)
    phase = turns - math.floor(turns)
    starts = [Fraction(*p.from_.as_pair()) for p in overlay.phases]
    return OverlayValue(phase, overlay.phases[bisect_right(starts, phase) - 1].name)


def overlay_phase(calendar: CompiledCalendar, t: int, overlay_id: str) -> OverlayValue:
    """§8 ``overlay_phase``: the overlay's exact phase at ``t`` and its name."""
    overlay, epoch = _overlay(calendar, overlay_id)
    return _value(overlay, epoch, t)


def overlay_values(calendar: CompiledCalendar, t: int) -> dict[str, OverlayValue]:
    """Every overlay's value at ``t`` (the ``overlays`` member of ``to_fields``)."""
    return {
        overlay.id: _value(overlay, epoch, t)
        for overlay, epoch in zip(
            calendar.definition.overlays, calendar.overlay_epochs, strict=True
        )
    }


def next_phase_at(calendar: CompiledCalendar, t: int, overlay_id: str, phase: Rational) -> int:
    """§8 ``next_phase_at``: the first moment ``≥ t`` at which the overlay reaches ``phase``.

    The overlay is at ``phase`` at the exact instants ``x(n) = epoch + (n + phase)·period``;
    the result is ``ceil(x(n))`` for the smallest ``n`` with ``ceil(x(n)) ≥ t`` (the moment
    itself when ``x(n)`` is an integer, else the first moment after it). ``phase`` must lie in
    ``[0, 1)`` (``invalid_date`` otherwise).
    """
    overlay, epoch = _overlay(calendar, overlay_id)
    if not 0 <= phase < 1:
        raise DateError("invalid_date", "a phase lies in [0, 1)")
    period = _period(overlay)
    # ceil(x(n)) >= t  <=>  x(n) > t - 1  <=>  n > (t - 1 - epoch) / period - phase
    n = math.floor((t - 1 - epoch) / period - phase) + 1
    return math.ceil(epoch + (n + phase) * period)
