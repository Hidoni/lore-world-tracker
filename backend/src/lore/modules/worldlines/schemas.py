"""Request and response bodies of the worldlines module (``time-model.md`` §11)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from lore.chronology.schema import Rational, TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId
from lore.core.types import Affected, MomentStr


class SegmentIn(BaseModel):
    dimension_id: EntityId
    timeline_id: EntityId = Field(description="A timeline of `dimension_id`.")
    start: TimePoint = Field(description="May be anchored to events of that timeline.")
    end: TimePoint
    rate: Rational | None = Field(
        default=None,
        description="Subjective base units per base unit of the dimension (default 1; > 0).",
    )
    departure_event_id: EntityId | None = Field(
        default=None, description="The event of the jump into this segment's previous one."
    )
    arrival_event_id: EntityId | None = Field(
        default=None, description="The event of the jump into this segment."
    )
    note: str | None = Field(default=None, max_length=5000)
    visibility: Visibility = "public"


class SegmentsPut(SuppressIn):
    """The worldline's segments in the entity's own order (an empty list: back to the implicit
    worldline)."""

    segments: list[SegmentIn] = Field(max_length=1000)


class SegmentOut(BaseModel):
    id: str | None = Field(description="Null for the implicit worldline's segments.")
    seq: int = Field(description="Its place in the entity's own order, from 1.")
    dimension_id: str
    timeline_id: str | None
    start: dict[str, Any] | None
    end: dict[str, Any] | None
    start_t: MomentStr | None
    end_t: MomentStr | None
    time_status: str | None
    rate: Rational
    subjective_start: Rational | None = Field(
        description="Subjective time at its start (exact, personal clock base units); null "
        "while a segment before it is unresolved."
    )
    subjective_end: Rational | None
    departure_event_id: str | None
    arrival_event_id: str | None
    note: str | None
    visibility: Visibility


class Worldline(BaseModel):
    entity_id: str
    implicit: bool = Field(description="No explicit segments: the existence periods (§11.2).")
    personal_dimension_id: str | None = Field(
        description="Whose base unit subjective time counts in: the home dimension, or "
        "segment 1's for a multiversal entity."
    )
    segments: list[SegmentOut]


class WorldlineWriteResult(BaseModel):
    worldline: Worldline
    affected: Affected


class Presence(BaseModel):
    entity_id: str
    dimension_id: str
    timeline_id: str
    t: MomentStr
    implicit: bool
    segments: list[SegmentOut] = Field(
        description="Every segment covering `t` there: a time traveler can be present twice."
    )


class Age(BaseModel):
    t: MomentStr = Field(description="Subjective time, floored to a base unit.")
    display: str | None = Field(
        description="In the personal clock dimension's default calendar (\"34 years, 2 "
        'months"); null without one.'
    )


class PersonalItem(BaseModel):
    kind: Literal["participation", "existence_start", "existence_end", "jump"]
    subjective_t: Rational | None = Field(
        description="Exact; null when no segment covers it (absent) or it is unresolved."
    )
    age: Age | None
    segment_id: str | None = Field(description="The segment it happens in, when known.")
    segment_ids: list[str] = Field(
        description="Every segment covering it (several: ambiguous, the first is used)."
    )
    dimension_id: str | None
    timeline_id: str | None
    t: MomentStr | None = Field(description="World time (for a jump: the departure).")
    event_id: str | None = Field(
        default=None, description="The event (participations; a jump's departure event)."
    )
    name: str | None = None
    roles: list[str] = []
    assignment: Literal["chosen", "implied", "ambiguous", "absent"] | None = Field(
        default=None,
        description="Participations (§11.4): the segment the link chose, the one covering "
        "segment (implied), several (ambiguous: the first is used) or none (absent).",
    )
    to_dimension_id: str | None = Field(default=None, description="Jumps: where to.")
    to_timeline_id: str | None = None
    to_t: MomentStr | None = None
    arrival_event_id: str | None = None


class PersonalTimeline(BaseModel):
    entity_id: str
    implicit: bool
    personal_dimension_id: str | None
    items: list[PersonalItem] = Field(
        description="By subjective time (items without one last, by world time)."
    )
    truncated: bool


# --- time travel (the wizard's helper) ---------------------------------------------------------


class Departure(BaseModel):
    """When the entity leaves: an event (it moves with it) or a time point, in one of the
    worldline's timelines; the last segment that covers it is cut there."""

    event_id: EntityId | None = Field(default=None, description="Leave when this event starts.")
    at: TimePoint | None = Field(default=None, description="Leave at this moment.")
    timeline_id: EntityId | None = Field(
        default=None,
        description="With `at`: the timeline it is in (default: the last segment covering it).",
    )
    event_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="With `at`: create a departure event of this name there.",
    )


class NewBranch(BaseModel):
    """A branch created for the arrival (the `branches` module must be on)."""

    name: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=5000)
    parent_timeline_id: EntityId | None = Field(
        default=None, description="Default: the destination dimension's prime timeline."
    )
    branch_point: TimePoint | None = Field(default=None, description="Default: the arrival moment.")


class Destination(BaseModel):
    dimension_id: EntityId
    timeline_id: EntityId | None = Field(
        default=None, description="Default: the dimension's prime (or `new_branch`)."
    )
    new_branch: NewBranch | None = None
    arrival: TimePoint
    until: TimePoint | None = Field(
        default=None, description="Where the new segment ends (default: the end of time)."
    )
    rate: Rational | None = None
    event_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="Create an arrival event of this name at the arrival.",
    )


class TimeTravelIn(SuppressIn):
    departure: Departure
    destination: Destination
    note: str | None = Field(default=None, max_length=5000)


class TimeTravelResult(WorldlineWriteResult):
    timeline_id: str = Field(description="Where the entity arrived (a new branch, if asked).")
    branch_id: str | None = None
    departure_event_id: str | None = None
    arrival_event_id: str | None = None
