"""The ``species`` kind and its fields."""

from lore.core.registry import FieldDef, FieldOption, KindCapabilities, KindDef

SPECIES = "species"

SPECIES_KIND = KindDef(
    SPECIES,
    "Species",
    "Species",
    icon="dna",
    color="#22c55e",
    description="A people, creature or organism; subspecies and breeds are its children.",
    allowed_parents=(SPECIES, "misc"),
    fields=(
        FieldDef("classification", "Classification", "text", sort=0),
        FieldDef(
            "sapience",
            "Sapience",
            "enum",
            options=tuple(
                FieldOption(key, label)
                for key, label in (
                    ("non_sapient", "Non-sapient"),
                    ("semi_sapient", "Semi-sapient"),
                    ("sapient", "Sapient"),
                    ("unknown", "Unknown"),
                )
            ),
            sort=1,
        ),
        FieldDef("typical_lifespan", "Typical lifespan", "duration", sort=2),
        FieldDef("maturity_age", "Age of maturity", "duration", sort=3),
        FieldDef("average_height", "Average height", "measurement", sort=4),
        FieldDef("average_mass", "Average mass", "measurement", sort=5),
        FieldDef("diet", "Diet", "text", sort=6),
        FieldDef("population", "Population", "integer", temporal=True, sort=7),
    ),
    capabilities=KindCapabilities(has_body=True, can_be_multiversal=True, has_existence=True),
)
