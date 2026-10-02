"""Cross-dimension correspondences: mapping moments through sync points (``time-model.md`` §12).

A correspondence relates dimension A to dimension B through resolved sync points ``(a_i, b_i)``,
strictly increasing in both coordinates. Between consecutive points the mapping is linear with an
exact rational slope; outside them it is undefined (``extrapolation: none``) or continues with
``rate_before`` / ``rate_after`` (B units per A unit). Results are floored to whole base units
and must lie in the target dimension's ``[0, D]``; otherwise there is no corresponding moment.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import Literal

from lore.chronology.calendar.compile import ValidationError
from lore.chronology.numbers import Rational
from lore.chronology.schema import CorrespondenceDef
from lore.chronology.schema import Rational as RationalModel

type Direction = Literal["ab", "ba"]


class CorrespondenceError(ValueError):
    """An invalid correspondence; ``code`` is the first error's, ``errors`` lists all."""

    def __init__(self, errors: Sequence[ValidationError]) -> None:
        super().__init__(errors[0].message)
        self.code = errors[0].code
        self.errors = tuple(errors)


@dataclass(frozen=True, slots=True)
class Correspondence:
    """A validated correspondence: points sorted by ``a``, both rates set when extrapolating."""

    points: tuple[tuple[int, int], ...]
    extrapolate: bool
    rate_before: Rational | None
    rate_after: Rational | None

    def map(self, t: int, direction: Direction, target_duration: int) -> int | None:
        """§12.2: the moment corresponding to ``t`` (``map_ab`` or ``map_ba``), or ``None``."""
        if direction == "ab":
            points, before, after = self.points, self.rate_before, self.rate_after
        else:
            points = tuple((b, a) for a, b in self.points)
            before = None if self.rate_before is None else 1 / self.rate_before
            after = None if self.rate_after is None else 1 / self.rate_after
        result = _map(points, before, after, self.extrapolate, t)
        return result if result is not None and 0 <= result <= target_duration else None


def _map(
    points: tuple[tuple[int, int], ...],
    before: Rational | None,
    after: Rational | None,
    extrapolate: bool,
    x: int,
) -> int | None:
    first_x, first_y = points[0]
    last_x, last_y = points[-1]
    if x < first_x:
        if not extrapolate or before is None:
            return None
        return first_y + math.floor((x - first_x) * before)
    if x > last_x:
        if not extrapolate or after is None:
            return None
        return last_y + math.floor((x - last_x) * after)
    i = min(bisect_right([p[0] for p in points], x) - 1, len(points) - 2)
    if i < 0:  # a single point, and x is that point
        return first_y
    (x0, y0), (x1, y1) = points[i], points[i + 1]
    return y0 + (x - x0) * (y1 - y0) // (x1 - x0)


def correspondence(
    points: Sequence[tuple[int, int]],
    *,
    extrapolation: Literal["none", "rate"] = "none",
    rate_before: Rational | None = None,
    rate_after: Rational | None = None,
) -> Correspondence:
    """Validate resolved sync points and rates (§12.1); raises :class:`CorrespondenceError`.

    Errors (paths into the correspondence document): ``correspondence.non_monotonic`` (points,
    sorted by ``a``, not strictly increasing in both ``a`` and ``b``), ``correspondence.bad_rate``
    (a rate ``≤ 0``) and ``correspondence.missing_rate`` (``rate`` extrapolation from a single
    point without that side's rate). Missing rates default to the adjacent segment's slope.
    """
    errors: list[ValidationError] = []
    order = sorted(range(len(points)), key=lambda i: points[i][0])
    for previous, current in pairwise(order):
        (a0, b0), (a1, b1) = points[previous], points[current]
        if not (a0 < a1 and b0 < b1):
            errors.append(
                ValidationError(
                    "correspondence.non_monotonic",
                    f"/points/{current}",
                    "sync points must increase strictly in both dimensions",
                )
            )
    for member, rate in (("rate_before", rate_before), ("rate_after", rate_after)):
        if rate is not None and rate <= 0:
            errors.append(
                ValidationError("correspondence.bad_rate", f"/{member}", "a rate must be positive")
            )
    sorted_points = tuple(points[i] for i in order)
    extrapolate = extrapolation == "rate"
    if extrapolate and len(sorted_points) == 1:
        for member, rate in (("rate_before", rate_before), ("rate_after", rate_after)):
            if rate is None:
                errors.append(
                    ValidationError(
                        "correspondence.missing_rate",
                        f"/{member}",
                        "a single sync point needs explicit rates",
                    )
                )
    if errors:
        raise CorrespondenceError(errors)
    if extrapolate and len(sorted_points) > 1:
        (a0, b0), (a1, b1) = sorted_points[0], sorted_points[1]
        (a2, b2), (a3, b3) = sorted_points[-2], sorted_points[-1]
        rate_before = rate_before if rate_before is not None else Fraction(b1 - b0, a1 - a0)
        rate_after = rate_after if rate_after is not None else Fraction(b3 - b2, a3 - a2)
    return Correspondence(sorted_points, extrapolate, rate_before, rate_after)


def compile_correspondence(
    definition: CorrespondenceDef, resolved: dict[str, int]
) -> Correspondence:
    """A correspondence document with its sync points resolved by the server
    (``resolved["/points/<i>/a"]`` and ``…/b``)."""
    points = [
        (resolved[f"/points/{i}/a"], resolved[f"/points/{i}/b"])
        for i in range(len(definition.points))
    ]

    def rate(value: RationalModel | None) -> Rational | None:
        return None if value is None else Fraction(*value.as_pair())

    return correspondence(
        points,
        extrapolation=definition.extrapolation,
        rate_before=rate(definition.rate_before),
        rate_after=rate(definition.rate_after),
    )


@dataclass(frozen=True, slots=True)
class Step:
    """One leg of a path: a correspondence, the direction to map it and the target's ``D``."""

    correspondence: Correspondence
    direction: Direction
    target_duration: int


def compose(path: Sequence[Step], t: int) -> int | None:
    """§12.3: map ``t`` along ``path``, flooring at every step; ``None`` as soon as a step has
    no corresponding moment. The path itself (e.g. the shortest one) is chosen by the caller."""
    current: int | None = t
    for step in path:
        if current is None:
            return None
        current = step.correspondence.map(current, step.direction, step.target_duration)
    return current
