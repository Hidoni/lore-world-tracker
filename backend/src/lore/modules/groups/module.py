"""The groups module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.groups.kinds import GROUP_KIND
from lore.modules.groups.links import LINK_TYPES
from lore.modules.groups.router import router

MODULE = ModuleSpec(
    id="groups",
    name="Groups",
    description="Organizations with sub-groups, members, leaders, relations and territory.",
    kinds=(GROUP_KIND,),
    link_types=LINK_TYPES,
    routers=(router,),
)
