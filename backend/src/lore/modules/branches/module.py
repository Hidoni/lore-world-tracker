"""The branches module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.branches.consistency import CONSISTENCY_RULES
from lore.modules.branches.router import router

MODULE = ModuleSpec(
    id="branches",
    name="Branches",
    description="Alternate timelines: “what if…” branches of a dimension's history.",
    routers=(router,),
    consistency_rules=CONSISTENCY_RULES,
)
