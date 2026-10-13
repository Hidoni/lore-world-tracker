"""API schemas of the locations module."""

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility
from lore.core.time.schemas import EventDisplay
from lore.core.types import MomentStr


class LocationNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    dimension_id: str | None
    parent_id: str | None
    multiversal: bool
    location_type: str | None = Field(
        description="The `location_type` option key (`null`: none, or hidden from the request)."
    )
    child_count: int = Field(description="Child locations the request sees.")
    children: list[LocationNode] | None = Field(
        description="The child locations, when within `depth` (`null`: not loaded)."
    )


class LocationTree(BaseModel):
    root_id: str | None
    items: list[LocationNode]
    truncated: bool = Field(description="Some levels were cut at `limit` nodes.")


class LocationEvent(BaseModel):
    id: str
    name: str
    visibility: Visibility
    start_t: MomentStr | None
    end_t: MomentStr | None
    time_status: str | None
    importance: int
    display: EventDisplay
    site_ids: list[str] = Field(
        description="The listed locations (this one or its descendants) where it took place."
    )


class LocationEvents(BaseModel):
    items: list[LocationEvent]
    truncated: bool
