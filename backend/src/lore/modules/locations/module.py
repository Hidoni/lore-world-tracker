"""The locations module's spec."""

from lore.core.modules import ModuleSpec
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
)
