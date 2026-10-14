"""Correspondences between dimensions (``time-model.md`` §12, D7): reading the stored sync points
through the chronology engine, the graph of dimensions they connect, and mapping moments along
its shortest paths. The correspondences module is the API; the tables, the ``sync_point`` slots
and the hard rule ``core.correspondence.non_monotonic`` are core.

- A correspondence compiles from its sync points once both sides resolved
  (``lore.chronology.correspondence``); points not strictly increasing in both dimensions are
  ``correspondence.non_monotonic``.
- Readers map through the correspondences they see (``CORRESPONDENCE_VISIBILITY``: its own
  visibility and both dimensions).
- ``map`` composes along the shortest path (fewest correspondences; ties go to the smallest
  correspondence ids), flooring at each step. Correspondences apply to every timeline.
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lore.chronology.correspondence import (
    Correspondence as Compiled,
)
from lore.chronology.correspondence import (
    CorrespondenceError,
    Direction,
    Step,
    compose,
    correspondence,
)
from lore.core.entities.models import Entity
from lore.core.time.models import Correspondence, CorrespondencePoint, Dimension
from lore.core.visibility import AUTHOR, VisibilityFilter, VisibilityPolicy

CORRESPONDENCE_VISIBILITY = VisibilityFilter(
    Correspondence, entity_columns=("dimension_a_id", "dimension_b_id")
)


def rate_of(value: Any) -> Fraction | None:
    """A stored rate (``{"num", "den"}``) as an exact fraction."""
    if not isinstance(value, dict):
        return None
    return Fraction(int(value["num"]), int(value["den"]))


def points_of(session: Session, ids: Iterable[str]) -> dict[str, list[CorrespondencePoint]]:
    """The sync points of correspondences, in the order given."""
    wanted = sorted(set(ids))
    found: dict[str, list[CorrespondencePoint]] = {i: [] for i in wanted}
    if not wanted:
        return found
    rows = session.scalars(
        select(CorrespondencePoint)
        .where(CorrespondencePoint.correspondence_id.in_(wanted))
        .order_by(CorrespondencePoint.correspondence_id, CorrespondencePoint.position)
    )
    for point in rows:
        found[point.correspondence_id].append(point)
    return found


def compile_rows(row: Correspondence, points: Sequence[CorrespondencePoint]) -> Compiled | None:
    """The engine's correspondence for stored rows (``None`` while a sync point is unresolved);
    raises ``CorrespondenceError`` (paths ``/points/<i>`` in the order given)."""
    resolved = [(p.a_t, p.b_t) for p in points]
    if not resolved or any(a is None or b is None for a, b in resolved):
        return None
    return correspondence(
        [(int(a), int(b)) for a, b in resolved if a is not None and b is not None],
        extrapolation="rate" if row.extrapolation == "rate" else "none",
        rate_before=rate_of(row.rate_before),
        rate_after=rate_of(row.rate_after),
    )


# --- the graph ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    """A correspondence seen from one of its dimensions."""

    correspondence_id: str
    target: str
    direction: Direction


@dataclass
class MapResult:
    t: int | None
    path: list[str]
    """The correspondences used, in order (empty: no path, or the same dimension)."""

    @property
    def defined(self) -> bool:
        return self.t is not None


@dataclass
class CorrespondenceGraph:
    """The live correspondences a request sees, compiled, and the dimensions they connect."""

    compiled: dict[str, Compiled]
    rows: dict[str, Correspondence]
    durations: dict[str, int]
    edges: dict[str, list[Edge]] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        session: Session,
        policy: VisibilityPolicy = AUTHOR,
        *,
        dimension_ids: Iterable[str] | None = None,
    ) -> CorrespondenceGraph:
        """Every live correspondence (of ``dimension_ids`` when given) that compiles."""
        statement = select(Correspondence).where(
            Correspondence.deleted_at.is_(None),
            *policy.module_rows(CORRESPONDENCE_VISIBILITY),
        )
        if dimension_ids is not None:
            ids = list(dimension_ids)
            statement = statement.where(
                or_(Correspondence.dimension_a_id.in_(ids), Correspondence.dimension_b_id.in_(ids))
            )
        rows = {row.id: row for row in session.scalars(statement.order_by(Correspondence.id))}
        live_dimensions = set(
            session.scalars(
                select(Entity.id).where(
                    Entity.id.in_({d for r in rows.values() for d in _ends(r)}),
                    Entity.deleted_at.is_(None),
                )
            )
        )
        points = points_of(session, rows)
        compiled: dict[str, Compiled] = {}
        for row_id, row in rows.items():
            if not set(_ends(row)) <= live_dimensions:
                continue
            try:
                found = compile_rows(row, points[row_id])
            except CorrespondenceError:
                continue
            if found is not None:
                compiled[row_id] = found
        durations = dict(
            session.execute(
                select(Dimension.entity_id, Dimension.duration).where(
                    Dimension.entity_id.in_(live_dimensions)
                )
            ).all()
        )
        graph = cls(compiled, {i: rows[i] for i in compiled}, durations)
        for row_id in sorted(compiled):
            row = rows[row_id]
            graph.edges.setdefault(row.dimension_a_id, []).append(
                Edge(row_id, row.dimension_b_id, "ab")
            )
            graph.edges.setdefault(row.dimension_b_id, []).append(
                Edge(row_id, row.dimension_a_id, "ba")
            )
        return graph

    def path(self, source: str, target: str, *, without: str | None = None) -> list[Edge] | None:
        """The shortest path (fewest correspondences, then the smallest ids), optionally avoiding
        one correspondence; ``[]`` from a dimension to itself, ``None`` when unconnected."""
        if source == target:
            return []
        previous: dict[str, tuple[str, Edge]] = {}
        queue = deque([source])
        seen = {source}
        while queue:
            current = queue.popleft()
            for edge in self.edges.get(current, []):
                if edge.correspondence_id == without or edge.target in seen:
                    continue
                seen.add(edge.target)
                previous[edge.target] = (current, edge)
                if edge.target == target:
                    found: list[Edge] = []
                    node = target
                    while node != source:
                        node, step = previous[node]
                        found.append(step)
                    return list(reversed(found))
                queue.append(edge.target)
        return None

    def steps(self, path: Sequence[Edge]) -> list[Step]:
        return [
            Step(self.compiled[e.correspondence_id], e.direction, self.durations[e.target])
            for e in path
        ]

    def map(self, source: str, target: str, t: int) -> MapResult:
        """§12.3: ``t`` of ``source`` mapped to ``target`` along the shortest path."""
        path = self.path(source, target)
        if path is None:
            return MapResult(None, [])
        if source == target:
            within = 0 <= t <= self.durations.get(source, t)
            return MapResult(t if within else None, [])
        return MapResult(compose(self.steps(path), t), [e.correspondence_id for e in path])

    def exact(self, path: Sequence[Edge], t: int) -> Fraction | None:
        """The unfloored image of ``t`` along ``path`` (``None`` where a step is undefined): the
        inconsistent-paths check compares paths without their rounding."""
        current: Fraction | None = Fraction(t)
        for edge in path:
            if current is None:
                return None
            current = exact_map(
                self.compiled[edge.correspondence_id],
                current,
                edge.direction,
                self.durations[edge.target],
            )
        return current


def _ends(row: Correspondence) -> tuple[str, str]:
    return (row.dimension_a_id, row.dimension_b_id)


def exact_map(
    compiled: Compiled, x: Fraction, direction: Direction, target_duration: int
) -> Fraction | None:
    """``Compiled.map`` without flooring (§12.2): the exact image, ``None`` outside the mapping
    or the target's ``[0, D]``."""
    points = compiled.points if direction == "ab" else tuple((b, a) for a, b in compiled.points)
    before, after = compiled.rate_before, compiled.rate_after
    if direction == "ba":
        before = None if before is None else 1 / before
        after = None if after is None else 1 / after
    (first_x, first_y), (last_x, last_y) = points[0], points[-1]
    if x < first_x:
        if not compiled.extrapolate or before is None:
            return None
        y = first_y + (x - first_x) * Fraction(before)
    elif x > last_x:
        if not compiled.extrapolate or after is None:
            return None
        y = last_y + (x - last_x) * Fraction(after)
    elif len(points) == 1:
        y = Fraction(first_y)
    else:
        i = max(j for j in range(len(points) - 1) if points[j][0] <= x)
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        y = y0 + (x - x0) * Fraction(y1 - y0, x1 - x0)
    return y if 0 <= y <= target_duration else None


# --- the hard rule ------------------------------------------------------------------------------


@dataclass
class OrderProblem:
    """A live correspondence whose resolved sync points don't increase in both dimensions."""

    correspondence: Correspondence
    message: str
    data: dict[str, Any]


def order_problems(session: Session, dimension_ids: Iterable[str] | None) -> list[OrderProblem]:
    """``core.correspondence.non_monotonic``: the live correspondences (of the dimensions) whose
    resolved sync points are not strictly increasing in both dimensions."""
    statement = select(Correspondence).where(Correspondence.deleted_at.is_(None))
    if dimension_ids is not None:
        ids = list(dimension_ids)
        statement = statement.where(
            or_(Correspondence.dimension_a_id.in_(ids), Correspondence.dimension_b_id.in_(ids))
        )
    rows = list(session.scalars(statement.order_by(Correspondence.id)))
    points = points_of(session, [row.id for row in rows])
    problems: list[OrderProblem] = []
    for row in rows:
        try:
            compile_rows(row, points[row.id])
        except CorrespondenceError as error:
            bad = [e for e in error.errors if e.code == "correspondence.non_monotonic"]
            if bad:
                problems.append(
                    OrderProblem(
                        row,
                        f"The sync points of “{row.name}” don't move forward in both dimensions "
                        "together: time would run backwards in one of them.",
                        {
                            "correspondence_id": row.id,
                            "points": [int(e.path.rsplit("/", 1)[-1]) for e in bad],
                        },
                    )
                )
    return problems


__all__ = [
    "CORRESPONDENCE_VISIBILITY",
    "CorrespondenceGraph",
    "Edge",
    "MapResult",
    "OrderProblem",
    "compile_rows",
    "exact_map",
    "order_problems",
    "points_of",
    "rate_of",
]
