"""What core registers: the built-in field types, the system kinds and event, and the core link
types (``data-model.md`` §3.4, §4.2, §6.2). Kind behavior lives with the kind extensions."""

from lore.core.registry.types import FieldTypeDef, KindCapabilities, KindDef, LinkTypeDef

CORE_FIELD_TYPES: tuple[FieldTypeDef, ...] = (
    FieldTypeDef("text", "Text", "Single line of text."),
    FieldTypeDef("long_text", "Long text", "Multi-line plain text."),
    FieldTypeDef("rich_text", "Rich text", "A rich-text document."),
    FieldTypeDef("integer", "Integer", "Arbitrary-precision integer."),
    FieldTypeDef("decimal", "Decimal", "Exact decimal number."),
    FieldTypeDef("boolean", "Yes/no"),
    FieldTypeDef("enum", "Choice", "One of a list of options."),
    FieldTypeDef("multi_enum", "Choices", "Several of a list of options."),
    FieldTypeDef("url", "URL", "An http(s) link."),
    FieldTypeDef("color", "Color", "#rrggbb."),
    FieldTypeDef("duration", "Duration", "A base or calendar duration."),
    FieldTypeDef("time_point", "Time point", "A date or moment; takes part in propagation."),
    FieldTypeDef("measurement", "Measurement", "A decimal value with a free unit."),
)

_SYSTEM = KindCapabilities(
    has_body=True,
    can_be_multiversal=False,
    has_existence=False,
    can_have_worldline=False,
    is_system=True,
)

CORE_KINDS: tuple[KindDef, ...] = (
    KindDef(
        "dimension",
        "Dimension",
        "Dimensions",
        icon="orbit",
        color="#6366f1",
        description="A universe with its own time: base unit, duration, calendars, timelines.",
        capabilities=KindCapabilities(
            has_body=True, can_be_multiversal=True, has_existence=False, is_system=True
        ),
    ),
    KindDef(
        "timeline",
        "Timeline",
        "Timelines",
        icon="git-branch",
        color="#8b5cf6",
        description="The prime timeline of a dimension, or an alternate branch.",
        capabilities=_SYSTEM,
    ),
    KindDef(
        "calendar",
        "Calendar",
        "Calendars",
        icon="calendar",
        color="#0ea5e9",
        description="A lens that turns moments into dates and back.",
        capabilities=_SYSTEM,
    ),
    KindDef(
        "event",
        "Event",
        "Events",
        icon="calendar-clock",
        color="#f59e0b",
        description="Something that happens at a time point, possibly recurring.",
        allowed_parents=("event", "misc"),
        capabilities=KindCapabilities(
            has_body=True, can_be_multiversal=False, has_existence=False, is_time_bound=True
        ),
    ),
)

CORE_LINK_TYPES: tuple[LinkTypeDef, ...] = (
    LinkTypeDef(
        "core.participant",
        "participant",
        inverse_label="participates in",
        description="An entity taking part in an event, with a free-text role.",
        source_kinds=("event",),
        temporal="never",
        # segment_id: the participant's worldline segment (worldlines module, time-model §11.4).
        data_schema={
            "type": "object",
            "properties": {"segment_id": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
    ),
    LinkTypeDef(
        "core.causes",
        "causes",
        inverse_label="caused by",
        description="Cause → effect between events, with an optional description.",
        source_kinds=("event",),
        target_kinds=("event",),
        temporal="never",
        unique="per_pair",  # decided 2026-10-06: edit the existing link instead
        data_schema={
            "type": "object",
            "properties": {"description": {"type": "string", "maxLength": 2000}},
            "additionalProperties": False,
        },
    ),
    LinkTypeDef(
        "core.related",
        "related to",
        inverse_label="related to",
        description="A generic relation between any two entities.",
        symmetric=True,
        temporal="optional",
    ),
)
