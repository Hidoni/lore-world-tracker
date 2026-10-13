"""API schemas of the languages module."""

from typing import Literal

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility


class FamilyNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    dimension_id: str | None
    parent_id: str | None = Field(description="The language it is a dialect of, if shown.")


class FamilyEdge(BaseModel):
    id: str = Field(description="The link's id, or `dialect:<child id>` for a dialect.")
    kind: Literal["descended_from", "borrowed_from", "dialect"]
    source_id: str = Field(description="The descendant, the borrower or the dialect.")
    target_id: str = Field(description="The ancestor, the lender or the parent language.")


class FamilyTree(BaseModel):
    nodes: list[FamilyNode]
    edges: list[FamilyEdge]
    truncated: bool
