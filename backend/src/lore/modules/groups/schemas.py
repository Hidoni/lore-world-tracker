"""API schemas of the groups module."""

from pydantic import BaseModel, Field

from lore.core.links.schemas import EntityLink
from lore.core.types import MomentStr


class Membership(BaseModel):
    group_id: str = Field(description="The group (or sub-group) the member belongs to.")
    item: EntityLink


class Members(BaseModel):
    items: list[Membership]


class Leadership(BaseModel):
    item: EntityLink
    from_t: MomentStr | None = Field(description="Start of the validity (`null`: timeless).")
    to_t: MomentStr | None


class Leaders(BaseModel):
    items: list[Leadership] = Field(
        description="Timeless leaders first, then by the start of their validity."
    )
