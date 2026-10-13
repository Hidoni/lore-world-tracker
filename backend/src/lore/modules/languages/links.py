"""The languages module's link types."""

from lore.core.registry import LinkTypeDef
from lore.modules.languages.kinds import LANGUAGE, WRITING_SYSTEM

DESCENDED_FROM = "languages.descended_from"
BORROWED_FROM = "languages.borrowed_from"
USES_SCRIPT = "languages.uses_script"
SPEAKS = "languages.speaks"

LINK_TYPES = (
    LinkTypeDef(
        DESCENDED_FROM,
        "descended from",
        inverse_label="ancestor of",
        description="A language's ancestor (its validity start is the divergence).",
        source_kinds=(LANGUAGE,),
        target_kinds=(LANGUAGE,),
    ),
    LinkTypeDef(
        BORROWED_FROM,
        "borrows from",
        inverse_label="lends to",
        source_kinds=(LANGUAGE,),
        target_kinds=(LANGUAGE,),
        data_schema={
            "type": "object",
            "properties": {"note": {"type": "string", "maxLength": 500}},
            "additionalProperties": False,
        },
    ),
    LinkTypeDef(
        USES_SCRIPT,
        "written in",
        inverse_label="used by",
        source_kinds=(LANGUAGE,),
        target_kinds=(WRITING_SYSTEM,),
    ),
    LinkTypeDef(
        SPEAKS,
        "speaks",
        inverse_label="spoken by",
        description="A character, group, species, place… using a language.",
        target_kinds=(LANGUAGE,),
        data_schema={
            "type": "object",
            "properties": {
                "fluency": {"enum": ["native", "fluent", "conversational", "basic"]},
            },
            "additionalProperties": False,
        },
    ),
)
