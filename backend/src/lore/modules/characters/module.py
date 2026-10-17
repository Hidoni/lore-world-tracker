"""The characters module's spec."""

from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.characters.consistency import CONSISTENCY_RULES
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
    consistency_rules=CONSISTENCY_RULES,
    static_reads=(
        StaticRead("{id}/relationships", kind="character", as_of=True),
        StaticRead("{id}/life", kind="character", timeline=True),
        # The family tree page (3 generations) and panel (2), as the app asks for them.
        StaticRead(
            "{id}/family-tree",
            kind="character",
            variants=tuple(
                (("up", n), ("down", n), ("include_spouses", "true"), ("include_siblings", "true"))
                for n in ("2", "3")
            ),
            timeline=True,
            as_of=True,
        ),
    ),
)
