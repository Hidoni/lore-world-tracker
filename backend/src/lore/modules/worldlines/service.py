"""The worldlines service (``docs/modules/worldlines.md``, ``time-model.md`` §11).

- **Segments.** ``PUT`` replaces an entity's explicit segments as a whole, in the request's
  transaction: the old rows go (with their dependency edges), the new ones are written, their
  ``start``/``end`` specs go through ``TimeWriter`` (they may be anchored to events of their
  timeline and move with them), and the resolved segments are validated.
- **Implicit worldline** (§11.2). Without explicit segments an entity lives its existence
  periods (``core.exists`` facts) in its home dimension's timeline context (the prime unless a
  timeline is given), in chronological order at rate 1; without existence facts, the whole time
  of the home dimension. A multiversal entity without segments has no worldline.
- **Subjective time** (§11.3) is exact (``lore.core.time.worldlines``), counted in base units of
  the personal clock dimension; ages are formatted with the calendar ``diff`` in that dimension's
  default calendar, counted from where the worldline starts.
- **Reads** go through the request's ``VisibilityPolicy``: readers see the segments whose own
  visibility, entity, dimension and timeline they see, and subjective time counts only those.
  Participations are the visible ``core.participant`` links from visible events to the entity;
  an event counts in a segment's timeline when that timeline's lineage sees it (``TimelineView``).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.calendar.arithmetic import diff
from lore.chronology.calendar.compiled import CompiledCalendar, DateError
from lore.chronology.schema import Rational, TimePoint
from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.facts.schemas import EXISTS
from lore.core.links.models import Link
from lore.core.modules.spec import VaultContext
from lore.core.time.anchors import anchored_elsewhere
from lore.core.time.calendars import compiled_calendar
from lore.core.time.changes import report as report_time
from lore.core.time.dependencies import DependencyIndex
from lore.core.time.dimensions import prime_timeline
from lore.core.time.kinds import SEGMENT
from lore.core.time.models import Dimension, Event, Timeline, WorldlineSegment
from lore.core.time.propagate import TimeWriter
from lore.core.time.redact import ReaderTimes
from lore.core.time.specs import dump_spec
from lore.core.time.timeline_view import TimelineView
from lore.core.time.worldlines import (
    ONE,
    SEGMENT_VISIBILITY,
    Span,
    rate_of,
    subjective_at,
    subjective_starts,
)
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityPolicy
from lore.modules.worldlines.schemas import (
    Age,
    PersonalItem,
    PersonalTimeline,
    Presence,
    SegmentIn,
    SegmentOut,
    SegmentsPut,
    Worldline,
    WorldlineWriteResult,
)

DIMENSION = "dimension"
TIMELINE = "timeline"
EVENT = "event"
PARTICIPANT = "core.participant"
# A personal timeline lists at most this many items (participations above all).
MAX_ITEMS = 5000
# Items of the same subjective (and world) moment: existence starts first, ends last.
# Items of the same subjective moment and segment: existence starts first, then participations
# (a departure event before its jump), ends last.
_KIND_ORDER = {"existence_start": 0, "participation": 1, "jump": 2, "existence_end": 3}


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def _rational(value: Fraction) -> Rational:
    return Rational(num=str(value.numerator), den=str(value.denominator))


def _floor(value: Fraction) -> int:
    return value.numerator // value.denominator


@dataclass
class Lived:
    """A worldline as a request sees it: its spans in worldline order, with their rows (``None``
    for the implicit worldline's) and specs."""

    entity: Entity
    implicit: bool
    personal_dimension_id: str | None
    spans: list[Span]
    rows: list[WorldlineSegment | None]
    specs: list[tuple[Any, Any]]
    starts: list[Fraction] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.starts = subjective_starts(self.spans)

    def subjective(self, index: int, t: int) -> Fraction:
        return subjective_at(self.spans[index], self.starts[index], t)


type Assignment = Literal["chosen", "implied", "ambiguous", "absent"]


@dataclass
class Participation:
    """A participation placed in the worldline (``Worldlines.participations``)."""

    link: Link
    event: Entity
    covering: list[int]
    """The covering segments (indexes into the worldline), the one used first."""
    assignment: Assignment
    timeline_id: str | None
    t: int | None


@dataclass
class Worldlines:
    context: VaultContext
    policy: VisibilityPolicy = AUTHOR

    def __post_init__(self) -> None:
        self.session: Session = self.context.session
        self.entities = EntityService(self.context, self.policy)
        self.times = ReaderTimes(self.context, self.policy)
        self._calendars: dict[str, CompiledCalendar | None] = {}

    # --- lookups ------------------------------------------------------------------------------

    def entity(self, entity_id: str) -> Entity:
        entity = self.entities.load_visible(entity_id)
        if entity.deleted_at is not None:
            raise NotFoundError(f"No entity {entity_id}.")
        return entity

    def _can_have_worldline(self, entity: Entity) -> bool:
        kind = self.entities.kinds.get(entity.kind)
        return kind is not None and kind.definition.capabilities.can_have_worldline

    def context_timeline(self, entity: Entity, timeline_id: str | None) -> str | None:
        """The timeline the implicit worldline is read in: ``timeline_id`` (a visible timeline
        of the home dimension) or the home dimension's prime."""
        if entity.dimension_id is None:
            return None
        if timeline_id is None:
            prime = prime_timeline(self.session, entity.dimension_id)
            return None if prime is None else prime.id
        row = self.session.get(Timeline, timeline_id)
        if (
            row is None
            or row.dimension_id != entity.dimension_id
            or not self.policy.visible_ids(self.session, [timeline_id])
        ):
            raise _invalid("timeline", "Not a timeline of the entity's home dimension.")
        return timeline_id

    def _rows(self, entity_id: str) -> list[WorldlineSegment]:
        """The entity's explicit segments the request sees, in worldline order."""
        return list(
            self.session.scalars(
                select(WorldlineSegment)
                .where(
                    WorldlineSegment.entity_id == entity_id,
                    WorldlineSegment.overrides_id.is_(None),
                    *self.policy.module_rows(SEGMENT_VISIBILITY),
                )
                .order_by(WorldlineSegment.seq, WorldlineSegment.id)
            )
        )

    def _has_segments(self, entity_id: str) -> bool:
        """Whether the entity has explicit segments at all (hidden ones too: a reader who sees
        none of them doesn't see the implicit worldline instead)."""
        return (
            self.session.scalar(
                select(WorldlineSegment.id).where(WorldlineSegment.entity_id == entity_id).limit(1)
            )
            is not None
        )

    # --- the worldline ------------------------------------------------------------------------

    def lived(self, entity: Entity, timeline_id: str | None = None) -> Lived:
        if self._has_segments(entity.id):
            rows = self._rows(entity.id)
            resolved = [r for r in rows if r.start_t is not None and r.end_t is not None]
            spans = [
                Span(
                    r.id,
                    r.dimension_id,
                    r.timeline_id,
                    int(r.start_t or 0),
                    int(r.end_t or 0),
                    rate_of(r.rate),
                )
                for r in resolved
            ]
            first = rows[0].dimension_id if rows else None
            return Lived(
                entity,
                implicit=False,
                personal_dimension_id=entity.dimension_id or first,
                spans=spans,
                rows=list(resolved),
                specs=[(r.start_spec, r.end_spec) for r in resolved],
            )
        return self._implicit(entity, self.context_timeline(entity, timeline_id))

    def _implicit(self, entity: Entity, timeline_id: str | None) -> Lived:
        """§11.2: the existence periods in the timeline context, merged, rate 1."""
        if entity.dimension_id is None or timeline_id is None:
            return Lived(entity, True, entity.dimension_id, [], [], [])
        dimension = self.session.get(Dimension, entity.dimension_id)
        duration = 0 if dimension is None else int(dimension.duration)
        facts = self._existence_facts(entity.id, timeline_id)
        if not facts:
            span = Span(None, entity.dimension_id, timeline_id, 0, duration, Fraction(1))
            return Lived(entity, True, entity.dimension_id, [span], [None], [(None, None)])
        periods: list[tuple[int, int, Any, Any]] = []
        for fact in facts:
            start = 0 if fact.valid_from_t is None else int(fact.valid_from_t)
            end = duration if fact.valid_to_t is None else int(fact.valid_to_t)
            if start > end:
                continue
            start_spec = None if fact.valid_from_t is None else fact.valid_from_spec
            end_spec = None if fact.valid_to_t is None else fact.valid_to_spec
            periods.append((start, end, start_spec, end_spec))
        merged: list[tuple[int, int, Any, Any]] = []
        for period in sorted(periods, key=lambda p: (p[0], p[1])):
            if merged and period[0] <= merged[-1][1]:
                last = merged[-1]
                if period[1] > last[1]:
                    merged[-1] = (last[0], period[1], last[2], period[3])
                continue
            merged.append(period)
        spans = [
            Span(None, entity.dimension_id, timeline_id, start, end, Fraction(1), closed_end=False)
            for start, end, _, _ in merged
        ]
        specs = [(self._fact_spec(s), self._fact_spec(e)) for _, _, s, e in merged]
        return Lived(entity, True, entity.dimension_id, spans, [None] * len(spans), specs)

    @staticmethod
    def _fact_spec(spec: Any) -> Any:
        return dump_spec(spec) if isinstance(spec, TimePoint) else spec

    def _existence_facts(self, entity_id: str, timeline_id: str) -> list[EntityFact]:
        view = TimelineView.for_timeline(self.session, timeline_id)

        def where(row: Any) -> list[Any]:
            return [
                row.deleted_at.is_(None),
                row.entity_id == entity_id,
                row.field_key == EXISTS,
                *self.policy.rows(row),
                *self.policy.entity_ref(row.timeline_id),
            ]

        return list(self.session.scalars(view.select(EntityFact, where=where)))

    def segment_out(self, lived: Lived, index: int) -> SegmentOut:
        span, row = lived.spans[index], lived.rows[index]
        start_spec, end_spec = lived.specs[index]
        owner = None if row is None else row.id
        return SegmentOut(
            id=span.id,
            seq=index + 1,
            dimension_id=span.dimension_id,
            timeline_id=span.timeline_id,
            start=self._shown(start_spec, span.dimension_id, owner),
            end=self._shown(end_spec, span.dimension_id, owner),
            start_t=span.start,
            end_t=span.end,
            time_status=None if row is None else row.time_status,
            rate=_rational(span.rate),
            subjective_start=_rational(lived.starts[index]),
            subjective_end=_rational(lived.subjective(index, span.end)),
            departure_event_id=self._event_ref(None if row is None else row.departure_event_id),
            arrival_event_id=self._event_ref(None if row is None else row.arrival_event_id),
            note=None if row is None else row.note,
            visibility="public" if row is None else row.visibility,
        )

    def _shown(self, spec: Any, dimension_id: str, owner: str | None) -> dict[str, Any] | None:
        if spec is None:
            return None
        found = self.times.point(spec, dimension_id, owner=owner)
        if isinstance(found, TimePoint):
            return dump_spec(found)
        return found if isinstance(found, dict) else None

    def _event_ref(self, event_id: str | None) -> str | None:
        if event_id is None or not self.policy.visible_ids(self.session, [event_id]):
            return None
        return event_id

    def worldline_out(self, lived: Lived) -> Worldline:
        return Worldline(
            entity_id=lived.entity.id,
            implicit=lived.implicit,
            personal_dimension_id=lived.personal_dimension_id,
            segments=[self.segment_out(lived, i) for i in range(len(lived.spans))],
        )

    def get(self, entity_id: str, timeline_id: str | None = None) -> Worldline:
        entity = self.entity(entity_id)
        return self.worldline_out(self.lived(entity, timeline_id))

    # --- presence -----------------------------------------------------------------------------

    def presence(
        self, entity_id: str, dimension_id: str, timeline_id: str | None, t: int
    ) -> Presence:
        """§11.4 ``where``: every segment covering ``t`` in the timeline (of the dimension; its
        prime by default). Explicit segments are read through the timeline's view (a branch
        inherits its ancestors' segments before its branch point, and their overrides apply)."""
        entity = self.entity(entity_id)
        dimension = self.entities.load_visible(dimension_id)
        if dimension.kind != DIMENSION or dimension.deleted_at is not None:
            raise _invalid("dimension", f"No dimension {dimension_id}.")
        if timeline_id is None:
            prime = prime_timeline(self.session, dimension_id)
            if prime is None:
                raise _invalid("timeline", "The dimension has no prime timeline.")
            timeline_id = prime.id
        row = self.session.get(Timeline, timeline_id)
        if (
            row is None
            or row.dimension_id != dimension_id
            or not self.policy.visible_ids(self.session, [timeline_id])
        ):
            raise _invalid("timeline", "Not a timeline of this dimension.")
        lived = self.lived(entity, timeline_id if entity.dimension_id == dimension_id else None)
        if lived.implicit:
            indexes = [
                i
                for i, span in enumerate(lived.spans)
                if span.dimension_id == dimension_id and span.covers(t)
            ]
        else:
            positions = {span.id: i for i, span in enumerate(lived.spans)}
            indexes = sorted(
                positions[root]
                for root, (start, end) in self._segments_in(entity.id, timeline_id).items()
                if root in positions and start is not None and end is not None and start <= t <= end
            )
        return Presence(
            entity_id=entity.id,
            dimension_id=dimension_id,
            timeline_id=timeline_id,
            t=t,
            implicit=lived.implicit,
            segments=[self.segment_out(lived, i) for i in indexes],
        )

    def _segments_in(
        self, entity_id: str, timeline_id: str
    ) -> dict[str, tuple[int | None, int | None]]:
        """The entity's segments the timeline sees: root id → the seen row's moments (an
        override row stands for its root, whose place in the worldline it keeps)."""
        view = TimelineView.for_timeline(self.session, timeline_id)

        def where(row: Any) -> list[Any]:
            return [row.entity_id == entity_id, *self.policy.module_rows(SEGMENT_VISIBILITY, row)]

        return {
            row.overrides_id or row.id: (row.start_t, row.end_t)
            for row in self.session.scalars(view.select(WorldlineSegment, where=where))
        }

    # --- the personal timeline ----------------------------------------------------------------

    def personal_timeline(
        self, entity_id: str, include: Iterable[str], timeline_id: str | None = None
    ) -> PersonalTimeline:
        """§11.5: participations, existence changes and jumps by subjective time."""
        entity = self.entity(entity_id)
        lived = self.lived(entity, timeline_id)
        wanted = set(include)
        items: list[PersonalItem] = []
        if "participations" in wanted:
            items.extend(self._participations(lived))
        if "existence" in wanted:
            items.extend(self._existence(lived))
        if "jumps" in wanted:
            items.extend(self._jumps(lived))
        positions = {span.id: i for i, span in enumerate(lived.spans) if span.id is not None}
        items.sort(key=lambda item: _order(item, positions))
        return PersonalTimeline(
            entity_id=entity.id,
            implicit=lived.implicit,
            personal_dimension_id=lived.personal_dimension_id,
            items=items[:MAX_ITEMS],
            truncated=len(items) > MAX_ITEMS,
        )

    def _item(
        self,
        lived: Lived,
        kind: str,
        *,
        dimension_id: str | None,
        timeline_id: str | None,
        t: int | None,
        covering: list[int],
        **extra: Any,
    ) -> PersonalItem:
        chosen = covering[0] if covering else None
        subjective = None if chosen is None or t is None else lived.subjective(chosen, t)
        return PersonalItem(
            kind=kind,  # type: ignore[arg-type]
            subjective_t=None if subjective is None else _rational(subjective),
            age=None if subjective is None else self.age(lived, subjective),
            segment_id=None if chosen is None else lived.spans[chosen].id,
            segment_ids=[s for i in covering if (s := lived.spans[i].id) is not None],
            dimension_id=dimension_id,
            timeline_id=timeline_id,
            t=t,
            **extra,
        )

    @staticmethod
    def _at(span: Span, t: int, index: int) -> dict[str, Any]:
        return {
            "dimension_id": span.dimension_id,
            "timeline_id": span.timeline_id,
            "t": t,
            "covering": [index],
        }

    def _covering(self, lived: Lived, dimension_id: str, timelines: set[str], t: int) -> list[int]:
        return [
            i
            for i, span in enumerate(lived.spans)
            if span.dimension_id == dimension_id
            and span.timeline_id in timelines
            and span.covers(t)
        ]

    def participations(self, lived: Lived) -> list[Participation]:
        """The events the entity takes part in (live ``core.participant`` links the request
        sees), each with the segments covering its start in a timeline of the worldline that sees
        it (§11.4). A link's ``data.segment_id`` chooses the segment: one that doesn't cover the
        event makes the entity absent from it. Without it, the one covering segment is implied,
        and several are ambiguous (the first in worldline order is used)."""
        event_entity = Entity
        links = list(
            self.session.execute(
                select(Link, event_entity)
                .join(event_entity, event_entity.id == Link.source_id)
                .where(
                    Link.target_id == lived.entity.id,
                    Link.link_type == PARTICIPANT,
                    Link.deleted_at.is_(None),
                    Link.overrides_id.is_(None),
                    *self.policy.links(Link),
                    event_entity.kind == EVENT,
                    event_entity.deleted_at.is_(None),
                    *self.policy.entities(event_entity),
                )
                .order_by(Link.id)
            ).all()
        )
        if not links:
            return []
        event_ids = sorted({event.id for _, event in links})
        # The event as each timeline of the worldline sees it (its start may be overridden).
        starts: dict[tuple[str, str], int | None] = {}
        for timeline_id in sorted({s.timeline_id for s in lived.spans if s.timeline_id}):
            view = TimelineView.for_timeline(self.session, timeline_id)
            rows = self.session.scalars(
                view.select(Event, where=lambda row: [row.entity_id.in_(event_ids)])
            )
            for row in rows:
                starts[(timeline_id, row.entity_id)] = row.start_t
        found: list[Participation] = []
        for link, event in links:
            # The timelines of the worldline that see the event, in worldline order.
            seen = [
                (i, span.timeline_id, starts[(span.timeline_id, event.id)])
                for i, span in enumerate(lived.spans)
                if span.timeline_id is not None
                and span.dimension_id == event.dimension_id
                and (span.timeline_id, event.id) in starts
            ]
            covering = [
                i for i, _, start in seen if start is not None and lived.spans[i].covers(start)
            ]
            picked = (link.data or {}).get("segment_id")
            assignment: Assignment
            if isinstance(picked, str):
                covering = [i for i in covering if lived.spans[i].id == picked]
                assignment = "chosen" if covering else "absent"
            elif len(covering) == 1:
                assignment = "implied"
            else:
                assignment = "ambiguous" if covering else "absent"
            place = next((x for x in seen if covering and x[0] == covering[0]), None)
            place = place or (seen[0] if seen else None)
            found.append(
                Participation(
                    link=link,
                    event=event,
                    covering=covering,
                    assignment=assignment,
                    timeline_id=None if place is None else place[1],
                    t=None if place is None else place[2],
                )
            )
        return found

    def _participations(self, lived: Lived) -> list[PersonalItem]:
        items = [
            self._item(
                lived,
                "participation",
                dimension_id=p.event.dimension_id,
                timeline_id=p.timeline_id,
                t=p.t,
                covering=p.covering,
                event_id=p.event.id,
                name=p.event.name,
                roles=[p.link.role] if p.link.role else [],
                assignment=p.assignment,
            )
            for p in self.participations(lived)
        ]
        return _merge_roles(items)

    def _existence(self, lived: Lived) -> list[PersonalItem]:
        """Where the entity starts and stops existing (``core.exists`` bounds), in each timeline
        of the worldline; the implicit worldline's segments are these periods."""
        items: list[PersonalItem] = []
        if lived.implicit:
            for i, span in enumerate(lived.spans):
                start_spec, end_spec = lived.specs[i]
                if start_spec is not None:
                    items.append(
                        self._item(lived, "existence_start", **self._at(span, span.start, i))
                    )
                if end_spec is not None:
                    # The period ends at its (half-open) end: subjective time runs to it.
                    items.append(self._item(lived, "existence_end", **self._at(span, span.end, i)))
            return items
        seen: set[tuple[str, str]] = set()
        timelines = {(s.timeline_id, s.dimension_id) for s in lived.spans if s.timeline_id}
        for timeline_id, dimension_id in sorted(timelines):
            for fact in self._existence_facts(lived.entity.id, timeline_id):
                root = fact.overrides_id or fact.id
                for kind, t in (
                    ("existence_start", fact.valid_from_t),
                    ("existence_end", fact.valid_to_t),
                ):
                    if t is None or (root, kind) in seen:
                        continue
                    seen.add((root, kind))
                    covering = self._covering(lived, dimension_id, {timeline_id}, int(t))
                    items.append(
                        self._item(
                            lived,
                            kind,
                            dimension_id=dimension_id,
                            timeline_id=timeline_id,
                            t=int(t),
                            covering=covering,
                        )
                    )
        return items

    def _jumps(self, lived: Lived) -> list[PersonalItem]:
        """Between consecutive segments: from the end of one to the start of the next (the gaps
        of an implicit worldline are times the entity doesn't exist, not jumps)."""
        items: list[PersonalItem] = []
        if lived.implicit:
            return items
        for i in range(len(lived.spans) - 1):
            here, there = lived.spans[i], lived.spans[i + 1]
            row, following = lived.rows[i], lived.rows[i + 1]
            departure = None if row is None else self._event_ref(row.departure_event_id)
            arrival = None if following is None else self._event_ref(following.arrival_event_id)
            items.append(
                self._item(
                    lived,
                    "jump",
                    **self._at(here, here.end, i),
                    event_id=departure,
                    name=None,
                    to_dimension_id=there.dimension_id,
                    to_timeline_id=there.timeline_id,
                    to_t=there.start,
                    arrival_event_id=arrival,
                )
            )
        return items

    # --- ages ---------------------------------------------------------------------------------

    def _calendar(self, dimension_id: str) -> CompiledCalendar | None:
        if dimension_id not in self._calendars:
            dimension = self.session.get(Dimension, dimension_id)
            calendar_id = None if dimension is None else dimension.default_calendar_id
            found: CompiledCalendar | None = None
            if calendar_id is not None and self.policy.visible_ids(self.session, [calendar_id]):
                try:
                    found = compiled_calendar(self.context, calendar_id)
                except NotFoundError, ConflictError:
                    found = None
            self._calendars[dimension_id] = found
        return self._calendars[dimension_id]

    def age(self, lived: Lived, subjective: Fraction) -> Age:
        """Subjective time as an age: floored, and formatted in the personal clock dimension's
        default calendar (counted from where the worldline starts there, else from its 0)."""
        amount = _floor(subjective)
        return Age(t=amount, display=self._display(lived, amount))

    def _display(self, lived: Lived, amount: int) -> str | None:
        dimension_id = lived.personal_dimension_id
        if dimension_id is None or amount < 0:
            return None
        calendar = self._calendar(dimension_id)
        dimension = self.session.get(Dimension, dimension_id)
        if calendar is None or dimension is None:
            return None
        duration = int(dimension.duration)
        first = next((s for s in lived.spans if s.dimension_id == dimension_id), None)
        origin = 0 if first is None else first.start
        if origin + amount > duration:
            origin = max(0, duration - amount)
        if origin + amount > duration:
            return None
        try:
            found = diff(calendar, origin, origin + amount, calendar.levels[-1], calendar.levels[0])
        except DateError:
            return None
        names = {level.id: level for level in calendar.definition.levels}
        parts = [
            f"{n} {names[level].label if n == 1 else names[level].plural}"
            for level, n in found.amounts.items()
            if n and level in names
        ][:2]
        if not parts:
            finest = names.get(calendar.levels[0])
            return None if finest is None else f"0 {finest.plural}"
        return ", ".join(parts)

    # --- writes -------------------------------------------------------------------------------

    def replace(self, entity_id: str, data: SegmentsPut) -> WorldlineWriteResult:
        """The entity's explicit segments become ``data.segments`` (empty: the implicit worldline
        again)."""
        entity = self.entity(entity_id)
        if not self._can_have_worldline(entity):
            raise _invalid("segments", "Entities of this kind have no worldline.")
        for position, segment in enumerate(data.segments):
            self._check(position, segment)
        delete_segments(self.context, entity.id)
        rows = [
            WorldlineSegment(
                entity_id=entity.id,
                seq=position + 1,
                dimension_id=segment.dimension_id,
                timeline_id=segment.timeline_id,
                start_spec=segment.start,
                end_spec=segment.end,
                rate=ONE if segment.rate is None else segment.rate.model_dump(mode="json"),
                departure_event_id=segment.departure_event_id,
                arrival_event_id=segment.arrival_event_id,
                note=segment.note,
                visibility=segment.visibility,
            )
            for position, segment in enumerate(data.segments)
        ]
        self.session.add_all(rows)
        self.session.flush()
        writer = TimeWriter(self.context)
        for row in rows:
            writer.set_spec(SEGMENT, row.id, "start", row.start_spec)
            writer.set_spec(SEGMENT, row.id, "end", row.end_spec)
        writer.propagate(path="segments")
        for row in rows:
            self.session.refresh(row)
        self._validate(rows)
        return self.written(entity)

    def written(self, entity: Entity) -> WorldlineWriteResult:
        """The worldline after a write, and what the write affected."""
        rows = self.rows_of(entity.id)
        dimensions = sorted(
            {r.dimension_id for r in rows}
            | ({entity.dimension_id} if entity.dimension_id else set())
        )
        affected = Affected(
            entities=[entity.id], dimensions=dimensions, time_changed=True, search_changed=False
        )
        return WorldlineWriteResult(
            worldline=self.worldline_out(self.lived(entity)),
            affected=report_time(self.session, self.context.registry, affected),
        )

    def rows_of(self, entity_id: str) -> list[WorldlineSegment]:
        """The entity's explicit segments (every one: for writes), in worldline order."""
        return list(
            self.session.scalars(
                select(WorldlineSegment)
                .where(
                    WorldlineSegment.entity_id == entity_id,
                    WorldlineSegment.overrides_id.is_(None),
                )
                .order_by(WorldlineSegment.seq, WorldlineSegment.id)
            )
        )

    def _check(self, position: int, segment: SegmentIn) -> None:
        path = f"segments.{position}"
        dimension = self.session.get(Entity, segment.dimension_id)
        if dimension is None or dimension.kind != DIMENSION or dimension.deleted_at is not None:
            raise _invalid(f"{path}.dimension_id", f"No dimension {segment.dimension_id}.")
        timeline = self.session.get(Timeline, segment.timeline_id)
        timeline_entity = self.session.get(Entity, segment.timeline_id)
        if (
            timeline is None
            or timeline_entity is None
            or timeline_entity.deleted_at is not None
            or timeline.dimension_id != segment.dimension_id
        ):
            raise _invalid(f"{path}.timeline_id", "Not a timeline of the segment's dimension.")
        if segment.rate is not None and int(segment.rate.num) <= 0:
            raise _invalid(f"{path}.rate", "A rate must be positive.", "bad_rate")
        for side in ("start", "end"):
            if anchored_elsewhere(self.context, getattr(segment, side), segment.dimension_id):
                raise _invalid(
                    f"{path}.{side}",
                    "A segment is anchored in its own dimension; this anchor is in another one.",
                )
        for side in ("departure_event_id", "arrival_event_id"):
            event_id = getattr(segment, side)
            if event_id is None:
                continue
            event = self.session.get(Entity, event_id)
            if event is None or event.kind != EVENT or event.deleted_at is not None:
                raise _invalid(f"{path}.{side}", f"No event {event_id}.")

    def _validate(self, rows: Sequence[WorldlineSegment]) -> None:
        for position, row in enumerate(rows):
            path = f"segments.{position}"
            for side in ("start", "end"):
                if getattr(row, f"{side}_t") is None:
                    raise _invalid(f"{path}.{side}", "This time point doesn't resolve to a moment.")
            if int(row.start_t or 0) > int(row.end_t or 0):
                raise _invalid(
                    f"{path}.end", "A segment ends before it starts.", "end_before_start"
                )


def _merge_roles(items: list[PersonalItem]) -> list[PersonalItem]:
    """One item per event (several participant links: their roles together)."""
    merged: dict[str | None, PersonalItem] = {}
    for item in items:
        known = merged.get(item.event_id)
        if known is None:
            merged[item.event_id] = item
        else:
            known.roles = sorted({*known.roles, *item.roles})
    return list(merged.values())


def _order(item: PersonalItem, positions: dict[str, int]) -> tuple[Any, ...]:
    """By subjective time, then worldline order (a traveler's later visit can start at an
    earlier world moment), then world time and kind."""
    subjective = (
        None
        if item.subjective_t is None
        else Fraction(int(item.subjective_t.num), int(item.subjective_t.den))
    )
    return (
        subjective is None,
        subjective or Fraction(0),
        positions.get(item.segment_id or "", 0),
        item.t is None,
        0 if item.t is None else int(item.t),
        _KIND_ORDER[item.kind],
        item.name or "",
        item.event_id or "",
    )


def delete_segments(context: VaultContext, entity_id: str) -> None:
    """Delete an entity's segments (their override rows too) with their dependency edges."""
    session = context.session
    rows = list(
        session.scalars(select(WorldlineSegment).where(WorldlineSegment.entity_id == entity_id))
    )
    if not rows:
        return
    index = DependencyIndex(session)
    for row in rows:
        index.drop_record(SEGMENT, row.id)
    for row in sorted(rows, key=lambda r: r.overrides_id is None):
        session.delete(row)
    session.flush()


def purge_segments(context: VaultContext, entity: Entity) -> None:
    """Before an entity is purged: its segments go with it."""
    delete_segments(context, entity.id)
