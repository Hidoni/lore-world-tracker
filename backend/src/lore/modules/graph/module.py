"""The graph module's spec."""

from collections.abc import Mapping, Sequence
from typing import Any

from lore.core.modules import ModuleSpec, VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.graph.router import router
from lore.modules.graph.service import GraphReader


def _static_data(
    context: VaultContext, policy: VisibilityPolicy, moments: Mapping[str, Sequence[int]]
) -> dict[str, Any]:
    """A static export computes every graph in the browser (``static-graph.ts``)."""
    return {"graph": GraphReader(context, policy).static_data(moments)}


MODULE = ModuleSpec(
    id="graph",
    name="Graph",
    description="An explorable graph of entities and their links, mentions and hierarchy.",
    routers=(router,),
    static_data=_static_data,
)
