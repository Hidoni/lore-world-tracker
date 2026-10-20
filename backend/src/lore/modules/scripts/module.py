"""The scripts module's spec: fields only. A writing system's font is a ``media`` field, so the
media module references it (readers get the file exactly when they see the field), keeps it from
collection and copies it on publish and static export; the frontend loads it with ``@font-face``.
"""

from lore.core.modules import ModuleSpec
from lore.core.registry import FieldContribution, FieldDef, FieldOption

SECTION = "Script font"

FONT = "scripts.font"
FONT_SCALE = "scripts.font_scale"
SAMPLE = "scripts.sample"
HEADWORDS = "scripts.headwords"

WRITING_SYSTEM_FIELDS = (
    FieldDef(
        FONT,
        "Font",
        "media",
        section=SECTION,
        sort=1,
        searchable=False,
        help="A font file (WOFF2, WOFF, TTF or OTF) for text in this script.",
    ),
    FieldDef(
        FONT_SCALE,
        "Font size",
        "integer",
        section=SECTION,
        sort=2,
        help="In percent of the text around it (default 100, from 50 to 400).",
    ),
    FieldDef(
        SAMPLE,
        "Sample",
        "long_text",
        section=SECTION,
        sort=3,
        help="Text shown in the font on the writing system's page.",
    ),
)

LANGUAGE_FIELDS = (
    FieldDef(
        HEADWORDS,
        "Headwords",
        "enum",
        options=(
            FieldOption("script", "In the script's font"),
            FieldOption("plain", "Plain text"),
        ),
        section=SECTION,
        sort=1,
        help="How the lexicon shows headwords. The script's font is the font of the first "
        "writing system the language is written in that has one.",
    ),
)

MODULE = ModuleSpec(
    id="scripts",
    name="Script fonts",
    description="Fonts for writing systems: lexicon headwords and samples in the conlang's own "
    "script.",
    depends_on=("languages", "media"),
    field_contributions=(
        FieldContribution("writing_system", WRITING_SYSTEM_FIELDS),
        FieldContribution("language", LANGUAGE_FIELDS),
    ),
)
