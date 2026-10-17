"""The groups module's spec."""

from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.groups.consistency import CONSISTENCY_RULES
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
    consistency_rules=CONSISTENCY_RULES,
    static_reads=(
        StaticRead(
            "{id}/members",
            kind="group",
            variants=((("include_subgroups", "false"),), (("include_subgroups", "true"),)),
            as_of=True,
        ),
        StaticRead("{id}/leaders", kind="group", as_of=True),
        StaticRead("{id}/territory", kind="group", as_of=True),
        StaticRead("{id}/org-chart", kind="group", variants=((("depth", "3"),),), as_of=True),
    ),
)
