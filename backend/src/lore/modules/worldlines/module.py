"""The worldlines module's spec."""

from lore.core.modules import ModuleSpec
from lore.modules.worldlines.consistency import CONSISTENCY_RULES
from lore.modules.worldlines.router import router
from lore.modules.worldlines.service import purge_segments

MODULE = ModuleSpec(
    id="worldlines",
    name="Worldlines",
    description="Personal timelines: time travelers live events in their own order and age "
    "at their own rate.",
    routers=(router,),
    purge_hooks=(purge_segments,),
    consistency_rules=CONSISTENCY_RULES,
)
