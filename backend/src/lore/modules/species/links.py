"""The species module's link types."""

from lore.core.registry import LinkTypeDef
from lore.modules.species.kinds import SPECIES

IS_A = "species.is_a"
DESCENDED_FROM = "species.descended_from"
NATIVE_TO = "species.native_to"

LINK_TYPES = (
    LinkTypeDef(
        IS_A,
        "is a",
        inverse_label="members",
        description="A character or other entity of a species (validity: transformations).",
        target_kinds=(SPECIES,),
    ),
    LinkTypeDef(
        DESCENDED_FROM,
        "descended from",
        inverse_label="ancestor of",
        description="An ancestor species (its validity start is the divergence).",
        source_kinds=(SPECIES,),
        target_kinds=(SPECIES,),
    ),
    # Offered while the locations module is enabled (its kind is the target).
    LinkTypeDef(
        NATIVE_TO,
        "native to",
        inverse_label="native species",
        source_kinds=(SPECIES,),
        target_kinds=("location",),
    ),
)
