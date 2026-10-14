"""The correspondences service (``docs/modules/correspondences.md``, ``time-model.md`` §12).

Writes run in the request's transaction: the sync points' specs go through ``TimeWriter`` (they
may be anchored to events of their dimension and move with them), and the resolved points must
compile (``lore.chronology.correspondence``: strictly increasing in both dimensions, positive
rates) or the write is refused. Later moves of an anchor that break the order are refused by the
hard rule ``core.correspondence.non_monotonic``. Reads go through the request's
``VisibilityPolicy``: a correspondence is hidden when it is private or either dimension is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lore.chronology.correspondence import CorrespondenceError
from lore.chronology.schema import Rational, TimePoint
from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.modules.spec import VaultContext
from lore.core.time.anchors import anchored_elsewhere
from lore.core.time.changes import report as report_time
from lore.core.time.correspondences import (
    CORRESPONDENCE_VISIBILITY,
    CorrespondenceGraph,
    compile_rows,
    points_of,
)
from lore.core.time.dependencies import DependencyIndex
from lore.core.time.kinds import SYNC_POINT
from lore.core.time.models import Correspondence, CorrespondencePoint, Dimension
from lore.core.time.propagate import TimeWriter
from lore.core.time.redact import ReaderTimes
from lore.core.time.specs import dump_spec
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityPolicy
from lore.modules.correspondences.schemas import (
    CorrespondenceCreate,
    CorrespondenceList,
    CorrespondenceOut,
    CorrespondenceUpdate,
    CorrespondenceWriteResult,
    MapBatchOut,
    MapOut,
    MappedMoment,
    SyncPointIn,
    SyncPointOut,
)

DIMENSION = "dimension"
SIDES = ("a", "b")


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def _rate(value: Rational | None) -> dict[str, str] | None:
    return None if value is None else value.model_dump(mode="json")


def _path(engine_path: str) -> str:
    """An engine error path (``/points/2``, ``/rate_after``) as a request path."""
    return ".".join(part for part in engine_path.split("/") if part)


@dataclass
class Correspondences:
    context: VaultContext
    policy: VisibilityPolicy = AUTHOR

    def __post_init__(self) -> None:
        self.session: Session = self.context.session
        self.entities = EntityService(self.context, self.policy)
        self.times = ReaderTimes(self.context, self.policy)

    # --- lookups ------------------------------------------------------------------------------

    def dimension(self, dimension_id: str, *, path: str | None = None) -> Entity:
        """A live dimension the request sees: ``404`` (or ``422`` at ``path``) otherwise."""
        try:
            entity = self.entities.load_visible(dimension_id)
        except NotFoundError:
            entity = None
        if entity is None or entity.kind != DIMENSION or entity.deleted_at is not None:
            if path is not None:
                raise _invalid(path, f"No dimension {dimension_id}.")
            raise NotFoundError(f"No dimension {dimension_id}.")
        return entity

    def row(self, correspondence_id: str, *, include_deleted: bool = False) -> Correspondence:
        row = self.session.scalar(
            select(Correspondence).where(
                Correspondence.id == correspondence_id,
                *self.policy.module_rows(CORRESPONDENCE_VISIBILITY),
            )
        )
        if row is None or (row.deleted_at is not None and not include_deleted):
            raise NotFoundError(f"No correspondence {correspondence_id}.")
        return row

    # --- reads --------------------------------------------------------------------------------

    def out(self, row: Correspondence, points: Sequence[CorrespondencePoint]) -> CorrespondenceOut:
        def shown(spec: Any, dimension_id: str, owner: str) -> dict[str, Any] | None:
            found = self.times.point(spec, dimension_id, owner=owner)
            return dump_spec(found) if isinstance(found, TimePoint) else found

        def point(p: CorrespondencePoint) -> SyncPointOut:
            return SyncPointOut(
                id=p.id,
                a=shown(p.a_spec, p.a_dimension_id, p.id),
                b=shown(p.b_spec, p.b_dimension_id, p.id),
                a_t=p.a_t,
                b_t=p.b_t,
                time_status=p.time_status,
                note=p.note,
            )

        return CorrespondenceOut(
            id=row.id,
            dimension_a_id=row.dimension_a_id,
            dimension_b_id=row.dimension_b_id,
            name=row.name,
            extrapolation="rate" if row.extrapolation == "rate" else "none",
            rate_before=None if row.rate_before is None else Rational(**row.rate_before),
            rate_after=None if row.rate_after is None else Rational(**row.rate_after),
            note=row.note,
            visibility=row.visibility,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
            points=[point(p) for p in points],
        )

    def get(self, correspondence_id: str) -> CorrespondenceOut:
        row = self.row(correspondence_id)
        return self.out(row, points_of(self.session, [row.id])[row.id])

    def list_all(self, dimension_id: str | None = None) -> CorrespondenceList:
        """The live correspondences the request sees (of a dimension: either side), by name."""
        statement = select(Correspondence).where(
            Correspondence.deleted_at.is_(None),
            *self.policy.module_rows(CORRESPONDENCE_VISIBILITY),
        )
        if dimension_id is not None:
            self.dimension(dimension_id)
            statement = statement.where(
                or_(
                    Correspondence.dimension_a_id == dimension_id,
                    Correspondence.dimension_b_id == dimension_id,
                )
            )
        rows = list(
            self.session.scalars(statement.order_by(Correspondence.name, Correspondence.id))
        )
        points = points_of(self.session, [row.id for row in rows])
        return CorrespondenceList(items=[self.out(row, points[row.id]) for row in rows])

    # --- writes -------------------------------------------------------------------------------

    def create(self, data: CorrespondenceCreate) -> CorrespondenceWriteResult:
        if data.dimension_a_id == data.dimension_b_id:
            raise _invalid("dimension_b_id", "A correspondence relates two different dimensions.")
        self.dimension(data.dimension_a_id, path="dimension_a_id")
        self.dimension(data.dimension_b_id, path="dimension_b_id")
        row = Correspondence(
            dimension_a_id=data.dimension_a_id,
            dimension_b_id=data.dimension_b_id,
            name=data.name,
            extrapolation=data.extrapolation,
            rate_before=_rate(data.rate_before),
            rate_after=_rate(data.rate_after),
            note=data.note,
            visibility=data.visibility,
        )
        self.session.add(row)
        self.session.flush()
        points = self._replace_points(row, data.points)
        return self._result(row, points)

    def update(
        self, correspondence_id: str, data: CorrespondenceUpdate
    ) -> CorrespondenceWriteResult:
        row = self.row(correspondence_id)
        if data.revision != row.revision:
            current = self.out(row, points_of(self.session, [row.id])[row.id])
            raise RevisionConflictError(
                f"The correspondence was changed meanwhile (revision {row.revision}, the edit is "
                f"based on {data.revision}).",
                context={"current": current.model_dump(mode="json")},
            )
        sent = data.model_fields_set - {"revision", "suppress"}
        for name in ("name", "extrapolation", "visibility"):
            if name in sent:
                value = getattr(data, name)
                if value is None:
                    raise _invalid(name, f"{name.capitalize()} can't be empty.")
                setattr(row, name, value)
        if "note" in sent:
            row.note = data.note
        if "rate_before" in sent:
            row.rate_before = _rate(data.rate_before)
        if "rate_after" in sent:
            row.rate_after = _rate(data.rate_after)
        row.updated_at = utc_now()
        self.session.flush()
        if "points" in sent and data.points is not None:
            points = self._replace_points(row, data.points)
        else:
            points = points_of(self.session, [row.id])[row.id]
            self._validate(row, points)
        return self._result(row, points)

    def delete(self, correspondence_id: str) -> CorrespondenceWriteResult:
        """Move the correspondence to the trash: mapping stops using it."""
        row = self.row(correspondence_id)
        row.deleted_at = utc_now()
        self.session.flush()
        return self._result(row, points_of(self.session, [row.id])[row.id])

    def _replace_points(
        self, row: Correspondence, given: Sequence[SyncPointIn]
    ) -> list[CorrespondencePoint]:
        """The sync points become ``given`` (old ones go, with their dependency edges); their
        specs resolve (propagation) and the result must compile."""
        self._check_anchors(row, given)
        index = DependencyIndex(self.session)
        for old in points_of(self.session, [row.id])[row.id]:
            index.drop_record(SYNC_POINT, old.id)
            self.session.delete(old)
        self.session.flush()
        points = [
            CorrespondencePoint(
                correspondence_id=row.id,
                position=position,
                a_dimension_id=row.dimension_a_id,
                b_dimension_id=row.dimension_b_id,
                a_spec=point.a,
                b_spec=point.b,
                note=point.note,
            )
            for position, point in enumerate(given)
        ]
        self.session.add_all(points)
        self.session.flush()
        writer = TimeWriter(self.context)
        for point in points:
            writer.set_spec(SYNC_POINT, point.id, "a", point.a_spec)
            writer.set_spec(SYNC_POINT, point.id, "b", point.b_spec)
        writer.propagate(path="points")
        for point in points:
            self.session.refresh(point)
        self._validate(row, points)
        return points

    def _check_anchors(self, row: Correspondence, given: Sequence[SyncPointIn]) -> None:
        """Each side is anchored in its own dimension (an anchor to the other side's records
        would make the correspondence define itself)."""
        for position, point in enumerate(given):
            for side, dimension_id in (("a", row.dimension_a_id), ("b", row.dimension_b_id)):
                if anchored_elsewhere(self.context, getattr(point, side), dimension_id):
                    raise _invalid(
                        f"points.{position}.{side}",
                        "A sync point is anchored in its own dimension; this anchor is in "
                        "another one.",
                    )

    def _validate(self, row: Correspondence, points: Sequence[CorrespondencePoint]) -> None:
        """The resolved sync points and rates must make a correspondence (§12.1)."""
        for position, point in enumerate(points):
            for side in SIDES:
                if getattr(point, f"{side}_t") is None:
                    raise _invalid(
                        f"points.{position}.{side}", "This sync point doesn't resolve to a moment."
                    )
        try:
            compile_rows(row, points)
        except CorrespondenceError as error:
            raise InvalidInputError(
                error.errors[0].message,
                errors=[
                    ErrorItem(
                        path=_path(e.path),
                        code=e.code.removeprefix("correspondence."),
                        message=_message(e.code, e.message),
                    )
                    for e in error.errors
                ],
            ) from error

    def _result(
        self, row: Correspondence, points: Sequence[CorrespondencePoint]
    ) -> CorrespondenceWriteResult:
        ends = sorted({row.dimension_a_id, row.dimension_b_id})
        affected = Affected(entities=ends, dimensions=ends, time_changed=True, search_changed=False)
        return CorrespondenceWriteResult(
            correspondence=self.out(row, points),
            affected=report_time(self.session, self.context.registry, affected),
        )

    # --- mapping ------------------------------------------------------------------------------

    def _durations(self, *ids: str) -> dict[str, int]:
        return dict(
            self.session.execute(
                select(Dimension.entity_id, Dimension.duration).where(
                    Dimension.entity_id.in_(list(ids))
                )
            ).all()
        )

    def map_many(
        self, source: str, target: str, moments: Sequence[int]
    ) -> tuple[list[int | None], list[str]]:
        """Moments of ``source`` mapped to ``target`` along the shortest path of correspondences
        the request sees (a moment outside ``source``'s ``[0, D]`` maps to nothing)."""
        self.dimension(source, path="from_dimension")
        self.dimension(target, path="to_dimension")
        graph = CorrespondenceGraph.load(self.session, self.policy)
        graph.durations.update(self._durations(source, target))
        duration = graph.durations.get(source, 0)
        results: list[int | None] = []
        path: list[str] = []
        for t in moments:
            if not 0 <= t <= duration:
                results.append(None)
                continue
            found = graph.map(source, target, t)
            path = found.path
            results.append(found.t)
        if not path:
            route = graph.path(source, target)
            path = [] if route is None else [edge.correspondence_id for edge in route]
        return results, path

    def map(self, source: str, target: str, t: int) -> MapOut:
        [result], path = self.map_many(source, target, [t])
        return MapOut(from_dimension=source, to_dimension=target, t=t, result_t=result,
                      defined=result is not None, path=path)  # fmt: skip

    def map_batch(self, source: str, target: str, moments: Sequence[int]) -> MapBatchOut:
        results, path = self.map_many(source, target, moments)
        return MapBatchOut(
            from_dimension=source,
            to_dimension=target,
            items=[
                MappedMoment(t=t, result_t=result, defined=result is not None)
                for t, result in zip(moments, results, strict=True)
            ],
            path=path,
        )


def _message(code: str, fallback: str) -> str:
    return {
        "correspondence.non_monotonic": "Sync points must move forward in both dimensions "
        "together: this one is not later than the one before it in both.",
        "correspondence.bad_rate": "A rate must be positive.",
        "correspondence.missing_rate": "A single sync point needs both rates to extrapolate.",
    }.get(code, fallback)
