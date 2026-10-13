"""API schemas of the species module."""

from typing import Literal

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility


class DescentNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    dimension_id: str | None
    parent_id: str | None = Field(description="The species it is a subspecies of, if shown.")


class DescentEdge(BaseModel):
    id: str = Field(description="The link's id, or `subspecies:<child id>` for a subspecies.")
    kind: Literal["descended_from", "subspecies"]
    source_id: str = Field(description="The descendant or the subspecies.")
    target_id: str = Field(description="The ancestor or the parent species.")


class DescentTree(BaseModel):
    nodes: list[DescentNode]
    edges: list[DescentEdge]
    truncated: bool
