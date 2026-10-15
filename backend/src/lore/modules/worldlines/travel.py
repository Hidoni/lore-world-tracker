"""Time travel in one request (``docs/modules/worldlines.md``, the wizard's helper).

The entity leaves at a departure (an event, which the cut then follows, or a time point) in the
last segment of its worldline that covers it, and arrives in a destination timeline (an existing
one, the dimension's prime, or a new branch): that segment ends at the departure, the rest of it
is no longer lived, and a new segment from the arrival (to ``until``, else the end of time) comes
right after it; the segments after it stay. An implicit worldline becomes explicit first.
Departure and arrival events can be created, and the entity takes part in them (each link names
its segment). Everything runs in the request's transaction: a refusal anywhere undoes it all.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from lore.chronology.schema import Rational, TimePoint
from lore.core.entities.models import Entity
from lore.core.entities.schemas import EntityCreate
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.links.schemas import LinkCreate
from lore.core.links.service import LinkService
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.time.branches import create_branch
from lore.core.time.dimensions import prime_timeline
from lore.core.time.models import Dimension, Timeline
from lore.core.time.resolve import Resolver
from lore.core.time.specs import dump_spec, parse_time_point
from lore.core.visibility import AUTHOR
from lore.modules.worldlines.schemas import (
    Departure,
    SegmentIn,
    SegmentsPut,
    TimeTravelIn,
    TimeTravelResult,
)
from lore.modules.worldlines.service import Worldlines

EVENT = "event"
DIMENSION = "dimension"
PARTICIPANT = "core.participant"


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def absolute(t: int) -> TimePoint:
    return parse_time_point({"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"})


def start_of(event_id: str) -> TimePoint:
    """A time point at an event's start (it moves with the event)."""
    return parse_time_point({
        "anchor": {
            "kind": "relative",
            "ref": {"type": EVENT, "id": event_id, "slot": "start"},
            "offset": {"kind": "base", "units": "0"},
        },
        "precision": "base",
    })  # fmt: skip


@dataclass
class _Plan:
    segments: list[SegmentIn]
    index: int
    """The segment cut at the departure; the new one comes right after it."""


@contextmanager
def _paths(index: int) -> Iterator[None]:
    """Errors of the replaced segments as the wizard's fields: the cut segment's end is the
    departure, the new segment's start and end are the arrival and `until`."""
    try:
        yield
    except InvalidInputError as error:
        renamed = {
            f"segments.{index}.end": "departure",
            f"segments.{index + 1}.start": "destination.arrival",
            f"segments.{index + 1}.end": "destination.until",
            f"segments.{index + 1}.timeline_id": "destination.timeline_id",
            f"segments.{index + 1}.dimension_id": "destination.dimension_id",
            f"segments.{index + 1}.rate": "destination.rate",
        }
        items = [
            ErrorItem(
                path=renamed.get(item["path"], item["path"]),
                code=item["code"],
                message=item["message"],
            )
            for item in error.errors or []
        ]
        raise InvalidInputError(error.detail, errors=items) from error


class TimeTravel:
    """``POST /m/worldlines/entities/{id}/time-travel`` (authors)."""

    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.worldlines = Worldlines(context, AUTHOR)
        self.entities = EntityService(context, AUTHOR)

    def run(self, entity_id: str, data: TimeTravelIn) -> TimeTravelResult:
        entity = self.worldlines.entity(entity_id)
        if not self.worldlines.entities.kinds.get(entity.kind) or not (
            self.worldlines.entities.kinds[entity.kind].definition.capabilities.can_have_worldline
        ):
            raise _invalid("entity", "Entities of this kind have no worldline.")
        departure = data.departure
        if (departure.event_id is None) == (departure.at is None):
            raise _invalid("departure", "Leave at an event or at a moment (one of them).")
        if departure.event_id is not None and departure.event_name is not None:
            raise _invalid("departure.event_name", "The departure is already an event.")
        plan = self._plan(entity, departure)
        cut = plan.segments[plan.index]
        destination_timeline, branch_id = self._destination(data)

        departure_event = departure.event_id
        if departure.event_name is not None and departure.at is not None:
            departure_event = self._event(departure.event_name, cut.dimension_id,
                                          cut.timeline_id, departure.at)  # fmt: skip
        departure_point = departure.at if departure_event is None else start_of(departure_event)
        assert departure_point is not None
        arrival_event = None
        arrival = data.destination.arrival
        if data.destination.event_name is not None:
            arrival_event = self._event(data.destination.event_name,
                                        data.destination.dimension_id, destination_timeline,
                                        arrival)  # fmt: skip
            arrival = start_of(arrival_event)
        until = data.destination.until
        if until is None:
            dimension = self.session.get(Dimension, data.destination.dimension_id)
            until = absolute(0 if dimension is None else int(dimension.duration))

        segments = list(plan.segments)
        segments[plan.index] = cut.model_copy(
            update={"end": departure_point, "departure_event_id": departure_event}
        )
        segments.insert(
            plan.index + 1,
            SegmentIn(
                dimension_id=data.destination.dimension_id,
                timeline_id=destination_timeline,
                start=arrival,
                end=until,
                rate=data.destination.rate,
                arrival_event_id=arrival_event,
                note=data.note,
            ),
        )
        with _paths(plan.index):
            written = self.worldlines.replace(
                entity.id, SegmentsPut(segments=segments, suppress=data.suppress)
            )
        ids = [segment.id for segment in written.worldline.segments]
        links = LinkService(self.session, self.context.registry, vault=self.context.vault)
        for event_id, index, role in ((departure_event, plan.index, "departs"),
                                      (arrival_event, plan.index + 1, "arrives")):  # fmt: skip
            segment_id = ids[index] if index < len(ids) else None
            if event_id is None or segment_id is None:
                continue
            links.add(
                LinkCreate(
                    link_type=PARTICIPANT,
                    source_id=event_id,
                    target_id=entity.id,
                    role=role,
                    data={"segment_id": segment_id},
                )
            )
        result = self.worldlines.written(entity)
        return TimeTravelResult(
            worldline=result.worldline,
            affected=result.affected,
            timeline_id=destination_timeline,
            branch_id=branch_id,
            departure_event_id=departure_event,
            arrival_event_id=arrival_event,
        )

    # --- the plan ---------------------------------------------------------------------------

    def _current(self, entity: Entity) -> list[SegmentIn]:
        """The worldline as segments to write: the explicit ones, else the implicit ones."""
        lived = self.worldlines.lived(entity)
        if not lived.implicit:
            return [
                SegmentIn(
                    dimension_id=row.dimension_id,
                    timeline_id=row.timeline_id,
                    start=parse_time_point(row.start_spec),
                    end=parse_time_point(row.end_spec),
                    rate=Rational(**row.rate),
                    departure_event_id=row.departure_event_id,
                    arrival_event_id=row.arrival_event_id,
                    note=row.note,
                    visibility=row.visibility,
                )
                for row in self.worldlines.rows_of(entity.id)
            ]
        return [
            SegmentIn(
                dimension_id=span.dimension_id,
                timeline_id=span.timeline_id or "",
                start=absolute(span.start),
                end=absolute(span.end),
            )
            for span in lived.spans
        ]

    def _plan(self, entity: Entity, departure: Departure) -> _Plan:
        segments = self._current(entity)
        if not segments:
            raise _invalid("departure", "The entity has no worldline to leave.")
        found = None
        for index in range(len(segments) - 1, -1, -1):
            segment = segments[index]
            if departure.timeline_id is not None and segment.timeline_id != departure.timeline_id:
                continue
            t = self._moment(segment, departure)
            start = self._moment_of(segment, segment.start)
            end = self._moment_of(segment, segment.end)
            if None not in (t, start, end) and start <= t <= end:  # type: ignore[operator]
                found = index
                break
        if found is None:
            raise _invalid("departure", "The departure isn't during the entity's worldline.")
        return _Plan(segments, found)

    def _moment(self, segment: SegmentIn, departure: Departure) -> int | None:
        point = departure.at if departure.event_id is None else start_of(departure.event_id)
        assert point is not None
        if departure.event_id is not None:
            event = self.session.get(Entity, departure.event_id)
            if event is None or event.kind != EVENT or event.deleted_at is not None:
                raise _invalid("departure.event_id", f"No event {departure.event_id}.")
            if event.dimension_id != segment.dimension_id:
                return None
        return self._moment_of(segment, point)

    def _moment_of(self, segment: SegmentIn, point: TimePoint) -> int | None:
        resolution = Resolver(self.context, segment.dimension_id, segment.timeline_id).resolve(
            point
        )
        return resolution.t if resolution.ok else None

    # --- destination and events -------------------------------------------------------------

    def _destination(self, data: TimeTravelIn) -> tuple[str, str | None]:
        """The arrival timeline (created when a new branch is asked for) and the branch's id."""
        target = data.destination
        dimension = self.session.get(Entity, target.dimension_id)
        if dimension is None or dimension.kind != DIMENSION or dimension.deleted_at is not None:
            raise _invalid("destination.dimension_id", f"No dimension {target.dimension_id}.")
        if target.new_branch is not None:
            if target.timeline_id is not None:
                raise _invalid("destination.new_branch", "Give a timeline or a new branch.")
            if "branches" not in enabled_modules(self.session, self.context.registry):
                raise _invalid("destination.new_branch", "Branches are off in this vault.",
                               "module_disabled")  # fmt: skip
            branch = target.new_branch
            parent = branch.parent_timeline_id
            if parent is None:
                prime = prime_timeline(self.session, target.dimension_id)
                parent = None if prime is None else prime.id
            row = None if parent is None else self.session.get(Timeline, parent)
            if row is None or row.dimension_id != target.dimension_id:
                raise _invalid("destination.new_branch.parent_timeline_id",
                               "Not a timeline of the destination dimension.")  # fmt: skip
            created = create_branch(
                self.context,
                AUTHOR,
                parent_timeline_id=row.entity_id,
                branch_point=branch.branch_point or target.arrival,
                name=branch.name,
                summary=branch.summary,
            )
            return created.entity.id, created.entity.id
        if target.timeline_id is not None:
            return target.timeline_id, None
        prime = prime_timeline(self.session, target.dimension_id)
        if prime is None:
            raise _invalid("destination.dimension_id", "The dimension has no prime timeline.")
        return prime.id, None

    def _event(self, name: str, dimension_id: str, timeline_id: str, at: TimePoint) -> str:
        """An instant event in the timeline (branch-only in a branch)."""
        prime = self.session.get(Timeline, timeline_id)
        branch = None if prime is None or prime.is_prime else timeline_id
        result = self.entities.create(
            EntityCreate(
                kind=EVENT,
                name=name,
                dimension_id=dimension_id,
                ext={"start": dump_spec(at), "end": {"kind": "instant"}},
            ),
            timeline_id=branch,
        )
        return result.entity.id
