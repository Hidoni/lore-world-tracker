"""The graph module's spec."""

from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.graph.router import router

MODULE = ModuleSpec(
    id="graph",
    name="Graph",
    description="An explorable graph of entities and their links, mentions and hierarchy.",
    routers=(router,),
    static_reads=(
        # The graph page as it opens (every entity, or the time context's dimension), and the
        # local graph of each entity (1 or 2 steps).
        StaticRead("graph", dimension=True, as_of=True),
        StaticRead(
            "graph",
            kind="*",
            variants=((("center", "{id}"), ("depth", "1")), (("center", "{id}"), ("depth", "2"))),
            as_of=True,
        ),
    ),
)
