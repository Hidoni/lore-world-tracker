"""Branches (alternate timelines, ``time-model.md`` §4, D7, ADR-0008): creating a branch of a
timeline at a branch point, checking branch points, and which entities a timeline shows. The data
model and ``TimelineView`` are core; the branches module (``lore.modules.branches``) is the API.

- A branch point resolves within ``[0, D]`` and its anchor may only reference records visible in
  the **parent** timeline (§4.1): a relative anchor to an event, fact or link of a sibling branch,
  or of the branch itself, would let a branch depend on its own future. Timeless records
  (dimensions, calendars) are visible everywhere; a timeline's own branch point only from that
  timeline's lineage.
- Entities created in a branch are **branch-only** (``origin_timeline_id``, §4.6). Entity lists,
  the tree, search and the graph show an entity when its origin is in the lineage of the request's
  timeline; without a timeline (the prime view), only entities without an origin.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lore.chronology.schema import TimePoint
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.time.dependencies import DependencyIndex, SlotNode, Target, time_point_targets
from lore.core.time.dimensions import TIMELINE, branching
from lore.core.time.models import Dimension, Timeline
from lore.core.time.timeline_view import Conditions, TimelineView, registered_time_bounds
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.entities.schemas import EntityWriteResult
    from lore.core.modules.spec import VaultContext

BRANCH_POINT = "branch_point"


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


# --- entities a timeline shows -------------------------------------------------------------------


def entity_scope(session: Session, timeline_id: str | None) -> Callable[[Any], Conditions]:
    """Conditions on an entity table (``Entity`` or an alias) for the entities shown in
    ``timeline_id`` (§4.6), or in the prime view without one. The origin column is ``unindexed``:
    nearly every entity has none, which must not draw the planner to its index."""
    if timeline_id is None:
        return lambda e: [unindexed(e.origin_timeline_id).is_(None)]
    view = TimelineView.for_timeline(session, timeline_id)
    ids = view.timeline_ids
    return lambda e: [
        unindexed(e.origin_timeline_id).is_(None) | unindexed(e.origin_timeline_id).in_(ids)
    ]


def scope_for(
    session: Session, policy: VisibilityPolicy, timeline_id: str | None
) -> Callable[[Any], Conditions]:
    """``entity_scope`` for a request's ``timeline``: a live timeline the policy shows (else
    ``404``, so a hidden branch's id reveals nothing)."""
    if timeline_id is not None:
        timeline = session.get(Entity, timeline_id)
        if (
            timeline is None
            or session.get(Timeline, timeline_id) is None
            or timeline.deleted_at is not None
            or not policy.visible_ids(session, [timeline_id])
        ):
            raise NotFoundError(f"No timeline {timeline_id}.")
    return entity_scope(session, timeline_id)


def origin_for(session: Session, timeline_id: str | None) -> str | None:
    """The ``origin_timeline_id`` of an entity created in ``timeline_id``: ``None`` in a prime
    timeline, the branch otherwise."""
    if timeline_id is None:
        return None
    row = session.get(Timeline, timeline_id)
    return None if row is None or row.is_prime else timeline_id


# --- branch points -------------------------------------------------------------------------------


def hidden_targets(
    context: VaultContext, parent_timeline_id: str, targets: Iterable[Target]
) -> list[SlotNode]:
    """The slots among ``targets`` whose records aren't visible in ``parent_timeline_id``."""
    session = context.session
    view = TimelineView.for_timeline(session, parent_timeline_id)
    providers = context.registry.slot_registry()
    bounds = registered_time_bounds()
    hidden: list[SlotNode] = []
    for target in sorted(t for t in targets if isinstance(t, SlotNode)):
        if target.type == TIMELINE:
            if target.id not in view.timeline_ids:
                hidden.append(target)
            continue
        provider = providers.get(target.type)
        if provider is None or provider.timeline_column is None:
            continue  # timeless records (dimensions, calendars) are visible everywhere
        model: Any = provider.model
        id_column = getattr(model, provider.id_column)
        if model in bounds:
            statement = view.select(model).where(id_column == target.id).limit(1)
        else:
            timeline = getattr(model, provider.timeline_column)
            statement = (
                select(id_column)
                .where(id_column == target.id, timeline.in_(view.timeline_ids))
                .limit(1)
            )
        if session.execute(statement).first() is None:
            hidden.append(target)
    return hidden


def _describe(nodes: list[SlotNode]) -> str:
    return ", ".join(f"{node.type} {node.id} ({node.slot})" for node in nodes)


@dataclass
class BranchPointProblem:
    """Why a stored branch point is invalid (``core.timeline.branch_point_invalid``)."""

    timeline_id: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def branch_point_problems(
    context: VaultContext, timeline_ids: Iterable[str] | None = None
) -> list[BranchPointProblem]:
    """Stored branch points outside ``[0, D]`` or anchored to records their parent doesn't see
    (of the given timelines, or of every branch)."""
    session = context.session
    statement = (
        select(Timeline, Dimension.duration)
        .join(Dimension, Dimension.entity_id == Timeline.dimension_id)
        .where(Timeline.parent_timeline_id.is_not(None))
    )
    if timeline_ids is not None:
        statement = statement.where(Timeline.entity_id.in_(list(timeline_ids)))
    index = DependencyIndex(session)
    problems: list[BranchPointProblem] = []
    for row, duration in session.execute(statement):
        assert row.parent_timeline_id is not None
        if row.branch_t is not None and not 0 <= row.branch_t <= duration:
            problems.append(BranchPointProblem(
                row.entity_id, "Its branch point lies outside the dimension's time.",
                {"branch_t": str(row.branch_t)},
            ))  # fmt: skip
        edges = index.edges_of(SlotNode(TIMELINE, row.entity_id, BRANCH_POINT))
        hidden = hidden_targets(context, row.parent_timeline_id, edges)
        if hidden:
            problems.append(BranchPointProblem(
                row.entity_id,
                "Its branch point is anchored to records its parent timeline doesn't have: "
                + _describe(hidden) + ".",
                {"references": [f"{n.type}/{n.id}/{n.slot}" for n in hidden]},
            ))  # fmt: skip
    return problems


# --- creating a branch ---------------------------------------------------------------------------


def create_branch(
    context: VaultContext,
    policy: VisibilityPolicy,
    *,
    parent_timeline_id: str,
    branch_point: TimePoint,
    name: str,
    summary: str = "",
    visibility: str | None = None,
) -> EntityWriteResult:
    """A branch of ``parent_timeline_id`` at ``branch_point`` (§4.1): a ``timeline`` entity of
    the parent's dimension, branch-only in the parent's lineage when the parent is a branch, with
    the parent's visibility unless given. The parent must be a live timeline the policy shows."""
    from lore.core.entities.schemas import EntityCreate  # noqa: PLC0415
    from lore.core.entities.service import EntityService  # noqa: PLC0415

    session = context.session
    parent = session.get(Entity, parent_timeline_id)
    parent_row = session.get(Timeline, parent_timeline_id)
    if (
        parent is None
        or parent_row is None
        or parent.deleted_at is not None
        or not policy.visible_ids(session, [parent_timeline_id])
    ):
        raise NotFoundError(f"No timeline {parent_timeline_id}.")
    hidden = hidden_targets(context, parent_timeline_id, time_point_targets(branch_point))
    if hidden:
        raise _invalid(
            "branch_point",
            "A branch point may only be anchored to records of its parent timeline: "
            + _describe(hidden)
            + " isn't one.",
            code="branch_point_invalid",
        )
    with branching(parent_timeline_id, branch_point):
        result = EntityService(context, policy).create(
            EntityCreate(
                kind=TIMELINE,
                name=name,
                summary=summary,
                dimension_id=parent_row.dimension_id,
                visibility=visibility or parent.visibility,  # type: ignore[arg-type]
            )
        )
    entity = session.get(Entity, result.entity.id)
    assert entity is not None
    # A branch of a branch exists only in its parent's lineage (like any entity created there).
    entity.origin_timeline_id = origin_for(session, parent_timeline_id)
    session.flush()
    return result


# --- what deleting a branch takes along ----------------------------------------------------------


@dataclass
class BranchContents:
    """A timeline's own records (rows of time-bound tables in it, and its branch-only entities)
    and its descendant branches, for the delete confirmation."""

    descendants: list[str]
    records: dict[str, int]
    entities: list[str]


def branch_contents(session: Session, timeline_id: str, *, trashed: bool = False) -> BranchContents:
    """What lives in ``timeline_id``: its descendant branches and branch-only entities that are
    live (or, with ``trashed``, in the trash), and the live rows of time-bound tables in it and
    its descendants."""
    tree = [timeline_id]
    frontier = [timeline_id]
    while frontier:
        frontier = list(
            session.scalars(
                select(Timeline.entity_id).where(Timeline.parent_timeline_id.in_(frontier))
            )
        )
        tree += frontier
    state = Entity.deleted_at.is_not(None) if trashed else Entity.deleted_at.is_(None)
    descendants = list(
        session.scalars(
            select(Entity.id).where(Entity.id.in_(tree[1:]), state).order_by(Entity.sort_name)
        )
    )
    records: dict[str, int] = {}
    for model in registered_time_bounds():
        table = getattr(model, "__table__", None)
        timeline = getattr(model, "timeline_id", None)
        if table is None or timeline is None:
            continue
        statement = select(func.count()).select_from(model).where(timeline.in_(tree))
        if hasattr(model, "deleted_at"):
            statement = statement.where(model.deleted_at.is_(None))
        count = session.scalar(statement) or 0
        if count:
            records[table.name] = count
    entities = list(
        session.scalars(
            select(Entity.id)
            .where(Entity.origin_timeline_id.in_(tree), state, Entity.id.not_in(tree))
            .order_by(Entity.sort_name, Entity.id)
        )
    )
    return BranchContents(descendants=descendants, records=records, entities=entities)


__all__ = [
    "BRANCH_POINT",
    "BranchContents",
    "BranchPointProblem",
    "branch_contents",
    "branch_point_problems",
    "create_branch",
    "entity_scope",
    "hidden_targets",
    "origin_for",
    "scope_for",
]
