"""The languages module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.languages.kinds import LANGUAGE_KIND, WRITING_SYSTEM_KIND
from lore.modules.languages.links import LINK_TYPES
from lore.modules.languages.router import router

MODULE = ModuleSpec(
    id="languages",
    name="Languages",
    description="Languages and writing systems, their families and their speakers.",
    kinds=(LANGUAGE_KIND, WRITING_SYSTEM_KIND),
    link_types=LINK_TYPES,
    routers=(router,),
)
