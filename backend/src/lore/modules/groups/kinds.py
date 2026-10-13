"""The ``group`` kind and its fields."""

from lore.core.registry import FieldDef, FieldOption, KindCapabilities, KindDef

GROUP = "group"

GROUP_TYPES = (
    ("government", "Government"),
    ("military", "Military"),
    ("religion", "Religion"),
    ("guild", "Guild"),
    ("company", "Company"),
    ("criminal", "Criminal"),
    ("secret_society", "Secret society"),
    ("noble_house", "Noble house"),
    ("tribe", "Tribe"),
    ("academic", "Academic"),
    ("political_party", "Political party"),
    ("other", "Other"),
)

GROUP_KIND = KindDef(
    GROUP,
    "Group",
    "Groups",
    icon="users",
    color="#ef4444",
    description="An organization: a government, army, guild, house, secret society…",
    allowed_parents=(GROUP, "misc"),
    fields=(
        FieldDef(
            "group_type",
            "Type",
            "enum",
            options=tuple(FieldOption(key, label) for key, label in GROUP_TYPES),
            sort=0,
        ),
        FieldDef("motto", "Motto", "text", temporal=True, sort=1),
        FieldDef("ideology", "Ideology", "long_text", sort=2),
        FieldDef("size", "Size", "integer", temporal=True, sort=3),
        FieldDef(
            "headquarters_note",
            "Headquarters",
            "text",
            temporal=True,
            sort=4,
            help="A note; link a location with “resides in” for a linked headquarters.",
        ),
    ),
    capabilities=KindCapabilities(has_body=True, can_be_multiversal=True, has_existence=True),
)
