"""The characters module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.characters.kinds import CHARACTER_KIND
from lore.modules.characters.links import LINK_TYPES
from lore.modules.characters.router import router

MODULE = ModuleSpec(
    id="characters",
    name="Characters",
    description="People with family, social and custom relationships, taking part in events.",
    kinds=(CHARACTER_KIND,),
    link_types=LINK_TYPES,
    routers=(router,),
)
