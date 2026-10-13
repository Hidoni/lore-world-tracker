"""The misc module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.misc.kinds import MISC

MODULE = ModuleSpec(
    id="misc",
    name="Miscellaneous",
    description="Entries that don't fit elsewhere: concepts, technologies, topics. A misc entry "
    "can be the parent of entities of any kind.",
    kinds=(MISC,),
)
