"""Routes of the graph module, mounted at ``/api/v1/vaults/{vault_id}/m/graph``."""

import json
from typing import Annotated

from fastapi import APIRouter, Query, Response

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.modules.graph.schemas import Graph
from lore.modules.graph.service import GraphReader
from lore.modules.graph.service import Query as GraphQuery

router = APIRouter(tags=["graph"])


@router.get("/graph", name="graph", response_model=Graph)
def get_graph(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="Entities of a dimension (and multiversal ones)."),
    ] = None,
    center: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="The local graph around an entity.")
    ] = None,
    depth: Annotated[int, Query(ge=1, le=4, description="Steps from `center`.")] = 1,
    kinds: Annotated[list[str] | None, Query(alias="kind", description="Kinds of nodes.")] = None,
    link_types: Annotated[
        list[str] | None, Query(alias="link_type", description="Link types of `link` edges.")
    ] = None,
    tags: Annotated[
        list[str] | None, Query(alias="tag", description="Tag ids; nodes need any of them.")
    ] = None,
    include_mentions: bool = True,
    include_hierarchy: bool = True,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
    limit: Annotated[int, Query(ge=1, le=20000, description="Nodes at most.")] = 5000,
) -> Response:
    """The graph of the entities the request sees and the links, mentions and parent edges
    between them: the whole vault (or a dimension), or the neighborhood of ``center``. With
    ``at`` only entities existing then and links valid then. Over ``limit`` nodes, the
    highest-degree ones (``truncated``). ``404`` for a center or timeline the request may not
    see."""
    query = GraphQuery(
        dimension=dimension, center=center, depth=depth, kinds=kinds or (),
        link_types=link_types or (), tags=tags or (), include_mentions=include_mentions,
        include_hierarchy=include_hierarchy, timeline=timeline, at=at, limit=limit,
    )  # fmt: skip
    body = GraphReader(VaultContext(vault, session, registry), policy).graph(query)
    # Serialized directly: validating 50k edges against the model would take most of the
    # budget (graph.md), and the service builds them in its shape.
    return Response(json.dumps(body, separators=(",", ":")), media_type="application/json")
