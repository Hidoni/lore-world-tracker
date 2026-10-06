"""The timeline window (``api.md`` §2, ``frontend.md`` §9.2): the events of a timeline overlapping
``[from, to)``, culled to a pixel budget (LOD), with density buckets for what is culled.

- **Overlap** is ``TimelineView.overlaps`` (``time-model.md`` §2.1): half-open spans, instants
  count at their moment.
- **LOD:** at most ``min(px, 2000)`` items (decided 2026-10-06), chosen by importance (highest
  first), then duration (longest first), then start and row id. Items come back ordered by start.
- **Buckets:** the window is split into ``px // 4`` equal buckets (at least 1, at most one per base
  unit). Per bucket (decided 2026-10-06): ``starts`` counts each culled event once, in the bucket
  of its start clamped to the window (so they add up to ``culled``); ``active`` counts the culled
  events covering any part of the bucket (for shading: an era begun before the window counts
  everywhere it lasts, not only at the left edge). Buckets where both are 0 are left out.
- **Filters:** ``min_importance``; ``categories`` (any); ``tags`` (all required);
  ``participants`` (any: events with a visible ``core.participant`` link to one of them);
  ``parent`` (all descendants of that event). Decided 2026-10-06.
- Visibility: only events the policy and the timeline show; participant links must be visible
  too. Precision names reach readers as ``ReaderTimes`` shows the points.

The overlap query fetches only ids, moments and importance; full rows are loaded for the items
kept.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import String, exists, select, type_coerce
from sqlalchemy.orm import aliased

from lore.chronology.numbers import from_sortable_key, sortable_key
from lore.core.entities.models import Entity, EntityTag
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.links.models import Link
from lore.core.time.events import EVENT, shown_events, with_children
from lore.core.time.models import Event
from lore.core.time.redact import ReaderTimes
from lore.core.time.specs import dump_spec, parse_end_spec
from lore.core.time.timeline_view import TimelineView
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

MAX_ITEMS = 2000
PX_PER_BUCKET = 4
PARTICIPANT = "core.participant"


@dataclass(frozen=True)
class WindowQuery:
    start: int
    end: int
    px: int
    min_importance: int | None = None
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    participants: tuple[str, ...] = ()
    parent: str | None = None


@dataclass(frozen=True)
class WindowItem:
    entity: Entity
    row: Event
    parent_id: str | None
    has_children: bool
    start_precision: str
    start_approximate: bool
    end_precision: str | None
    end_approximate: bool
    end_kind: str


@dataclass(frozen=True)
class Bucket:
    start: int
    end: int
    starts: int  # culled events starting here (the first bucket: or before the window)
    active: int  # culled events covering any part of the bucket


@dataclass
class Window:
    items: list[WindowItem] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)
    total: int = 0
    culled: int = 0


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code="invalid_value",
                                                        message=message)])  # fmt: skip


def budget(px: int) -> int:
    return min(px, MAX_ITEMS)


def bucket_bounds(start: int, end: int, px: int) -> list[int]:
    """The ``n + 1`` boundaries of ``n`` equal buckets over ``[start, end)``."""
    count = max(1, min(px // PX_PER_BUCKET, end - start))
    width = end - start
    return [start + (i * width) // count for i in range(count + 1)]


def timeline_window(
    context: VaultContext, policy: VisibilityPolicy, timeline_id: str, query: WindowQuery
) -> Window:
    if query.start >= query.end:
        raise _invalid("to", "The window must end after it starts.")
    session = context.session
    view = TimelineView.for_timeline(session, timeline_id)
    # Raw sortable keys (text order is numeric order): decoding 2 x 100k moments costs more
    # than the query. Only the importance tier at the budget's edge is decoded.
    statement = shown_events(
        view.select(Event, window=(query.start, query.end)), view, policy
    ).with_only_columns(
        Event.id, type_coerce(Event.start_t, String), type_coerce(Event.end_t, String),
        Event.importance,
    )  # fmt: skip
    for condition in _filters(policy, query):
        statement = statement.where(condition)
    rows: list[_Row] = [tuple(row) for row in session.execute(statement)]

    kept = _keep(rows, budget(query.px))
    culled = [row for row in rows if row[0] not in kept]
    window = Window(buckets=_buckets(culled, query), total=len(rows), culled=len(culled))
    window.items = _items(context, policy, view, sorted(kept))
    return window


type _Row = tuple[str, str, str, int]  # row id, start key, end key, importance


def _keep(rows: list[_Row], keep: int) -> set[str]:
    """LOD: the ``keep`` rows ranked first by importance (highest first), then duration (longest
    first), start and row id. Whole importance tiers are taken by count; only the tier at the
    edge of the budget is ranked."""
    tiers: dict[int, list[_Row]] = {}
    for row in rows:
        tiers.setdefault(row[3], []).append(row)
    kept: set[str] = set()
    for importance in sorted(tiers, reverse=True):
        tier = tiers[importance]
        room = keep - len(kept)
        if room <= 0:
            break
        if len(tier) <= room:
            kept.update(row[0] for row in tier)
            continue
        ranked = sorted(
            tier, key=lambda r: (from_sortable_key(r[1]) - from_sortable_key(r[2]), r[1], r[0])
        )
        kept.update(row[0] for row in ranked[:room])
    return kept


def _buckets(culled: list[_Row], query: WindowQuery) -> list[Bucket]:
    """``starts`` and ``active`` per bucket, by counting on sorted keys: an event starts in the
    bucket of its start clamped to the window; it is active in bucket ``[lo, hi)`` when it starts
    before ``hi`` and its last covered moment (``end - 1``, an instant's start) is at or after
    ``lo`` (it overlaps the window, so the first bucket has them all)."""
    bounds = bucket_bounds(query.start, query.end, query.px)
    keys = [sortable_key(bound) for bound in bounds]
    starts = sorted(row[1] for row in culled)
    span_ends = sorted(row[2] for row in culled if row[1] != row[2])
    instants = sorted(row[1] for row in culled if row[1] == row[2])
    before = [bisect_left(starts, key) for key in keys]  # culled starting before each bound
    before[0], before[-1] = 0, len(starts)  # clamped to the window
    buckets = []
    for i in range(len(bounds) - 1):
        count = before[i + 1] - before[i]
        ended = bisect_right(span_ends, keys[i]) + bisect_left(instants, keys[i]) if i else 0
        active = before[i + 1] - ended
        if count or active:
            buckets.append(Bucket(bounds[i], bounds[i + 1], count, active))
    return buckets


def _filters(policy: VisibilityPolicy, query: WindowQuery) -> list[Any]:
    conditions: list[Any] = []
    if query.min_importance is not None:
        conditions.append(Event.importance >= query.min_importance)
    if query.categories:
        conditions.append(Event.category.in_(query.categories))
    for tag_id in query.tags:
        conditions.append(
            exists().where(EntityTag.entity_id == Event.entity_id, EntityTag.tag_id == tag_id)
        )
    if query.participants:
        link = aliased(Link)
        conditions.append(
            exists().where(
                link.source_id == Event.entity_id,
                link.link_type == PARTICIPANT,
                link.target_id.in_(query.participants),
                link.deleted_at.is_(None),
                *policy.links(link),
            )
        )
    if query.parent is not None:
        conditions.append(Event.entity_id.in_(_descendants(query.parent)))
    return conditions


def _descendants(parent_id: str) -> Any:
    """The ids of every event below ``parent_id`` (sub-events at any depth)."""
    child = aliased(Entity)
    tree = (
        select(Entity.id)
        .where(Entity.parent_id == parent_id, Entity.kind == EVENT)
        .cte("descendants", recursive=True)
    )
    # UNION (not UNION ALL) also terminates on a cycle.
    tree = tree.union(
        select(child.id).join(tree, child.parent_id == tree.c.id).where(child.kind == EVENT)
    )
    return select(tree.c.id)


def _items(
    context: VaultContext, policy: VisibilityPolicy, view: TimelineView, row_ids: list[str]
) -> list[WindowItem]:
    if not row_ids:
        return []
    session = context.session
    pairs = session.execute(
        select(Event, Entity)
        .join(Entity, Entity.id == Event.entity_id)
        .where(Event.id.in_(row_ids))
        .order_by(Event.start_t, Event.end_t.desc(), Event.id)
    ).all()
    parents = with_children(session, view, policy, [entity.id for _row, entity in pairs])
    hidden_parents = {
        e.parent_id for _r, e in pairs if e.parent_id is not None
    } - policy.visible_ids(session, [e.parent_id for _r, e in pairs])
    times = ReaderTimes(context, policy)
    items = []
    for row, entity in pairs:
        start = times.point(dump_spec(row.start_spec), entity.dimension_id) or {}
        end = parse_end_spec(row.end_spec)
        end_point: dict[str, Any] = {}
        if end.kind == "time_point":
            end_point = times.point(dump_spec(end.time_point), entity.dimension_id) or {}
        items.append(
            WindowItem(
                entity=entity,
                row=row,
                parent_id=None if entity.parent_id in hidden_parents else entity.parent_id,
                has_children=entity.id in parents,
                start_precision=str(start.get("precision", "base")),
                start_approximate=bool(start.get("approximate", False)),
                end_precision=end_point.get("precision"),
                end_approximate=bool(end_point.get("approximate", False)),
                end_kind=end.kind,
            )
        )
    return items
