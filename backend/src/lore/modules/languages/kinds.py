"""The ``language`` and ``writing_system`` kinds and their fields."""

from lore.core.registry import FieldDef, FieldOption, KindCapabilities, KindDef

LANGUAGE = "language"
WRITING_SYSTEM = "writing_system"


def _options(*pairs: tuple[str, str]) -> tuple[FieldOption, ...]:
    return tuple(FieldOption(key, label) for key, label in pairs)


CAPABILITIES = KindCapabilities(has_body=True, can_be_multiversal=True, has_existence=True)

LANGUAGE_KIND = KindDef(
    LANGUAGE,
    "Language",
    "Languages",
    icon="languages",
    color="#0ea5e9",
    description="A spoken, written or signed language; its dialects are its children.",
    allowed_parents=(LANGUAGE, "misc"),
    fields=(
        FieldDef(
            "modality",
            "Modality",
            "multi_enum",
            options=_options(
                ("spoken", "Spoken"),
                ("written", "Written"),
                ("signed", "Signed"),
                ("telepathic", "Telepathic"),
                ("other", "Other"),
            ),
            sort=0,
        ),
        FieldDef(
            "status",
            "Status",
            "enum",
            temporal=True,
            options=_options(
                ("living", "Living"),
                ("endangered", "Endangered"),
                ("extinct", "Extinct"),
                ("constructed", "Constructed"),
                ("liturgical", "Liturgical"),
                ("other", "Other"),
            ),
            sort=1,
        ),
        FieldDef(
            "word_order",
            "Word order",
            "enum",
            options=_options(
                *((order, order) for order in ("SOV", "SVO", "VSO", "VOS", "OVS", "OSV")),
                ("free", "Free"),
                ("other", "Other"),
            ),
            sort=2,
        ),
        FieldDef(
            "alphabet_order",
            "Alphabet order",
            "long_text",
            help="Space-separated collation order (“a b c ch d …”) for sorting the lexicon.",
            sort=3,
        ),
        FieldDef("phonology", "Phonology", "rich_text", sort=4),
        FieldDef("grammar", "Grammar", "rich_text", sort=5),
        FieldDef("code", "Code", "text", help="A short code (“hv”).", sort=6),
    ),
    capabilities=CAPABILITIES,
)

WRITING_SYSTEM_KIND = KindDef(
    WRITING_SYSTEM,
    "Writing system",
    "Writing systems",
    icon="type",
    color="#0284c7",
    description="A script: an alphabet, abjad, syllabary…",
    allowed_parents=("misc",),
    fields=(
        FieldDef(
            "script_type",
            "Script type",
            "enum",
            options=_options(
                ("alphabet", "Alphabet"),
                ("abjad", "Abjad"),
                ("abugida", "Abugida"),
                ("syllabary", "Syllabary"),
                ("logographic", "Logographic"),
                ("featural", "Featural"),
                ("other", "Other"),
            ),
            sort=0,
        ),
        FieldDef(
            "direction",
            "Direction",
            "enum",
            options=_options(
                ("ltr", "Left to right"),
                ("rtl", "Right to left"),
                ("ttb", "Top to bottom"),
                ("btt", "Bottom to top"),
                ("boustrophedon", "Boustrophedon"),
            ),
            sort=1,
        ),
        FieldDef("glyph_count", "Glyphs", "integer", sort=2),
    ),
    capabilities=CAPABILITIES,
)
