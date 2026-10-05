"""Dimensions and timelines as entity kinds (``time-model.md`` §3, §4.1; R-DIM-1…4, R-TL-1).

A **dimension**'s ``ext`` is its time spec: ``base_unit`` and ``duration`` (``D``, required on
creation) and the optional ``present`` time point. Creating a dimension creates its **prime
timeline** (named "Prime") in the same transaction. Rules (decided 2026-10-05 where noted):

- ``1 ≤ D`` with at most 1000 digits. ``D`` may change only if every resolved moment of the
  dimension's records stays within ``[0, new D]`` (R-DIM-3): otherwise ``422 time_constraint``
  lists the offending slots. Slots that *are* the end of time (``end_of_time`` ends, which depend
  on the dimension) aren't offenders: they move to the new ``D``.
- ``present`` accepts absolute anchors only until anchor resolution (#47); it must lie in
  ``[0, D]``.
- Timelines can't be created through the entity API: the prime comes with its dimension and
  branches with the branches module (M9). Their ``ext`` is read-only for now.
- The prime timeline follows its dimension (decided): trashing, restoring and purging the
  dimension does the same to its prime, which can't be trashed, restored or purged on its own.
  Purging a dimension is still refused while anything else lives in it. The prime also has its
  dimension's visibility: changing the dimension's changes the prime's, and the prime's can't be
  set on its own (decided, so a world made public later doesn't keep a hidden prime).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.schema import BaseUnit, MomentStr, TimePoint
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.time.dependencies import (
    DependencyIndex,
    DimensionNode,
    SlotNode,
    time_point_targets,
)
from lore.core.time.models import Dimension, Timeline
from lore.core.time.schemas import TimelineNode, TimelineTree
from lore.core.time.slots import SlotKey, SlotMoment, SlotRegistry, SlotUpdate
from lore.core.time.specs import dump_spec
from lore.core.time.status import TimeStatus
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

PRIME_NAME = "Prime"
DIMENSION = "dimension"
TIMELINE = "timeline"

# Set while the dimension acts on its prime timeline (create, purge), which the timeline kind
# refuses otherwise.
_CASCADE: ContextVar[bool] = ContextVar("lore_time_prime_cascade", default=False)


@contextmanager
def _cascade() -> Iterator[None]:
    token = _CASCADE.set(True)
    try:
        yield
    finally:
        _CASCADE.reset(token)


class TimeConstraintError(InvalidInputError):
    """A hard structural time rule would break (``time-model.md`` §7.2 step 6)."""

    code = "time_constraint"
    title = "Time constraint violated"


class DimensionExt(BaseModel):
    """A dimension's ``ext`` on create (``base_unit`` and ``duration`` required) or patch (only
    the members sent change)."""

    model_config = ConfigDict(extra="forbid")

    base_unit: BaseUnit | None = None
    duration: MomentStr | None = None
    present: TimePoint | None = None


def _parse(ext: dict[str, Any] | None) -> DimensionExt:
    try:
        return DimensionExt.model_validate(ext or {})
    except ValidationError as exc:
        raise InvalidInputError(
            "The dimension's time spec is invalid.",
            errors=[
                ErrorItem(
                    path=".".join(["ext", *(str(part) for part in error["loc"])]),
                    code="invalid_value",
                    message=str(error["msg"]),
                )
                for error in exc.errors(include_url=False)
            ],
        ) from exc


def _slots_resolve(count: int) -> str:
    return "1 time slot resolves" if count == 1 else f"{count} time slots resolve"


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


# --- dimension -----------------------------------------------------------------------------------


def dimension_row(session: Session, dimension_id: str) -> Dimension:
    row = session.get(Dimension, dimension_id)
    if row is None:
        raise ConflictError("The dimension has no time spec.")
    return row


def prime_timeline(session: Session, dimension_id: str) -> Entity | None:
    return session.scalar(
        select(Entity)
        .join(Timeline, Timeline.entity_id == Entity.id)
        .where(Timeline.dimension_id == dimension_id, Timeline.is_prime)
    )


def write_dimension(
    context: VaultContext, entity: Entity, ext: dict[str, Any] | None, creating: bool
) -> None:
    data = _parse(ext)
    sent = data.model_fields_set
    session = context.session
    duration = _check_spec(data, creating)

    if creating:
        assert data.base_unit is not None
        assert duration is not None
        row = Dimension(
            entity_id=entity.id, base_unit=data.base_unit.model_dump(), duration=duration
        )
        session.add(row)
    else:
        row = dimension_row(session, entity.id)
        if data.base_unit is not None:
            row.base_unit = data.base_unit.model_dump()
    old_duration = row.duration
    if duration is not None:
        row.duration = duration
    if "present" in sent:
        _set_present(session, row, data.present)
    session.flush()

    if creating:
        _create_prime(context, entity)
    elif duration is not None and duration != old_duration:
        _change_duration(context, row)


def _check_spec(data: DimensionExt, creating: bool) -> int | None:
    """Required and non-removable members; returns the duration sent (if any)."""
    sent = data.model_fields_set
    if creating:
        missing = [key for key in ("base_unit", "duration") if getattr(data, key) is None]
        if missing:
            message = "A dimension needs a base unit and a duration."
            raise InvalidInputError(
                message,
                errors=[ErrorItem(path=f"ext.{key}", code="required", message=message)
                        for key in missing],
            )  # fmt: skip
    else:
        for key in ("base_unit", "duration"):
            if key in sent and getattr(data, key) is None:
                raise _invalid(f"ext.{key}", f"The {key.replace('_', ' ')} can't be removed.")
    duration = int(data.duration) if data.duration is not None else None
    if duration is not None and duration < 1:
        raise _invalid("ext.duration", "The duration must be at least 1 base unit.")
    return duration


def _set_present(session: Session, row: Dimension, point: TimePoint | None) -> None:
    """Store and resolve the present moment (absolute anchors only until #47)."""
    if point is None:
        row.present_spec, row.present_t, row.time_status = None, None, None
    else:
        if point.anchor.kind != "absolute":
            raise _invalid(
                "ext.present.anchor",
                "The present moment can only be given as an absolute moment for now.",
                code="not_supported",
            )
        t = int(point.anchor.t)
        if t > row.duration:
            raise _invalid(
                "ext.present",
                "The present moment lies after the end of the dimension.",
                code="out_of_bounds",
            )
        row.present_spec, row.present_t, row.time_status = point, t, TimeStatus.OK.value
    targets = time_point_targets(point) if point is not None else set()
    DependencyIndex(session).replace_edges(SlotNode(DIMENSION, row.entity_id, "present"), targets)


def _create_prime(context: VaultContext, dimension: Entity) -> None:
    from lore.core.entities.schemas import EntityCreate  # noqa: PLC0415
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    with _cascade():
        EntityService(context).create(
            EntityCreate(
                kind=TIMELINE,
                name=PRIME_NAME,
                dimension_id=dimension.id,
                visibility=dimension.visibility,
            )
        )


def _offenders(context: VaultContext, row: Dimension) -> list[SlotMoment]:
    """Slots of the dimension resolved after its duration, except those that follow it."""
    session = context.session
    following = set(DependencyIndex(session).dependents_of(DimensionNode(row.entity_id)))
    return [
        moment
        for moment in context.registry.slot_registry().moments_beyond(
            session, row.entity_id, row.duration
        )
        if SlotNode(moment.record_type, moment.id, moment.slot) not in following
    ]


def _change_duration(context: VaultContext, row: Dimension) -> None:
    """R-DIM-3, then move the slots that are the end of time to the new ``D``."""
    offenders = _offenders(context, row)
    if offenders:
        message = (
            f"{_slots_resolve(len(offenders))} after the new duration: "
            "move them first, or choose a longer duration."
        )
        raise TimeConstraintError(
            message,
            errors=[
                ErrorItem(
                    path="ext.duration",
                    code=TimeStatus.OUT_OF_BOUNDS.value,
                    message=f"{m.record_type} {m.id}: slot {m.slot!r} resolves after the end.",
                )
                for m in offenders
            ],
            context={
                "records": [
                    {"record_type": m.record_type, "id": m.id, "slot": m.slot, "t": str(m.t)}
                    for m in offenders
                ]
            },
        )
    registry: SlotRegistry = context.registry.slot_registry()
    by_type: dict[str, list[SlotUpdate]] = {}
    for node in DependencyIndex(context.session).dependents_of(DimensionNode(row.entity_id)):
        update = SlotUpdate(SlotKey(node.id, node.slot), row.duration, TimeStatus.OK)
        by_type.setdefault(node.type, []).append(update)
    for record_type, updates in by_type.items():
        registry.write(context.session, record_type, updates)


def read_dimension(context: VaultContext, entity: Entity) -> dict[str, Any] | None:
    row = context.session.get(Dimension, entity.id)
    if row is None:
        return None
    prime = prime_timeline(context.session, entity.id)
    return {
        "base_unit": row.base_unit,
        "duration": str(row.duration),
        "default_calendar_id": row.default_calendar_id,
        "present": dump_spec(row.present_spec) if row.present_spec is not None else None,
        "present_t": None if row.present_t is None else str(row.present_t),
        "time_status": row.time_status,
        "prime_timeline_id": prime.id if prime is not None else None,
    }


def update_dimension(context: VaultContext, entity: Entity, sent: frozenset[str]) -> None:
    """The prime timeline takes over the dimension's visibility."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    if "visibility" not in sent:
        return
    prime = prime_timeline(context.session, entity.id)
    if prime is None or prime.visibility == entity.visibility:
        return
    prime.visibility = entity.visibility
    context.session.flush()
    EntityService(context).reindex(prime)


def trash_dimension(context: VaultContext, entity: Entity, trashing: bool) -> None:
    """The prime timeline follows its dimension into and out of the trash."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    prime = prime_timeline(context.session, entity.id)
    if prime is None or (prime.deleted_at is not None) == trashing:
        return
    prime.deleted_at = utc_now() if trashing else None
    context.session.flush()
    EntityService(context).reindex(prime)


def purge_dimension(context: VaultContext, entity: Entity) -> None:
    """Purge the prime timeline with the dimension, then the time spec. The entity service's
    checks then refuse the purge (rolling all of it back) if anything else lives in it."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    session = context.session
    prime = prime_timeline(session, entity.id)
    if prime is not None:
        if prime.deleted_at is None:  # stored state from before the prime followed its dimension
            prime.deleted_at = entity.deleted_at
        with _cascade():
            EntityService(context).purge(prime.id)
    row = session.get(Dimension, entity.id)
    if row is not None:
        session.delete(row)
    DependencyIndex(session).drop_record(DIMENSION, entity.id)
    session.flush()


def dimension_problems(context: VaultContext, entity: Entity) -> list[str]:
    """Rules a stored dimension breaks (vetting an undo)."""
    session = context.session
    row = session.get(Dimension, entity.id)
    if row is None:
        return [f"{entity.name}: the dimension has no time spec."]
    problems: list[str] = []
    if row.duration < 1:
        problems.append(f"{entity.name}: the duration must be at least 1 base unit.")
    offenders = _offenders(context, row)
    if offenders:
        problems.append(
            f"{entity.name}: {_slots_resolve(len(offenders))} after the end of the dimension."
        )
    primes = session.scalars(
        select(Entity)
        .join(Timeline, Timeline.entity_id == Entity.id)
        .where(Timeline.dimension_id == entity.id, Timeline.is_prime)
    ).all()
    if len(primes) != 1:
        problems.append(f"{entity.name}: the dimension needs exactly one prime timeline.")
    elif (primes[0].deleted_at is None) != (entity.deleted_at is None):
        problems.append(f"{entity.name}: the prime timeline must follow its dimension's trash.")
    elif primes[0].visibility != entity.visibility:
        problems.append(f"{entity.name}: the prime timeline must have its dimension's visibility.")
    return problems


# --- timeline ------------------------------------------------------------------------------------


def write_timeline(
    context: VaultContext, entity: Entity, ext: dict[str, Any] | None, creating: bool
) -> None:
    if creating:
        if not _CASCADE.get():
            raise _invalid(
                "kind",
                "Timelines can't be created directly: every dimension has its prime timeline, "
                "and branches come with the branches module.",
            )
        assert entity.dimension_id is not None
        context.session.add(
            Timeline(entity_id=entity.id, dimension_id=entity.dimension_id, is_prime=True)
        )
        context.session.flush()
    elif ext:
        raise _invalid("ext", "A timeline's settings can't be edited yet.")


def read_timeline(context: VaultContext, entity: Entity) -> dict[str, Any] | None:
    row = context.session.get(Timeline, entity.id)
    if row is None:
        return None
    return {
        "dimension_id": row.dimension_id,
        "parent_timeline_id": row.parent_timeline_id,
        "is_prime": row.is_prime,
        "branch_point": dump_spec(row.branch_point_spec) if row.branch_point_spec else None,
        "branch_t": None if row.branch_t is None else str(row.branch_t),
        "time_status": row.time_status,
    }


def _is_prime(session: Session, entity: Entity) -> bool:
    row = session.get(Timeline, entity.id)
    return row is not None and row.is_prime


def update_timeline(context: VaultContext, entity: Entity, sent: frozenset[str]) -> None:
    if "visibility" not in sent or not _is_prime(context.session, entity):
        return
    dimension = context.session.get(Entity, entity.dimension_id)
    if dimension is not None and entity.visibility != dimension.visibility:
        raise _invalid(
            "visibility",
            "The prime timeline has its dimension's visibility: change the dimension's instead.",
        )


def trash_timeline(context: VaultContext, entity: Entity, trashing: bool) -> None:
    if _is_prime(context.session, entity):
        action = "trashed" if trashing else "restored"
        raise ConflictError(f"The prime timeline is {action} with its dimension.")


def purge_timeline(context: VaultContext, entity: Entity) -> None:
    session = context.session
    row = session.get(Timeline, entity.id)
    if row is None:
        return
    if row.is_prime and not _CASCADE.get():
        raise ConflictError("The prime timeline is purged with its dimension.")
    branches = session.scalars(
        select(Timeline.entity_id).where(Timeline.parent_timeline_id == entity.id)
    ).all()
    if branches:
        raise ConflictError(
            f"The timeline has {len(branches)} branches: purge them first.",
            context={"references": {"branches": len(branches)}},
        )
    session.delete(row)
    DependencyIndex(session).drop_record(TIMELINE, entity.id)
    session.flush()


def timeline_problems(context: VaultContext, entity: Entity) -> list[str]:
    row = context.session.get(Timeline, entity.id)
    if row is None:
        return [f"{entity.name}: the timeline doesn't belong to a dimension."]
    if row.dimension_id != entity.dimension_id:
        return [f"{entity.name}: the timeline's dimension differs from its home dimension."]
    return []


# --- reads ---------------------------------------------------------------------------------------


def timeline_tree(
    context: VaultContext, policy: VisibilityPolicy, dimension_id: str
) -> TimelineTree:
    """The dimension's timelines as a tree. A timeline the policy hides hides its branches too
    (they inherit from it). Trashed branches are left out unless the dimension itself is in the
    trash (then its prime is too)."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    dimension = EntityService(context, policy).load_visible(dimension_id)
    if dimension.kind != DIMENSION:
        raise NotFoundError(f"No dimension {dimension_id}.")
    statement = (
        select(Entity, Timeline)
        .join(Timeline, Timeline.entity_id == Entity.id)
        .where(Timeline.dimension_id == dimension_id, *policy.entities(Entity))
        .order_by(Entity.sort_name, Entity.id)
    )
    if dimension.deleted_at is None:
        statement = statement.where(Entity.deleted_at.is_(None))
    rows = context.session.execute(statement).all()
    children: dict[str | None, list[tuple[Entity, Timeline]]] = {}
    for entity, row in rows:
        children.setdefault(row.parent_timeline_id, []).append((entity, row))

    def node(entity: Entity, row: Timeline) -> TimelineNode:
        return TimelineNode(
            id=entity.id,
            name=entity.name,
            visibility=entity.visibility,
            is_prime=row.is_prime,
            parent_timeline_id=row.parent_timeline_id,
            branch_point=dump_spec(row.branch_point_spec) if row.branch_point_spec else None,
            branch_t=row.branch_t,
            time_status=row.time_status,
            trashed=entity.deleted_at is not None,
            children=[node(*child) for child in children.get(entity.id, [])],
        )

    return TimelineTree(
        dimension_id=dimension_id, items=[node(*root) for root in children.get(None, [])]
    )
