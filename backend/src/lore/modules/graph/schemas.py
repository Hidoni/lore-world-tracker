"""The graph's API shapes (``docs/modules/graph.md``, API)."""

from typing import Literal

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    kind: str
    name: str
    dimension_id: str | None
    degree: int = Field(description="Edges of the node in the response's edge set.")
    existence: Literal["exists", "unknown", "possible"] | None = Field(
        description="Existence at `at` (entities that don't exist then are left out); `null` "
        "without `at`."
    )


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["link", "mention", "parent"] = Field(
        description="`link`: a link (source → target as stored); `mention`: the source's text "
        "mentions the target; `parent`: the source is the target's parent."
    )
    link_type: str | None
    label: str | None = Field(description="The link's role, if any.")
    weight: int = Field(description="1, or the number of mentions.")


class Graph(BaseModel):
    nodes: list[GraphNode] = Field(description="By degree, then name.")
    edges: list[GraphEdge]
    truncated: bool = Field(
        description="More nodes matched than `limit`: the highest-degree ones are kept."
    )
