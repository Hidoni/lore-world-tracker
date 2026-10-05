"""API models of the time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lore.chronology.schema import BaseUnit
from lore.chronology.schema import MomentStr as ChronologyMomentStr
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, EntityName, EntityOut
from lore.core.time.calendars import CalendarSource
from lore.core.types import MomentStr


class TimelineNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    is_prime: bool
    parent_timeline_id: str | None
    branch_point: dict[str, Any] | None = Field(description="The branch point time point.")
    branch_t: MomentStr | None = Field(description="The resolved branch moment.")
    time_status: str | None
    trashed: bool
    children: list[TimelineNode] = Field(description="Branches, by name.")


class TimelineTree(BaseModel):
    dimension_id: str
    items: list[TimelineNode] = Field(
        description="The root timelines: the prime, unless the request may not see it."
    )


class PresetOut(BaseModel):
    id: str
    name: str
    description: str
    origin: str = Field(description="What the preset's origin moment is.")
    duration_seconds: str = Field(
        description="The dimension must last at least this long after the origin (seconds)."
    )
    definition: dict[str, Any] = Field(description="The definition, written in seconds.")


class PresetList(BaseModel):
    items: list[PresetOut]


class TimeSpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_unit: BaseUnit
    duration: ChronologyMomentStr


class CalendarPreviewIn(BaseModel):
    """Exactly one of ``dimension_id`` (an existing dimension) and ``time_spec`` (one about to be
    created, e.g. in the wizard)."""

    model_config = ConfigDict(extra="forbid")

    dimension_id: EntityId | None = None
    time_spec: TimeSpecIn | None = None
    calendar_id: EntityId | None = Field(
        default=None, description="The calendar being edited (detects self-references)."
    )
    source: CalendarSource


class WizardCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: EntityName
    summary: str = ""
    source: CalendarSource


class DimensionWizardIn(BaseModel):
    """A dimension with its time spec, its prime timeline and its first calendar, in one go."""

    model_config = ConfigDict(extra="forbid")

    name: EntityName
    summary: str = ""
    visibility: Visibility | None = None
    ext: dict[str, Any] = Field(description="The time spec: `{base_unit, duration, present?}`.")
    calendar: WizardCalendar


class DimensionCreated(BaseModel):
    dimension: EntityOut
    prime_timeline: EntityOut
    calendar: EntityOut
