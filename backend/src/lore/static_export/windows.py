"""Timeline windows and series occurrences of the static export (#375, ADR 0016).

Windows have a free range and pixel budget, so the browser computes them like the server does
(``lore.core.time.window``), from what is exported here:

- per timeline (``static/windows/<T>``): its events as the view resolves them, each root with
  its candidate rows nearest first (the window's start bound applies before resolution), every
  row with what the window reads (moments, importance, category, whether it recurs or is a
  cancelled occurrence) and the item it shows, as the server dumps it; and each recurring
  candidate's rule, context and materialized occurrence keys (``series``);
- the filters' inputs per event (``static/events``): tags, visible participants and their kinds,
  and the events above it (``parent`` takes any depth);
- the calendars the rules use (``static/calendars``), compiled in the browser by
  ``@lore/chronology``, the same engine semantics as the server's (``chronology-engine.md``);
- per series (``static/series/<e>``): the row the occurrences endpoint reads (with and without
  a ``timeline``), its rule and its materialized occurrences, or the problem it answers.
"""

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from lore.chronology.schema import CompileContext
from lore.core.entities.models import Entity, EntityTag
from lore.core.links.models import Link
from lore.core.modules.spec import VaultContext
from lore.core.time.calendars import dimension_spec
from lore.core.time.events import EVENT, home_row, shown_events
from lore.core.time.models import Calendar, Event
from lore.core.time.resolve import Resolver
from lore.core.time.schemas import WindowItemOut
from lore.core.time.series import (
    CANCELLED,
    RuleProblem,
    calendar_of,
    dump_rule,
    stored_context,
    visible_materialized,
)
from lore.core.time.specs import dump_spec, parse_end_spec
from lore.core.time.timeline_view import TimelineView
from lore.core.time.window import PARTICIPANT, window_items
from lore.core.visibility import READER
from lore.static_export.asgi import Recorder, route_with
from lore.static_export.entities import TimelineInfo
from lore.static_export.time import PROBLEM


def _candidates(session: Session, view: TimelineView) -> list[list[Event]]:
    """The view's event rows by root, nearest timeline first (``TimelineView.select``'s rank):
    the rows of the lineage that start before their timeline's cut-off."""
    depth = {entry.timeline_id: entry for entry in view.lineage}
    rows = session.scalars(select(Event).where(Event.timeline_id.in_(depth))).all()
    roots: dict[str, list[tuple[int, str, Event]]] = {}
    for row in rows:
        cutoff = depth[row.timeline_id].cutoff
        if row.start_t is None or (cutoff is not None and row.start_t >= cutoff):
            continue
        root = row.overrides_id or row.id
        roots.setdefault(root, []).append((depth[row.timeline_id].depth, row.id, row))
    return [[row for _d, _id, row in sorted(found)] for _root, found in sorted(roots.items())]


def _item(item: Any) -> dict[str, Any]:
    out: dict[str, Any] = WindowItemOut.model_validate(asdict(item)).model_dump(mode="json")
    return out


class WindowExport:
    def __init__(self, recorder: Recorder, vault_id: str) -> None:
        self.recorder = recorder
        self.base = f"vaults/{vault_id}"
        self.calendars: set[str] = set()

    async def files(
        self, context: VaultContext, timelines: dict[str, TimelineInfo]
    ) -> dict[str, Any]:
        files: dict[str, Any] = {}
        session = context.session
        for timeline in timelines.values():
            files[f"{self.base}/static/windows/{timeline.id}"] = self._window(context, timeline)
        files[f"{self.base}/static/events"] = _event_filters(session)
        files.update(await self._series(context, timelines))
        files[f"{self.base}/static/calendars"] = {
            calendar_id: _calendar(session, calendar_id) for calendar_id in sorted(self.calendars)
        }
        return files

    def _window(self, context: VaultContext, timeline: TimelineInfo) -> dict[str, Any]:
        session = context.session
        view = TimelineView.for_timeline(session, timeline.id)
        shown = set(
            session.scalars(
                shown_events(view.select(Event), view, READER).with_only_columns(Event.entity_id)
            )
        )
        roots = [found for found in _candidates(session, view) if found[0].entity_id in shown]
        # Any recurring row of the lineage, as the server checks before expanding series.
        has_series = (
            session.scalar(
                select(Event.id)
                .where(Event.timeline_id.in_(view.timeline_ids), Event.recurrence.is_not(None))
                .limit(1)
            )
            is not None
        )
        rows = [row for found in roots for row in found]
        items = {
            item.row_id: _item(item)
            for item in window_items(context, READER, view, [row.id for row in rows])
        }
        series = {
            row.id: found
            for row in rows
            if row.recurrence is not None
            and (found := self._rule(context, view, timeline.dimension_id, row)) is not None
        }
        return {
            "has_series": has_series,
            "roots": [
                [
                    {
                        "id": row.id,
                        "start": None if row.start_t is None else str(row.start_t),
                        "end": None if row.end_t is None else str(row.end_t),
                        "importance": row.importance,
                        "category": row.category,
                        "recurs": row.recurrence is not None,
                        "cancelled": row.series_entity_id is not None
                        and row.occurrence_state == CANCELLED,
                        "item": items[row.id],
                    }
                    for row in found
                ]
                for found in roots
            ],
            "series": series,
        }

    def _rule(
        self, context: VaultContext, view: TimelineView | None, dimension_id: str, row: Event
    ) -> dict[str, Any] | None:
        """What the engine needs for a series row (``None``: its rule doesn't evaluate)."""
        resolver = Resolver(context, dimension_id)
        found = stored_context(
            resolver, row.recurrence, row.start_t, row.end_spec, row.recurrence_resolved
        )
        if isinstance(found, RuleProblem):
            return None
        rule, ctx = found
        calendar_id, _path = calendar_of(rule, ctx.end)
        if calendar_id is not None:
            self.calendars.add(calendar_id)
        materialized = visible_materialized(context.session, READER, [row.entity_id])
        return {
            "rule": dump_rule(rule),
            "series_start": str(row.start_t),
            "end": dump_spec(parse_end_spec(row.end_spec)),
            "resolved": dict(row.recurrence_resolved or {}),
            "calendar": calendar_id,
            "duration": str(resolver.duration),
            "bounds": [
                None if row.series_start_t is None else str(row.series_start_t),
                None if row.series_end_t is None else str(row.series_end_t),
            ],
            "own": sorted(
                m.occurrence_key
                for m in materialized
                if view is not None
                and m.timeline_id in view.timeline_ids
                and m.series_entity_id
                and m.occurrence_key
            ),
            "materialized": [
                {
                    "key": m.occurrence_key,
                    "timeline": m.timeline_id,
                    "start": None if m.start_t is None else str(m.start_t),
                    "end": None if m.end_t is None else str(m.end_t),
                    "entity_id": m.entity_id,
                    "state": m.occurrence_state,
                }
                for m in sorted(materialized, key=lambda m: m.id)
            ],
        }

    async def _series(
        self, context: VaultContext, timelines: dict[str, TimelineInfo]
    ) -> dict[str, Any]:
        """``static/series/<e>`` for each event with a recurring row: per timeline asked (``""``:
        none), the row the occurrences endpoint reads, or the problem it answers."""
        session = context.session
        files: dict[str, Any] = {}
        recurring = sorted(
            set(session.scalars(select(Event.entity_id).where(Event.recurrence.is_not(None))))
        )
        for entity_id in recurring:
            route = f"{self.base}/events/{entity_id}/occurrences"
            rows: dict[str, Any] = {}
            by_timeline: dict[str, Any] = {}
            for timeline in [None, *timelines.values()]:
                params = {
                    "from": "0",
                    "to": "1",
                    "timeline": None if timeline is None else timeline.id,
                }
                status, answer = await self.recorder.answer(route_with(route, params))
                key = "" if timeline is None else timeline.id
                if status != 200:  # noqa: PLR2004
                    by_timeline[key] = {PROBLEM: answer}
                    continue
                row = _occurrence_row(session, entity_id, timeline)
                assert row is not None  # the endpoint found it
                by_timeline[key] = row.id
                if row.id not in rows:
                    view = TimelineView.for_timeline(session, row.timeline_id)
                    found = self._rule(context, view, _dimension_of(session, row), row)
                    assert found is not None  # the endpoint evaluated it
                    rows[row.id] = {**found, "timeline": row.timeline_id}
            files[f"{self.base}/static/series/{entity_id}"] = {
                "rows": rows,
                "timelines": by_timeline,
            }
        return files


def _dimension_of(session: Session, row: Event) -> str:
    timeline = session.get(Entity, row.timeline_id)
    assert timeline is not None
    assert timeline.dimension_id is not None
    return timeline.dimension_id


def _occurrence_row(
    session: Session, entity_id: str, timeline: TimelineInfo | None
) -> Event | None:
    """The row ``GET /events/{id}/occurrences`` reads (``router.get_occurrences``)."""
    if timeline is None:
        return home_row(session, entity_id)
    view = TimelineView.for_timeline(session, timeline.id)
    row: Event | None = session.scalar(
        view.select(Event).where(Event.entity_id == entity_id).limit(1)
    )
    return row


def _event_filters(session: Session) -> dict[str, Any]:
    """Per event: its tags, its visible participants and their kinds, and the events above it."""
    found: dict[str, dict[str, Any]] = {}
    parents: dict[str, tuple[str | None, str]] = {
        entity_id: (parent_id, kind)
        for entity_id, parent_id, kind in session.execute(
            select(Entity.id, Entity.parent_id, Entity.kind)
        )
    }
    for entity_id, (_parent, kind) in parents.items():
        if kind == EVENT:
            found[entity_id] = {"tags": [], "participants": [], "kinds": [], "ancestors": []}
    for entity_id, tag_id in session.execute(select(EntityTag.entity_id, EntityTag.tag_id)):
        if entity_id in found:
            found[entity_id]["tags"].append(tag_id)
    link = aliased(Link)
    target = aliased(Entity)
    links = select(link.source_id, link.target_id).where(
        link.link_type == PARTICIPANT, link.deleted_at.is_(None), *READER.links(link)
    )
    for source, target_id in session.execute(links):
        if source in found:
            found[source]["participants"].append(target_id)
    kinds = (
        select(link.source_id, target.kind)
        .join(target, target.id == link.target_id)
        .where(
            link.link_type == PARTICIPANT,
            link.deleted_at.is_(None),
            *READER.links(link),
            target.deleted_at.is_(None),
            *READER.entities(target),
        )
    )
    for source, kind in session.execute(kinds):
        if source in found:
            found[source]["kinds"].append(kind)
    for entity_id, entry in found.items():
        # ``window._descendants``: a sub-event of an event, at any depth (cycles end it).
        seen: set[str] = set()
        current = parents[entity_id][0]
        while current is not None and current not in seen:
            seen.add(current)
            entry["ancestors"].append(current)
            above = parents.get(current)
            current = above[0] if above is not None and above[1] == EVENT else None
        for key in ("tags", "participants", "kinds"):
            entry[key] = sorted(set(entry[key]))
    return found


def _calendar(session: Session, calendar_id: str) -> dict[str, Any]:
    """A calendar's definition and compile context, as ``compiled_calendar`` compiles it."""
    row = session.get(Calendar, calendar_id)
    assert row is not None
    base_unit, duration = dimension_spec(session, row.dimension_id)
    context = CompileContext(
        calendar_id=calendar_id,
        base_unit=base_unit,
        dimension_duration=str(duration),
        resolved=row.resolved_anchors,
    )
    return {"definition": row.definition, "context": context.model_dump(mode="json")}
