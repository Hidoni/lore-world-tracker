"""The groups module's link types."""

from typing import Any

from lore.core.registry import LinkTypeDef
from lore.modules.groups.kinds import GROUP

MEMBER_OF = "groups.member_of"
LED_BY = "groups.led_by"
PART_OF = "groups.part_of"
ALLIED_WITH = "groups.allied_with"
AT_WAR_WITH = "groups.at_war_with"
VASSAL_OF = "groups.vassal_of"
CONTROLS = "groups.controls"

GROUPS = (GROUP,)


def _object(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False}


TEXT = {"type": "string", "maxLength": 200}

LINK_TYPES = (
    LinkTypeDef(
        MEMBER_OF,
        "member of",
        inverse_label="members",
        description="A character, group or other entity belonging to a group.",
        target_kinds=GROUPS,
        data_schema=_object(rank=TEXT, title=TEXT, is_leader={"type": "boolean"}),
    ),
    LinkTypeDef(
        LED_BY,
        "led by",
        inverse_label="leads",
        description="A leader; succession is the sequence of validity periods.",
        source_kinds=GROUPS,
        data_schema=_object(title=TEXT),
    ),
    LinkTypeDef(
        PART_OF,
        "part of",
        inverse_label="has part",
        description="Structure that changes over time (besides the parent group).",
        source_kinds=GROUPS,
        target_kinds=GROUPS,
    ),
    LinkTypeDef(
        ALLIED_WITH, "allied with", source_kinds=GROUPS, target_kinds=GROUPS, symmetric=True
    ),
    LinkTypeDef(
        AT_WAR_WITH,
        "at war with",
        source_kinds=GROUPS,
        target_kinds=GROUPS,
        symmetric=True,
        data_schema=_object(war_event_id={"type": "string", "maxLength": 100}),
    ),
    LinkTypeDef(
        VASSAL_OF,
        "vassal of",
        inverse_label="overlord of",
        source_kinds=GROUPS,
        target_kinds=GROUPS,
    ),
    # Offered while the locations module is enabled (its kind is the target).
    LinkTypeDef(
        CONTROLS,
        "controls",
        inverse_label="controlled by",
        description="Territory: locations the group controls.",
        source_kinds=GROUPS,
        target_kinds=("location",),
    ),
)
