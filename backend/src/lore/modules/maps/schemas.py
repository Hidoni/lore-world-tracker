"""Request and response models of the maps module (``docs/modules/maps.md``, API)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import Color, EntityId, Icon, SortKey
from lore.core.types import Affected, MomentStr

MapName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Coordinate = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Scale(BaseModel):
    units_per_pixel: Annotated[str, StringConstraints(pattern=r"^[0-9]+(\.[0-9]+)?$")] = Field(
        description="A decimal string."
    )
    unit: Annotated[str, StringConstraints(min_length=1, max_length=20)]


class MapOut(BaseModel):
    id: str
    location_id: str
    media_id: str
    name: str
    description: str
    width: int
    height: int
    scale: Scale | None
    sort_key: str | None
    visibility: Visibility
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class MapList(BaseModel):
    items: list[MapOut]


class MapCreate(SuppressIn):
    location_id: EntityId = Field(description="The location the map depicts.")
    media_id: EntityId = Field(description="Its image: a raster image of the media library.")
    name: MapName
    description: Description = ""
    scale: Scale | None = None
    sort_key: SortKey | None = None
    visibility: Visibility = "public"


class MapUpdate(SuppressIn):
    revision: int
    media_id: EntityId | None = Field(default=None, description="Another image for the map.")
    name: MapName | None = None
    description: Description | None = None
    scale: Scale | None = None
    sort_key: SortKey | None = None
    visibility: Visibility | None = None


class PinTarget(BaseModel):
    id: str
    kind: str
    name: str
    icon: str | None
    color: str | None


type Shown = Literal["certain", "possible"]


class PinOut(BaseModel):
    id: str
    map_id: str
    target: PinTarget | None
    label: str | None = Field(description="As stored (`display_label` falls back to the target).")
    display_label: str
    x: float
    y: float
    icon: str | None
    color: str | None
    child_map_id: str | None = Field(description="As stored.")
    drill_map_id: str | None = Field(
        description="Where clicking drills in: `child_map_id`, else the target location's first "
        "map (the request sees)."
    )
    visibility: Visibility
    timeline_id: str | None
    overrides_id: str | None
    valid_from: TimePoint | None
    valid_to: TimePoint | None
    valid_from_t: MomentStr | None
    valid_to_t: MomentStr | None
    time_status: str | None
    revision: int
    shown: Shown = Field(
        default="certain",
        description="At the cursor: `possible` when a bound's uncertainty (or the target's "
        "existence) leaves it open.",
    )


class MapCrumb(BaseModel):
    map_id: str
    name: str
    location_id: str


class MapDetail(MapOut):
    pins: list[PinOut]
    breadcrumbs: list[MapCrumb] = Field(
        description="The maps of the location's ancestors, outermost first (each one's first "
        "map the request sees)."
    )


class PinCreate(SuppressIn):
    target_entity_id: EntityId | None = Field(default=None, description="null: a label pin.")
    label: Label | None = None
    x: Coordinate
    y: Coordinate
    icon: Icon | None = None
    color: Color | None = None
    child_map_id: EntityId | None = None
    visibility: Visibility = "public"
    timeline_id: EntityId | None = Field(
        default=None, description="With a validity: the timeline it is in."
    )
    valid_from: TimePoint | None = None
    valid_to: TimePoint | None = None


class PinUpdate(SuppressIn):
    revision: int
    target_entity_id: EntityId | None = None
    label: Label | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    icon: Icon | None = None
    color: Color | None = None
    child_map_id: EntityId | None = None
    visibility: Visibility | None = None
    timeline_id: EntityId | None = None
    valid_from: TimePoint | None = None
    valid_to: TimePoint | None = None


class MapWriteResult(BaseModel):
    map: MapOut
    affected: Affected


class PinWriteResult(BaseModel):
    pin: PinOut
    affected: Affected


class EntityPin(BaseModel):
    pin: PinOut
    map: MapOut


class EntityPins(BaseModel):
    entity_id: str
    items: list[EntityPin]
