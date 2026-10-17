"""The locations module's spec."""

from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.locations.consistency import CONSISTENCY_RULES
from lore.modules.locations.kinds import LOCATION_KIND
from lore.modules.locations.links import LINK_TYPES
from lore.modules.locations.router import router

MODULE = ModuleSpec(
    id="locations",
    name="Locations",
    description="Places from galaxies to rooms, nested inside each other, and event sites.",
    kinds=(LOCATION_KIND,),
    link_types=LINK_TYPES,
    routers=(router,),
    consistency_rules=CONSISTENCY_RULES,
    static_reads=(
        StaticRead("tree", variants=((("depth", "6"), ("limit", "500")),)),
        StaticRead(
            "tree",
            kind="location",
            variants=((("root", "{id}"),), (("root", "{id}"), ("depth", "6"), ("limit", "500"))),
        ),
        StaticRead(
            "{id}/events",
            kind="location",
            variants=((("include_descendants", "true"),), (("include_descendants", "false"),)),
            timeline=True,
        ),
        StaticRead("{id}/residents", kind="location", as_of=True),
    ),
)
