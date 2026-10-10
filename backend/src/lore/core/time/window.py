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
- **Series** (``recurrence.md`` §5.1, §5.5; #52): a series row isn't an item itself. Candidate
  series are those with ``series_start_t < to`` and ``series_end_t >= from`` (``>=``: an instant
  occurrence at ``from`` counts); each is expanded with ``expand(max_items = budget)``. Its
  occurrences become items (``occurrence_key`` set) that take part in LOD and buckets like events;
  a truncated expansion becomes a **series band** (``estimated_count``, over the part of the
  window the series covers) instead. ``include_series=false`` leaves series out.
- **Materialized occurrences** are events of their own: an occurrence with a materialized
  row (visible to the policy) isn't computed again; the row is an item at its own time
  (``modified`` ones move in and out of windows), with ``occurrence_key``, ``series_id`` and
  ``occurrence_state``. ``cancelled`` rows are left out unless ``include_cancelled``.

The overlap query fetches only ids, raw moment keys and importance; the items kept are loaded
with the columns they show. Results are cached per vault write generation (``WINDOWS``, decided
2026-10-07): any committed write to the vault invalidates them.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, String, exists, select, type_coerce
from sqlalchemy.orm import Session, aliased

from lore.chronology.numbers import from_sortable_key, sortable_key
from lore.chronology.recurrence import (
    Occurrence,
    RecurrenceContext,
    RecurrenceError,
    count_in_window,
    expand,
)
from lore.core.entities.models import Entity, EntityTag
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.links.models import Link
from lore.core.time.cache import SERIES, WINDOWS, SeriesOccurrences
from lore.core.time.events import EVENT, shown_events, with_children
from lore.core.time.models import Event
from lore.core.time.redact import ReaderTimes
from lore.core.time.resolve import Resolver
from lore.core.time.series import (
    CANCELLED,
    Rule,
    RuleProblem,
    calendar_of,
    stored_context,
    visible_materialized,
)
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
    include_series: bool = True
    include_cancelled: bool = False


@dataclass(frozen=True)
class WindowItem:
    entity_id: str
    row_id: str
    name: str
    visibility: str
    parent_id: str | None
    has_children: bool
    start_t: int | None
    end_t: int | None
    importance: int
    category: str | None
    time_status: str | None
    start_precision: str
    start_approximate: bool
    end_precision: str | None
    end_approximate: bool
    end_kind: str
    occurrence_key: str | None = None
    series_id: str | None = None
    occurrence_state: str | None = None


@dataclass(frozen=True)
class SeriesBand:
    """A series with too many occurrences in the window to list."""

    entity_id: str
    row_id: str
    name: str
    visibility: str
    importance: int
    category: str | None
    start: int
    end: int
    estimated_count: int


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
    series_bands: list[SeriesBand] = field(default_factory=list)
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
    vault = context.vault
    key = (timeline_id, query, type(policy).__name__, policy.reader)
    window: Window = WINDOWS.get(
        vault.id,
        vault.writes.generation,  # read before the query: a later write can't be cached as old
        key,
        lambda: _compute(context, policy, timeline_id, query),
    )
    return window


def _compute(
    context: VaultContext, policy: VisibilityPolicy, timeline_id: str, query: WindowQuery
) -> Window:
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
    # Series and cancelled occurrences of the lineage's timelines (a superset of what the view
    # shows: they are only left out of the scan), through their partial indexes: few rows, where
    # the view's own conditions would make SQLite walk the timeline's whole window index.
    lineage = set(view.timeline_ids)
    series_ids = {
        row_id
        for row_id, timeline in session.execute(
            select(Event.id, Event.timeline_id).where(Event.recurrence.is_not(None))
        )
        if timeline in lineage
    }
    left_out = series_ids
    if not query.include_cancelled:
        cancelled = select(Event.id, Event.timeline_id).where(
            Event.series_entity_id.is_not(None), Event.occurrence_state == CANCELLED
        )
        left_out = left_out | {
            i for i, timeline in session.execute(cancelled) if timeline in lineage
        }
    rows = [row for row in _raw_rows(session, statement) if row[0] not in left_out]
    occurrences = _Occurrences()
    bands: list[SeriesBand] = []
    if query.include_series and series_ids:
        bands = _expand_series(context, policy, view, query, occurrences=occurrences, rows=rows)

    kept = _keep(rows, budget(query.px))
    culled = [row for row in rows if row[0] not in kept]
    window = Window(buckets=_buckets(culled, query), total=len(rows), culled=len(culled))
    window.items = _items(context, policy, view, sorted(kept), occurrences)
    window.series_bands = bands
    return window


def _raw_rows(session: Session, statement: Any) -> list[_Row]:
    """The statement's rows as the driver returns them (text and integer columns only): the
    whole-dimension window reads 100k rows, which cost more as ``Row`` objects than to fetch."""
    result = session.connection().execute(statement)
    try:
        return list(result.cursor.fetchall())
    finally:
        result.close()


@dataclass(frozen=True)
class _Occurrence:
    row_id: str
    key: str
    start: int
    end: int
    importance: int


type _Computed = tuple[str, int, int]  # occurrence key, start, end


class _Occurrences:
    """The computed occurrences of a window, by synthetic id ``<row id>:<key>``. A zoomed-out
    window has tens of thousands and keeps a few: they are only looked up for those."""

    def __init__(self) -> None:
        self._series: dict[str, tuple[Sequence[_Computed], int]] = {}
        self._by_key: dict[str, dict[str, _Computed]] = {}

    def add(self, row_id: str, items: Sequence[_Computed], importance: int) -> None:
        self._series[row_id] = (items, importance)

    def get(self, item_id: str) -> _Occurrence | None:
        row_id, _, key = item_id.partition(":")
        if row_id not in self._series:
            return None
        items, importance = self._series[row_id]
        if row_id not in self._by_key:
            self._by_key[row_id] = {item[0]: item for item in items}
        _key, start, end = self._by_key[row_id][key]
        return _Occurrence(row_id, key, start, end, importance)


@dataclass(frozen=True)
class _Expanded:
    """Every occurrence of a series, by start, with the sortable keys of their moments (what
    ``SERIES`` caches: plain tuples of text and integers, which the garbage collector doesn't
    have to walk)."""

    items: tuple[_Computed, ...]
    keys: tuple[tuple[str, str], ...]
    starts: tuple[int, ...]
    longest: int

    def overlapping(self, w0: int, w1: int) -> range:
        """The indexes of the occurrences overlapping ``[w0, w1)`` with ``w0 < w1``
        (``time-model.md`` §2.1), as ``expand`` selects them: a run, since the occurrences are
        in order of both start and end."""
        first = bisect_left(self.starts, w0 - self.longest)
        last = bisect_left(self.starts, w1)
        items = self.items
        while first < last and not _reaches(items[first], w0):
            first += 1
        return range(first, last)


def _reaches(item: _Computed, w0: int) -> bool:
    """Whether an occurrence starting before the window's end is still on at ``w0``."""
    _key, start, end = item
    return end > w0 or (start == end and start >= w0)


def _computed(items: Sequence[Occurrence]) -> tuple[_Computed, ...]:
    return tuple((item.key, item.start, item.end) for item in items)


def _sortable(items: Sequence[_Computed]) -> tuple[tuple[str, str], ...]:
    return tuple((sortable_key(start), sortable_key(end)) for _key, start, end in items)


def _expanded(rule: Rule, ctx: RecurrenceContext, limit: int) -> _Expanded | None:
    """Every occurrence of a series when there are at most ``limit`` (``None`` otherwise, or
    for a rule that doesn't evaluate): no occurrence starts after the dimension's end. Only
    series whose occurrences are in order of both start and end are kept, so that those
    overlapping a window are a run of them."""
    try:
        expansion = expand(rule, ctx, (0, ctx.dimension_duration + 1), limit)
    except RecurrenceError:
        return None
    items = _computed(expansion.items)
    if expansion.truncated or any(a[1] > b[1] or a[2] > b[2] for a, b in pairwise(items)):
        return None
    return _Expanded(
        items,
        _sortable(items),
        tuple(start for _key, start, _end in items),
        max((end - start for _key, start, end in items), default=0),
    )


def _occurrences_in(
    vault_id: str, resolver: Resolver, row: Any, query: WindowQuery
) -> tuple[Sequence[_Computed], Sequence[tuple[str, str]]] | int | None:
    """``expand(rule, ctx, window, budget)`` of a series row (its stored columns): the
    occurrences and their sortable keys, or the ``estimated_count`` of a truncated expansion
    (``None``: the rule no longer evaluates; its findings say why).

    A series with at most the budget in all comes from its cached occurrences. It is never
    truncated in a window: it has no more periods or occurrences there than over the whole
    dimension, where the same ``max_items`` didn't truncate it (``recurrence.md`` §5.1). Other
    series are counted first: an exact count over the budget is what the truncated expansion
    reports, without visiting thousands of occurrences to find out."""
    limit = budget(query.px)
    window = (query.start, query.end)
    key = (vault_id, row.id, limit)
    inputs = (row.recurrence, row.start_t, row.end_spec, row.recurrence_resolved, resolver.duration)
    entry = SERIES.find(key, inputs)
    if (
        entry is not None
        and entry.calendar_id is not None
        and resolver.calendars.get(entry.calendar_id, "") is not entry.calendar
    ):
        entry = None  # the calendar was compiled again
    rule_ctx = None
    if entry is None or entry.occurrences is None:
        found = stored_context(resolver, *inputs[:4])
        if isinstance(found, RuleProblem):
            return None
        rule_ctx = found
    if entry is None:
        assert rule_ctx is not None
        rule, ctx = rule_ctx
        expanded = _expanded(rule, ctx, limit)
        calendar_id, _path = calendar_of(rule, ctx.end)
        entry = SeriesOccurrences(
            inputs, calendar_id, ctx.calendar, expanded, len(expanded.items) if expanded else 0
        )
        SERIES.put(key, entry)
    cached: _Expanded | None = entry.occurrences
    if cached is not None:
        run = cached.overlapping(*window)
        return cached.items[run.start : run.stop], cached.keys[run.start : run.stop]
    assert rule_ctx is not None
    rule, ctx = rule_ctx
    count, exact = count_in_window(rule, ctx, window)
    if exact and count > limit:
        return count
    expansion = expand(rule, ctx, window, limit)
    if expansion.truncated:
        assert expansion.estimated_count is not None
        return expansion.estimated_count
    items = _computed(expansion.items)
    return items, _sortable(items)


def _expand_series(
    context: VaultContext,
    policy: VisibilityPolicy,
    view: TimelineView,
    query: WindowQuery,
    *,
    occurrences: _Occurrences,
    rows: list[_Row],
) -> list[SeriesBand]:
    """Adds the occurrences of the candidate series in the window to ``occurrences`` and to
    ``rows``; returns the bands of the series with too many."""
    session = context.session
    # Through the series' partial index (timeline, series start); stored documents as they are
    # (parsed only for the series whose occurrences aren't cached).
    statement = shown_events(
        view.select(Event, where=lambda e: [e.recurrence.is_not(None)]), view, policy
    ).where(Event.series_start_t < query.end, Event.series_end_t >= query.start)
    for condition in _filters(policy, query):
        statement = statement.where(condition)
    statement = statement.with_only_columns(
        Event.id, Event.entity_id, Event.recurrence, Event.recurrence_resolved, Event.start_t,
        type_coerce(Event.end_spec, JSON).label("end_spec"), Event.series_start_t,
        Event.series_end_t, Event.importance, Event.category, Entity.name, Entity.visibility,
        Entity.dimension_id,
    )  # fmt: skip
    bands: list[SeriesBand] = []
    resolvers: dict[str, Resolver] = {}
    candidates = session.execute(statement).all()
    # Materialized occurrences replace the computed ones: they are events of the window
    # themselves (drawn at their own time, or left out when cancelled; recurrence.md §7).
    own: dict[str, set[str]] = {}
    for m in visible_materialized(session, policy, [row.entity_id for row in candidates]):
        if m.timeline_id in view.timeline_ids and m.series_entity_id and m.occurrence_key:
            own.setdefault(m.series_entity_id, set()).add(m.occurrence_key)
    for row in candidates:
        if row.dimension_id not in resolvers:
            resolvers[row.dimension_id] = Resolver(context, row.dimension_id)
        try:
            expansion = _occurrences_in(context.vault.id, resolvers[row.dimension_id], row, query)
        except RecurrenceError:
            continue
        if expansion is None:
            continue
        if isinstance(expansion, int):
            bands.append(
                SeriesBand(
                    entity_id=row.entity_id,
                    row_id=row.id,
                    name=row.name,
                    visibility=row.visibility,
                    importance=row.importance,
                    category=row.category,
                    start=max(query.start, row.series_start_t),
                    end=min(query.end, row.series_end_t),
                    estimated_count=expansion,
                )
            )
            continue
        items, keys = expansion
        materialized = own.get(row.entity_id)
        if materialized:
            shown = [i for i, item in enumerate(items) if item[0] not in materialized]
            items, keys = [items[i] for i in shown], [keys[i] for i in shown]
        occurrences.add(row.id, items, row.importance)
        prefix, importance = row.id + ":", row.importance
        rows.extend(
            [(prefix + item[0], *key, importance) for item, key in zip(items, keys, strict=True)]
        )
    bands.sort(key=lambda band: (band.start, band.row_id))
    return bands


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
    context: VaultContext,
    policy: VisibilityPolicy,
    view: TimelineView,
    kept: list[str],
    occurrences: _Occurrences,
) -> list[WindowItem]:
    """The kept rows and occurrences, with only the columns the window shows (specs as plain
    JSON), by start, then the later end first, then row id and occurrence key."""
    if not kept:
        return []
    computed = {i: found for i in kept if (found := occurrences.get(i)) is not None}
    row_ids = sorted({computed[i].row_id if i in computed else i for i in kept})
    session = context.session
    rows = session.execute(
        select(
            Event.id, Event.entity_id, Event.start_t, Event.end_t, Event.importance,
            Event.category, Event.time_status, type_coerce(Event.start_spec, JSON),
            type_coerce(Event.end_spec, JSON), Entity.name, Entity.visibility,
            Entity.parent_id, Entity.dimension_id, Event.series_entity_id, Event.occurrence_key,
            Event.occurrence_state,
        )
        .join(Entity, Entity.id == Event.entity_id)
        .where(Event.id.in_(row_ids))
    ).all()  # fmt: skip
    named_series = {row.series_entity_id for row in rows if row.series_entity_id is not None}
    shown_series = policy.visible_ids(session, named_series) if policy.reader else named_series
    parents = with_children(session, view, policy, [row.entity_id for row in rows])
    named_parents = {row.parent_id for row in rows if row.parent_id is not None}
    shown_parents = policy.visible_ids(session, named_parents) if policy.reader else named_parents
    times = ReaderTimes(context, policy)
    times.prefetch(
        point
        for row in rows
        for point in (row[7], row[8].get("time_point") if row[8]["kind"] == "time_point" else None)
    )

    def shown(point: dict[str, Any], dimension_id: str | None) -> dict[str, Any]:
        if not policy.reader or point["anchor"]["kind"] == "absolute":
            return point
        return times.point(point, dimension_id) or {}

    by_id = {row.id: row for row in rows}
    items = []
    for kept_id in kept:
        occurrence = computed.get(kept_id)
        row = by_id[occurrence.row_id if occurrence is not None else kept_id]
        start_spec, end_spec = row[7], row[8]
        start = shown(start_spec, row.dimension_id)
        end_point: dict[str, Any] = {}
        if end_spec["kind"] == "time_point":
            end_point = shown(end_spec["time_point"], row.dimension_id)
        items.append(
            WindowItem(
                entity_id=row.entity_id,
                row_id=row.id,
                name=row.name,
                visibility=row.visibility,
                parent_id=row.parent_id if row.parent_id in shown_parents else None,
                has_children=row.entity_id in parents,
                start_t=row.start_t if occurrence is None else occurrence.start,
                end_t=row.end_t if occurrence is None else occurrence.end,
                importance=row.importance,
                category=row.category,
                time_status=row.time_status,
                start_precision=str(start.get("precision", "base")),
                start_approximate=bool(start.get("approximate", False)),
                end_precision=end_point.get("precision"),
                end_approximate=bool(end_point.get("approximate", False)),
                end_kind=str(end_spec["kind"]),
                occurrence_key=row.occurrence_key if occurrence is None else occurrence.key,
                series_id=(
                    row.entity_id
                    if occurrence is not None
                    else row.series_entity_id
                    if row.series_entity_id in shown_series
                    else None
                ),
                occurrence_state=row.occurrence_state,
            )
        )
    items.sort(key=_order)
    return items


def _order(item: WindowItem) -> tuple[int, int, str, int, str]:
    start = item.start_t if item.start_t is not None else -1
    end = item.end_t if item.end_t is not None else -1
    key = item.occurrence_key or ""
    head, _, tail = key.partition(".")
    return (start, -end, item.row_id, int(head or -1), tail)
