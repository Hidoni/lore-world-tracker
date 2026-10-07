"""Events as an entity kind (``time-model.md`` §5.5, §9.1-§9.4; R-EVT-1…5, R-DIM-5).

An event's ``ext`` is its **home row** in ``events``: ``timeline_id`` (default: the dimension's
prime timeline), ``start`` (a time point, required on creation), ``end`` (an end spec, default
``instant``), ``importance`` (1-5, default 3) and ``category``. Rules (decided 2026-10-06 where
noted):

- **R-DIM-5:** an event can only be created in a dimension with a calendar that isn't in the
  trash (decided): ``422 dimension_has_no_calendar``.
- Specs are resolved when written (``422`` on ``ext.start``/``ext.end`` for dates that don't
  resolve or lie outside ``[0, D]``) and stay linked to their anchors (``propagate``): moving an
  event moves what is anchored to it, in the same transaction.
- The timeline is chosen on creation and can't change (branches, M9, decide about moving).
- **Sub-events:** a parent event must be visible in the child's timeline (``TimelineView``).
- Relative anchors reference an event by its **entity id** (decided): "that event as seen from
  the dependent's timeline". Only home rows exist until M9 (#115 makes the slots
  timeline-aware).
- Purging an event freezes what is anchored to it, then deletes its rows.
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from lore.chronology.schema import EndSpec, InstantEnd, TimePoint
from lore.core.entities.errors import ParentNotAllowedError
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError
from lore.core.time.batch import Lens, display
from lore.core.time.calendars import lens
from lore.core.time.models import Calendar, Event, Timeline
from lore.core.time.propagate import TimeWriter, freeze_on_purge
from lore.core.time.redact import ReaderTimes
from lore.core.time.resolve import Resolution, Resolver, require
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID, dump_spec, parse_end_spec
from lore.core.time.timeline_view import TimeBound, TimelineView, register_time_bound
from lore.core.visibility import AUTHOR, VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

EVENT = "event"
INSTANT: EndSpec = InstantEnd(kind="instant")

# Series start at series_start_t (recurrence, #52); until then every row starts at start_t.
register_time_bound(TimeBound(Event, start="start_t", end="end_t"))


class DimensionHasNoCalendarError(InvalidInputError):
    """R-DIM-5: events need a calendar in their dimension."""

    code = "dimension_has_no_calendar"
    title = "Dimension has no calendar"


class EventExt(BaseModel):
    """An event's ``ext`` on create (``start`` required) or patch (only the members sent
    change)."""

    model_config = ConfigDict(extra="forbid")

    timeline_id: str | None = None
    start: TimePoint | None = None
    end: EndSpec | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    category: str | None = Field(default=None, min_length=1, max_length=200)


def _parse(ext: dict[str, Any] | None) -> EventExt:
    try:
        return EventExt.model_validate(ext or {})
    except ValidationError as exc:
        raise InvalidInputError(
            "The event's data is invalid.",
            errors=[
                ErrorItem(
                    path=".".join(["ext", *(str(part) for part in error["loc"])]),
                    code="invalid_value",
                    message=str(error["msg"]),
                )
                for error in exc.errors(include_url=False)
            ],
        ) from exc


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def home_row(session: Session, entity_id: str) -> Event | None:
    """The event's row in its own timeline."""
    return session.scalar(
        select(Event).where(Event.entity_id == entity_id, Event.overrides_id.is_(None))
    )


# --- writes ----------------------------------------------------------------------------------


def write_event(
    context: VaultContext, entity: Entity, ext: dict[str, Any] | None, creating: bool
) -> None:
    data = _parse(ext)
    sent = data.model_fields_set
    session = context.session
    assert entity.dimension_id is not None  # events always have a home dimension
    start: TimePoint | None
    end: EndSpec | None
    if creating:
        _require_calendar(session, entity.dimension_id)
        if data.start is None:
            raise _invalid("ext.start", "An event needs a start.", code="required")
        row = Event(
            entity_id=entity.id,
            timeline_id=_timeline(session, entity.dimension_id, data.timeline_id),
            start_spec=data.start,
            end_spec=data.end or INSTANT,
            importance=data.importance or 3,
            category=data.category,
        )
        session.add(row)
        _check_parent(context, entity, row.timeline_id)
        start, end = data.start, data.end or INSTANT
    else:
        found = home_row(session, entity.id)
        if found is None:
            raise ConflictError("The event has no time data.")
        row = found
        for key in ("start", "end", "importance"):
            if key in sent and getattr(data, key) is None:
                raise _invalid(f"ext.{key}", f"The event's {key} can't be removed.")
        if "timeline_id" in sent and data.timeline_id != row.timeline_id:
            raise _invalid("ext.timeline_id", "An event can't move to another timeline.")
        start = data.start if "start" in sent else None
        end = data.end if "end" in sent else None
        if data.importance is not None:
            row.importance = data.importance
        if "category" in sent:
            row.category = data.category
        if sent - {"timeline_id"}:
            row.revision += 1
    if start is not None or end is not None:
        _write_times(context, entity.dimension_id, row, start, end)
    session.flush()


def _require_calendar(session: Session, dimension_id: str) -> None:
    live = session.scalar(
        select(func.count())
        .select_from(Calendar)
        .join(Entity, Entity.id == Calendar.entity_id)
        .where(Calendar.dimension_id == dimension_id, Entity.deleted_at.is_(None))
    )
    if not live:
        message = "The dimension has no calendar: create one before adding events."
        raise DimensionHasNoCalendarError(
            message,
            errors=[ErrorItem(path="dimension_id", code="dimension_has_no_calendar",
                              message=message)],
        )  # fmt: skip


def _timeline(session: Session, dimension_id: str, timeline_id: str | None) -> str:
    """The event's timeline: the one given (of the dimension, not in the trash) or the prime."""
    statement = (
        select(Timeline.entity_id)
        .join(Entity, Entity.id == Timeline.entity_id)
        .where(Timeline.dimension_id == dimension_id, Entity.deleted_at.is_(None))
    )
    if timeline_id is None:
        found = session.scalar(statement.where(Timeline.is_prime))
        if found is None:
            raise ConflictError("The dimension has no prime timeline.")
        return found
    if session.scalar(statement.where(Timeline.entity_id == timeline_id)) is None:
        raise _invalid(
            "ext.timeline_id", "The timeline must be a timeline of the event's dimension."
        )
    return timeline_id


def _write_times(
    context: VaultContext,
    dimension_id: str,
    row: Event,
    start: TimePoint | None,
    end: EndSpec | None,
) -> None:
    """Check that the new specs resolve, store them and propagate (§7.2)."""
    session = context.session
    resolver = Resolver(context, dimension_id, row.timeline_id)
    started = resolver.resolve(start if start is not None else row.start_spec)
    if start is not None:
        _require(started, "ext.start")
    if end is not None:
        _require(resolver.resolve_end(end, started), "ext.end")
    if start is not None:
        row.start_spec = start
    if end is not None:
        row.end_spec = end
    session.flush()
    writer = TimeWriter(context)
    if start is not None:
        writer.set_spec(EVENT, row.entity_id, "start", start)
    if end is not None:
        writer.set_spec(EVENT, row.entity_id, "end", end, dimension_id=dimension_id)
    writer.propagate(path="ext")


def _require(resolution: Resolution, path: str) -> None:
    if resolution.problem is not None and resolution.problem.code == "out_of_bounds":
        raise _invalid(path, resolution.problem.message, code="out_of_bounds")
    require(resolution, path)


def _check_parent(context: VaultContext, entity: Entity, timeline_id: str) -> None:
    """A parent event must be visible in the child's timeline (``time-model.md`` §9.2)."""
    if entity.parent_id is None:
        return
    parent = context.session.get(Entity, entity.parent_id)
    if parent is None or parent.kind != EVENT:
        return  # misc parents (and the generic rules) are the entity service's
    view = TimelineView.for_timeline(context.session, timeline_id)
    visible = context.session.scalar(
        view.select(Event).where(Event.entity_id == parent.id).limit(1)
    )
    if visible is None or not view.shows_entity(parent.origin_timeline_id):
        message = "The parent event isn't part of the event's timeline."
        raise ParentNotAllowedError(
            message, errors=[ErrorItem(path="parent_id", code="parent_not_allowed",
                                       message=message)]
        )  # fmt: skip


def update_event(context: VaultContext, entity: Entity, sent: frozenset[str]) -> None:
    if "parent_id" in sent:
        row = home_row(context.session, entity.id)
        if row is not None:
            _check_parent(context, entity, row.timeline_id)


def purge_event(context: VaultContext, entity: Entity) -> None:
    """Freeze what is anchored to the event (it needs the rows), then delete them."""
    freeze_on_purge(context, entity)
    session = context.session
    rows = session.scalars(select(Event).where(Event.entity_id == entity.id)).all()
    for row in sorted(rows, key=lambda r: r.overrides_id is None):  # overrides first
        session.delete(row)
        session.flush()


def event_problems(context: VaultContext, entity: Entity) -> list[str]:
    row = home_row(context.session, entity.id)
    if row is None:
        return [f"{entity.name}: the event has no time data."]
    timeline = context.session.get(Timeline, row.timeline_id)
    if timeline is None or timeline.dimension_id != entity.dimension_id:
        return [f"{entity.name}: the event's timeline isn't in its home dimension."]
    return []


# --- reads -----------------------------------------------------------------------------------


@dataclass
class EventTimes:
    """Resolved moments, statuses and displays of events for one request: displays use the
    dimension's default calendar when the policy may see it, else raw base units."""

    context: VaultContext
    policy: VisibilityPolicy
    _resolvers: dict[str, Resolver] = field(default_factory=dict)
    _lenses: dict[str, tuple[str, Lens]] = field(default_factory=dict)

    def _resolver(self, dimension_id: str) -> Resolver:
        if dimension_id not in self._resolvers:
            # Stored moments are shown to anyone who sees the event (only specs are redacted).
            self._resolvers[dimension_id] = Resolver(self.context, dimension_id, policy=AUTHOR)
        return self._resolvers[dimension_id]

    def lens(self, dimension_id: str) -> tuple[str, Lens]:
        if dimension_id not in self._lenses:
            calendar_id = self._resolver(dimension_id).default_calendar_id
            if calendar_id is None or not self.policy.visible_ids(
                self.context.session, [calendar_id]
            ):
                calendar_id = ABSOLUTE_CALENDAR_ID
            try:
                found = lens(self.context, dimension_id, calendar_id)
            except ConflictError:  # the calendar doesn't compile
                calendar_id = ABSOLUTE_CALENDAR_ID
                found = lens(self.context, dimension_id, calendar_id)
            self._lenses[dimension_id] = (calendar_id, found)
        return self._lenses[dimension_id]

    def displays(self, dimension_id: str, row: Event) -> dict[str, str | None]:
        resolver = self._resolver(dimension_id)
        calendar_id, lens_ = self.lens(dimension_id)
        start = resolver.slot(EVENT, row.entity_id, "start")
        end = resolver.slot(EVENT, row.entity_id, "end")
        unknown = parse_end_spec(row.end_spec).kind == "unknown"
        return {
            "calendar_id": calendar_id,
            "start": display(lens_, start),
            "end": "?" if unknown else display(lens_, end),
        }


def read_event(
    context: VaultContext, entity: Entity, policy: VisibilityPolicy
) -> dict[str, Any] | None:
    row = home_row(context.session, entity.id)
    if row is None or entity.dimension_id is None:
        return None
    times = ReaderTimes(context, policy)
    return {
        "timeline_id": row.timeline_id,
        "start": times.point(dump_spec(row.start_spec), entity.dimension_id),
        "end": reader_end(times, row, entity.dimension_id),
        "start_t": None if row.start_t is None else str(row.start_t),
        "end_t": None if row.end_t is None else str(row.end_t),
        "time_status": row.time_status,
        "importance": row.importance,
        "category": row.category,
        "display": EventTimes(context, policy).displays(entity.dimension_id, row),
    }


def reader_end(times: ReaderTimes, row: Event, dimension_id: str) -> dict[str, Any] | None:
    """An end spec as the policy may see it: a time-point end is redacted like any point; a
    duration in a calendar the reader can't see becomes a time-point end at the stored moment."""
    end = parse_end_spec(row.end_spec)
    document = dump_spec(end)
    if not times.policy.reader:
        return document
    if end.kind == "time_point":
        point = times.point(document["time_point"], dimension_id)
        return None if point is None else {"kind": "time_point", "time_point": point}
    if end.kind == "duration" and end.duration.kind == "calendar":
        hidden = not times.policy.visible_ids(times.context.session, [end.duration.calendar_id])
        if hidden:
            if row.end_t is None:
                return None
            point = {"anchor": {"kind": "absolute", "t": str(row.end_t)}, "precision": "base"}
            return {"kind": "time_point", "time_point": times.point(point, dimension_id)}
    return document


# --- the event tree ----------------------------------------------------------------------------


def shown_events(statement: Any, view: TimelineView, policy: VisibilityPolicy) -> Any:
    """A ``view.select(Event)`` statement joined to the events' entities and restricted to those
    a timeline shows: not in the trash, visible to the policy and to the timeline (§4.6)."""
    return statement.join(Entity, Entity.id == Event.entity_id).where(
        Entity.kind == EVENT,
        Entity.deleted_at.is_(None),
        *policy.entities(Entity),
        *view.entities(Entity),
    )


def with_children(
    session: Session, view: TimelineView, policy: VisibilityPolicy, ids: list[str]
) -> set[str]:
    """The events of ``ids`` that have sub-events the timeline shows."""
    if not ids:
        return set()
    # From the parent index: the candidate children, then those the timeline has rows of.
    candidates = dict(
        session.execute(
            select(Entity.id, Entity.parent_id).where(
                Entity.parent_id.in_(ids),
                Entity.kind == EVENT,
                Entity.deleted_at.is_(None),
                *policy.entities(Entity),
                *view.entities(Entity),
            )
        ).all()
    )
    if not candidates:
        return set()
    shown = view.select(Event, where=lambda e: [e.entity_id.in_(list(candidates))])
    found = session.scalars(shown.with_only_columns(Event.entity_id))
    return {parent for child in found if (parent := candidates[child]) is not None}


@dataclass(frozen=True)
class EventTreeRow:
    entity: Entity
    row: Event
    has_children: bool


def _cursor(row: Event, entity: Entity) -> str:
    assert row.start_t is not None
    assert row.end_t is not None
    values = [str(row.start_t), str(row.end_t), entity.sort_name, entity.id]
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")


def _decode(cursor: str) -> tuple[int, int, str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        start, end, name, entity_id = json.loads(raw)
        return int(start), int(end), str(name), str(entity_id)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise _invalid("cursor", "The cursor is invalid.") from exc


def event_tree(
    context: VaultContext,
    policy: VisibilityPolicy,
    timeline_id: str,
    *,
    parent_id: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[EventTreeRow], str | None]:
    """One level of the event outline of a timeline (``api.md`` §2): the events the timeline
    sees (``TimelineView``), not in the trash and visible to the policy, whose parent is
    ``parent_id``, or the roots: events whose parent this tree doesn't show (none, a misc entry,
    a hidden or trashed event). Ordered by start, then the longer first (later end), then name
    and id (decided 2026-10-06)."""
    session = context.session
    view = TimelineView.for_timeline(session, timeline_id)

    def shown(statement: Any) -> Any:
        return shown_events(statement, view, policy)

    statement = shown(view.select(Event)).add_columns(Entity)
    if parent_id is not None:
        statement = statement.where(Entity.parent_id == parent_id)
    else:
        ids = shown(view.select(Event)).with_only_columns(Event.entity_id)
        statement = statement.where(
            or_(Entity.parent_id.is_(None), Entity.parent_id.not_in(ids.scalar_subquery()))
        )
    if cursor is not None:
        start, end, name, entity_id = _decode(cursor)
        statement = statement.where(
            or_(
                Event.start_t > start,
                and_(
                    Event.start_t == start,
                    or_(
                        Event.end_t < end,
                        and_(
                            Event.end_t == end,
                            or_(
                                Entity.sort_name > name,
                                and_(Entity.sort_name == name, Entity.id > entity_id),
                            ),
                        ),
                    ),
                ),
            )
        )
    statement = statement.order_by(
        Event.start_t, Event.end_t.desc(), Entity.sort_name, Entity.id
    ).limit(limit + 1)
    found = [(row, entity) for row, entity in session.execute(statement)]
    page = found[:limit]
    parents = with_children(session, view, policy, [entity.id for _row, entity in page])
    next_cursor = _cursor(*page[-1]) if len(found) > limit else None
    return [EventTreeRow(e, r, e.id in parents) for r, e in page], next_cursor
