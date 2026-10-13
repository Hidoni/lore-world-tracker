"""API schemas of the groups module."""

from typing import Literal

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility
from lore.core.links.schemas import EntityLink
from lore.core.types import MomentStr


class Membership(BaseModel):
    group_id: str = Field(description="The group (or sub-group) the member belongs to.")
    item: EntityLink
    from_t: MomentStr | None = Field(
        description="Start of the membership's validity (`null`: open; resolved validity comes "
        "with temporal links)."
    )
    to_t: MomentStr | None


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


class OrgLeader(BaseModel):
    id: str
    name: str
    title: str | None = Field(description="The `led_by` link's `data.title`.")


class OrgUnit(BaseModel):
    id: str
    name: str
    visibility: Visibility
    parent_id: str | None = Field(description="The unit above it in the chart (`null`: the group).")
    via: Literal["root", "subgroup", "part_of"] = Field(
        description="How it is below its parent: a sub-group (`parent_id`) or a `part_of` link."
    )
    depth: int
    leaders: list[OrgLeader]
    member_count: int = Field(description="Its own members (`member_of`), not its sub-groups'.")


class OrgChart(BaseModel):
    root_id: str
    units: list[OrgUnit] = Field(description="The group first, then level by level.")
    truncated: bool
