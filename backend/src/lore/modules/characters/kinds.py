"""The ``character`` kind and its fields."""

from lore.core.registry import FieldDef, KindCapabilities, KindDef

CHARACTER = "character"

CHARACTER_KIND = KindDef(
    CHARACTER,
    "Character",
    "Characters",
    icon="user",
    color="#8b5cf6",
    description="A person in the world: relationships, events, a life.",
    allowed_parents=("misc",),
    fields=(
        FieldDef(
            "full_name",
            "Full name",
            "text",
            temporal=True,
            sort=0,
            help="The legal or formal name; the entity name is the display name.",
        ),
        FieldDef("epithet", "Epithet", "text", temporal=True, sort=1),
        FieldDef("title", "Titles", "text", temporal=True, multiple=True, sort=2),
        FieldDef("gender", "Gender", "text", temporal=True, sort=3),
        FieldDef("occupation", "Occupations", "text", temporal=True, multiple=True, sort=4),
        FieldDef("appearance", "Appearance", "long_text", sort=5),
        FieldDef("personality", "Personality", "long_text", sort=6),
        FieldDef("secret", "Secret", "long_text", default_visibility="private", sort=7),
    ),
    capabilities=KindCapabilities(
        has_body=True, can_be_multiversal=True, has_existence=True, can_have_worldline=True
    ),
)
