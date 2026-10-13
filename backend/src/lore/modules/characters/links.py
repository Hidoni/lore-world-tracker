"""The characters module's relationship link types, by category."""

from typing import Any, Literal

from lore.core.registry import LinkTypeDef
from lore.modules.characters.kinds import CHARACTER

type Category = Literal["family", "social", "custom"]

PARENT_OF = "characters.parent_of"
SIBLING_OF = "characters.sibling_of"
SPOUSE_OF = "characters.spouse_of"
RELATIONSHIP = "characters.relationship"

PEOPLE = (CHARACTER,)


def _kind_of(*kinds: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"kind": {"enum": list(kinds)}},
        "additionalProperties": False,
    }


def _between(
    key: str, label: str, *, inverse: str | None = None, symmetric: bool = False, **more: Any
) -> LinkTypeDef:
    return LinkTypeDef(
        key,
        label,
        inverse_label=inverse,
        source_kinds=more.pop("source_kinds", PEOPLE),
        target_kinds=more.pop("target_kinds", PEOPLE),
        symmetric=symmetric,
        temporal=more.pop("temporal", "optional"),
        **more,
    )


LINK_TYPES = (
    _between(
        PARENT_OF,
        "parent of",
        inverse="child of",
        data_schema=_kind_of("biological", "adoptive", "step", "foster", "other"),
        description="A parent and their child (adoption may have validity).",
    ),
    _between(
        SIBLING_OF,
        "sibling of",
        symmetric=True,
        temporal="never",
        data_schema=_kind_of("full", "half", "step", "adoptive"),
    ),
    _between(
        SPOUSE_OF,
        "spouse of",
        symmetric=True,
        data_schema=_kind_of("marriage", "partnership", "betrothal"),
    ),
    _between("characters.romance", "romantic partner of", symmetric=True),
    _between("characters.friend_of", "friend of", symmetric=True),
    _between("characters.rival_of", "rival of", symmetric=True),
    _between("characters.enemy_of", "enemy of", symmetric=True),
    _between("characters.mentor_of", "mentor of", inverse="student of"),
    # Groups (M6, #94) add their kind to the targets.
    _between(
        "characters.serves",
        "serves",
        inverse="served by",
        data_schema={
            "type": "object",
            "properties": {"capacity": {"type": "string", "maxLength": 200}},
            "additionalProperties": False,
        },
    ),
    _between(
        RELATIONSHIP,
        "related to",
        description='Any other relationship: its role names it ("godmother of").',
    ),
)

CATEGORIES: dict[str, Category] = {
    PARENT_OF: "family",
    SIBLING_OF: "family",
    SPOUSE_OF: "family",
    "characters.romance": "social",
    "characters.friend_of": "social",
    "characters.rival_of": "social",
    "characters.enemy_of": "social",
    "characters.mentor_of": "social",
    "characters.serves": "social",
    RELATIONSHIP: "custom",
}
