"""The characters module's spec."""

from collections.abc import Mapping, Sequence
from typing import Any

from lore.core.modules import ModuleSpec, StaticRead, VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.characters.consistency import CONSISTENCY_RULES
from lore.modules.characters.kinds import CHARACTER_KIND
from lore.modules.characters.links import LINK_TYPES
from lore.modules.characters.router import router
from lore.modules.characters.service import Characters


def _static_data(
    context: VaultContext, policy: VisibilityPolicy, moments: Mapping[str, Sequence[int]]
) -> dict[str, Any]:
    """A static export computes family trees in the browser (``static-family.ts``)."""
    return {"family": Characters(context, policy).static_data(moments)}


MODULE = ModuleSpec(
    id="characters",
    name="Characters",
    description="People with family, social and custom relationships, taking part in events.",
    kinds=(CHARACTER_KIND,),
    link_types=LINK_TYPES,
    routers=(router,),
    consistency_rules=CONSISTENCY_RULES,
    static_reads=(
        StaticRead("{id}/relationships", kind="character", as_of=True),
        StaticRead("{id}/life", kind="character", timeline=True),
    ),
    static_data=_static_data,
)
