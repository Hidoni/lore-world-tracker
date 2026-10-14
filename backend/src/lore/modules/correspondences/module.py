"""The correspondences module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.correspondences.consistency import CONSISTENCY_RULES
from lore.modules.correspondences.router import router

MODULE = ModuleSpec(
    id="correspondences",
    name="Correspondences",
    description="Cross-dimension time: which moments of two dimensions happen at the same time.",
    routers=(router,),
    consistency_rules=CONSISTENCY_RULES,
)
