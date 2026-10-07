"""Precision-aware comparisons (``consistency.md`` §4). Every rule comparing time points uses
these, so "definite" and "possible" mean the same everywhere.

A point is its stored moment ``t``, its uncertainty extent ``[lo, hi)`` (``time-model.md`` §5.3)
and its circa flag. For a required relation ``a ≤ b``:

- **definite** violation: ``lo(a) ≥ hi(b)`` (even the earliest ``a`` is after the latest ``b``)
  and neither point is approximate;
- **possible** violation: not definite, but ``t(a) > t(b)``, or the condition above holds with
  an approximate point;
- otherwise none.

Either kind implies ``t(a) > t(b)`` (``lo(a) = t(a)`` and ``hi(b) > t(b)``), so scans may select
candidates on stored moments in SQL and compare extents only for those.
"""

from dataclasses import dataclass
from typing import Literal

from lore.core.time.resolve import Resolution

type Certainty = Literal["definite", "possible"]
DEFINITE: Certainty = "definite"
POSSIBLE: Certainty = "possible"


@dataclass(frozen=True)
class Point:
    t: int
    lo: int
    hi: int
    approximate: bool = False

    @classmethod
    def exact(cls, t: int, *, approximate: bool = False) -> Point:
        return cls(t, t, t + 1, approximate)

    @classmethod
    def of(cls, resolution: Resolution) -> Point | None:
        """A resolved slot (``Resolver.slot``) as a point; ``None`` without a moment."""
        if resolution.t is None:
            return None
        lo, hi = resolution.extent or (resolution.t, resolution.t + 1)
        return cls(resolution.t, lo, hi, resolution.approximate)


def violates_order(a: Point, b: Point) -> Certainty | None:
    """How certainly ``a ≤ b`` is violated (``None``: it holds, or may)."""
    if a.lo >= b.hi:
        return POSSIBLE if a.approximate or b.approximate else DEFINITE
    if a.t > b.t:
        return POSSIBLE
    return None


def worst(*found: Certainty | None) -> Certainty | None:
    """The most certain of several violations."""
    if DEFINITE in found:
        return DEFINITE
    return POSSIBLE if POSSIBLE in found else None


__all__ = ["DEFINITE", "POSSIBLE", "Certainty", "Point", "violates_order", "worst"]
