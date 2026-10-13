"""The ``misc`` kind and its fields."""

from lore.core.registry import FieldDef, KindCapabilities, KindDef

MISC = KindDef(
    "misc",
    "Misc entry",
    "Misc entries",
    icon="shapes",
    color="#64748b",
    description="Anything that doesn't fit elsewhere; can be the parent of entities of any kind.",
    allowed_parents=("misc",),
    fields=(
        FieldDef(
            "category",
            "Category",
            "text",
            help="Free text (Concept, Technology, Magic…); groups entries in the sidebar.",
        ),
    ),
    capabilities=KindCapabilities(has_body=True, can_be_multiversal=True, has_existence=True),
)
