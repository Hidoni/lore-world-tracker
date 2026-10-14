"""The graph module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.graph.router import router

MODULE = ModuleSpec(
    id="graph",
    name="Graph",
    description="An explorable graph of entities and their links, mentions and hierarchy.",
    routers=(router,),
)
