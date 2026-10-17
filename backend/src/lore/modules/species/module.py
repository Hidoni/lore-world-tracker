"""The species module's spec."""

from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.species.consistency import CONSISTENCY_RULES
from lore.modules.species.kinds import SPECIES_KIND
from lore.modules.species.links import LINK_TYPES
from lore.modules.species.router import router

MODULE = ModuleSpec(
    id="species",
    name="Species",
    description="Peoples, creatures and organisms with subspecies, descent and origin.",
    kinds=(SPECIES_KIND,),
    link_types=LINK_TYPES,
    routers=(router,),
    consistency_rules=CONSISTENCY_RULES,
    static_reads=(
        StaticRead("{id}/members", kind="species", as_of=True),
        StaticRead("descent-tree", dimension=True),
    ),
)
