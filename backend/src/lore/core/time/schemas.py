"""API models of the time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Any

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility
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
