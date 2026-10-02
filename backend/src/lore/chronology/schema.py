"""Chronology schemas v1: the structural source of truth for every chronology document.

Pydantic models for rationals, time points and anchors (``time-model.md`` §2.4, §5), durations,
end specs, calendar definitions (``chronology-engine.md`` §3), recurrence rules
(``recurrence.md`` §2) and correspondences (``time-model.md`` §12.1). They are exported as JSON
Schemas into ``spec/chronology/schema/`` (``lore chronology export-schemas``), and the TypeScript
types in ``packages/chronology/src/schema.gen.ts`` are generated from those (``make gen``).

The models check **structure** only: shapes, id/number patterns and size limits. Semantic rules
(references between ids, lengths, ordering, …) belong to compilation (``chronology-engine.md``
§11) and report stable error codes there.

In-world integers are canonical decimal **strings** here (moments, counts, offsets, years).
Engine functions convert them with :func:`int_of`; see ``time-model.md`` §2.2.
"""

from math import gcd
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = 1
"""Current version of calendar definitions and recurrence rules (``data-model.md`` §10)."""

MAX_DIGITS = 1000
"""Moments, durations, counts and offsets have at most 1000 digits (``time-model.md`` §2.2)."""

# --- scalar string types -------------------------------------------------------------------------

MOMENT_PATTERN = r"^(0|[1-9][0-9]*)$"
SIGNED_PATTERN = r"^(0|-?[1-9][0-9]*)$"
POSITIVE_PATTERN = r"^[1-9][0-9]*$"
LEVEL_ID_PATTERN = r"^[a-z][a-z0-9_]*$"
SLOT_ID_PATTERN = r"^[a-z][a-z0-9_-]*$"
FIELD_VALUE_PATTERN = r"^(0|-?[1-9][0-9]*|[a-z][a-z0-9_-]*)$"
OCCURRENCE_KEY_PATTERN = r"^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$"
RECORD_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
RECORD_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$"
SLOT_NAME_PATTERN = r"^[a-z][a-z0-9_]*(:[A-Za-z0-9_.-]+)?$"

MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 200

MomentStr = Annotated[str, StringConstraints(pattern=MOMENT_PATTERN, max_length=MAX_DIGITS)]
"""A moment: a non-negative integer, canonical decimal string."""

SignedIntStr = Annotated[str, StringConstraints(pattern=SIGNED_PATTERN, max_length=MAX_DIGITS + 1)]
"""A signed integer (offsets, years), canonical decimal string (no ``-0``)."""

PositiveIntStr = Annotated[str, StringConstraints(pattern=POSITIVE_PATTERN, max_length=MAX_DIGITS)]
"""A positive integer (counts, intervals, moduli, denominators), canonical decimal string."""

NonNegativeIntStr = MomentStr
"""A non-negative integer that is not a moment (amounts, residues)."""

LevelId = Annotated[str, StringConstraints(pattern=LEVEL_ID_PATTERN, max_length=MAX_ID_LENGTH)]
"""Id of a calendar level (``chronology-engine.md`` §3.2), template, era or cycle."""

SlotId = Annotated[str, StringConstraints(pattern=SLOT_ID_PATTERN, max_length=MAX_ID_LENGTH)]
"""Stable id of a named template child (a slot id, ``time-model.md`` §5.1) or a regime."""

FieldValue = Annotated[
    str, StringConstraints(pattern=FIELD_VALUE_PATTERN, max_length=MAX_DIGITS + 1)
]
"""A calendar field value: a regular number (signed integer) or a slot id."""

RecordId = Annotated[str, StringConstraints(pattern=RECORD_ID_PATTERN, max_length=MAX_ID_LENGTH)]
"""Id of a stored record (UUIDv7 strings; also the virtual ``absolute`` calendar)."""

Name = Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME_LENGTH)]

DateFields = Annotated[dict[LevelId, FieldValue], Field(min_length=1, max_length=20)]
"""Calendar fields by level id, from the top level down to some precision."""

Precision = LevelId
"""A level id of the relevant calendar, or ``base`` (exact)."""


def _exact_int(value: Any) -> Any:
    """Reject ``True``/``1.0`` where a JSON integer literal is expected."""
    if type(value) is not int:
        msg = "must be an integer"
        raise ValueError(msg)
    return value


SchemaVersion1 = Annotated[Literal[1], BeforeValidator(_exact_int)]


def int_of(value: str) -> int:
    """Convert a validated integer string from these models to ``int``."""
    return int(value)


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        use_attribute_docstrings=True,
    )


# --- rationals -----------------------------------------------------------------------------------


class Rational(_Model):
    """An exact rational ``num/den``, always normalized: gcd 1 and ``den > 0`` (time-model §2.4)."""

    num: SignedIntStr
    den: PositiveIntStr

    @model_validator(mode="after")
    def _normalized(self) -> Self:
        if gcd(int(self.num), int(self.den)) != 1:
            msg = "rational must be normalized (gcd(num, den) = 1)"
            raise ValueError(msg)
        return self

    def as_pair(self) -> tuple[int, int]:
        return int(self.num), int(self.den)


# --- durations -----------------------------------------------------------------------------------


class BaseDuration(_Model):
    """An exact, signed number of base units."""

    kind: Literal["base"]
    units: SignedIntStr


class CalendarDuration(_Model):
    """Amounts of calendar units, applied by calendar arithmetic (chronology-engine §9)."""

    kind: Literal["calendar"]
    calendar_id: RecordId
    amounts: Annotated[dict[LevelId, NonNegativeIntStr], Field(min_length=1, max_length=20)]
    sign: Annotated[Literal[1, -1], BeforeValidator(_exact_int)]


type Duration = Annotated[BaseDuration | CalendarDuration, Field(discriminator="kind")]


# --- anchors and time points ---------------------------------------------------------------------


class AbsoluteAnchor(_Model):
    """A moment given directly."""

    kind: Literal["absolute"]
    t: MomentStr


class CalendarAnchor(_Model):
    """A typed date in a calendar; resolves to the start of the unit at the precision."""

    kind: Literal["calendar"]
    calendar_id: RecordId
    fields: DateFields
    era: LevelId | None = None
    regime: SlotId | None = None


class SlotRef(_Model):
    """A referenceable time slot of a record (time-model §6)."""

    type: Annotated[str, StringConstraints(pattern=RECORD_TYPE_PATTERN, max_length=MAX_ID_LENGTH)]
    id: RecordId
    slot: Annotated[str, StringConstraints(pattern=SLOT_NAME_PATTERN, max_length=MAX_NAME_LENGTH)]
    occurrence: (
        Annotated[str, StringConstraints(pattern=OCCURRENCE_KEY_PATTERN, max_length=MAX_DIGITS + 1)]
        | None
    ) = None


class RelativeAnchor(_Model):
    """A slot of another record plus an offset (which may be negative or zero)."""

    kind: Literal["relative"]
    ref: SlotRef
    offset: Duration


class LocalAnchor(_Model):
    """A date in the calendar being defined (astronomical year). Valid only inside definitions."""

    kind: Literal["local"]
    fields: DateFields
    regime: SlotId | None = None


type Anchor = Annotated[
    AbsoluteAnchor | CalendarAnchor | RelativeAnchor, Field(discriminator="kind")
]

type DefinitionAnchor = Annotated[
    AbsoluteAnchor | CalendarAnchor | RelativeAnchor | LocalAnchor, Field(discriminator="kind")
]


def _reject_range(data: Any) -> Any:
    if isinstance(data, dict) and "range" in data:
        msg = "'range' is reserved for explicit uncertainty ranges (post-MVP) and not allowed in v1"
        raise ValueError(msg)
    return data


class TimePoint(_Model):
    """An anchor plus precision and the circa flag (time-model §5.1).

    The member ``range`` is reserved for explicit uncertainty ranges and rejected in v1.
    """

    anchor: Anchor
    precision: Precision
    approximate: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _no_range(cls, data: Any) -> Any:
        return _reject_range(data)


class DefinitionTimePoint(_Model):
    """A time point inside a calendar definition: may also use a ``local`` anchor (§3.10)."""

    anchor: DefinitionAnchor
    precision: Precision
    approximate: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _no_range(cls, data: Any) -> Any:
        return _reject_range(data)


# --- end specs -----------------------------------------------------------------------------------


class TimePointEnd(_Model):
    kind: Literal["time_point"]
    time_point: TimePoint


class DurationEnd(_Model):
    kind: Literal["duration"]
    duration: Duration


class InstantEnd(_Model):
    kind: Literal["instant"]


class EndOfTimeEnd(_Model):
    kind: Literal["end_of_time"]


class UnknownEnd(_Model):
    kind: Literal["unknown"]


type EndSpec = Annotated[
    TimePointEnd | DurationEnd | InstantEnd | EndOfTimeEnd | UnknownEnd,
    Field(discriminator="kind"),
]
"""How an event's end is given (time-model §5.5)."""


# --- calendar definition: levels and templates ---------------------------------------------------


class Level(_Model):
    """One calendar level, fine → coarse (chronology-engine §3.2)."""

    id: LevelId
    label: Name
    plural: Name
    abbr: Name | None = None
    numbering_start: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 1
    """Number of the first regular child in its parent; ignored for the top level."""
    default_template: LevelId | None = None


class UniformLayout(_Model):
    count: PositiveIntStr
    template: LevelId | None = None


class UniformTemplate(_Model):
    """``count`` identical children (base units for level 0)."""

    level: LevelId
    uniform: UniformLayout


class NamedChild(_Model):
    """A named slot of a sequence template."""

    id: SlotId
    template: LevelId
    name: Name
    abbr: Name | None = None
    intercalary: StrictBool = False
    cycle_excluded: Annotated[list[LevelId], Field(max_length=100)] = []


class RunLayout(_Model):
    count: PositiveIntStr
    template: LevelId | None = None


class RunChild(_Model):
    """``count`` unnamed, numbered children."""

    run: RunLayout


type SequenceChild = NamedChild | RunChild


class SequenceTemplate(_Model):
    """Explicit children (chronology-engine §3.4)."""

    level: LevelId
    sequence: Annotated[list[SequenceChild], Field(min_length=1, max_length=10_000)]


type Template = UniformTemplate | SequenceTemplate


# --- calendar definition: top pattern ------------------------------------------------------------


class ModPredicate(_Model):
    """``Y mod mod == eq`` (floor mod)."""

    mod: PositiveIntStr
    eq: NonNegativeIntStr


class AllPredicate(_Model):
    all: Annotated[list[Predicate], Field(min_length=1)]


class AnyPredicate(_Model):
    any: Annotated[list[Predicate], Field(min_length=1)]


class NotPredicate(_Model):
    not_: Predicate = Field(alias="not")


type Predicate = ModPredicate | AllPredicate | AnyPredicate | NotPredicate
"""A periodic condition on the year number ``Y`` (chronology-engine §3.5)."""


class FixedPattern(_Model):
    kind: Literal["fixed"]
    template: LevelId


class CyclePattern(_Model):
    kind: Literal["cycle"]
    templates: Annotated[list[LevelId], Field(min_length=1, max_length=1_000_000)]
    start: SignedIntStr


class YearRule(_Model):
    when: Predicate
    template: LevelId


class RulesPattern(_Model):
    kind: Literal["rules"]
    default: LevelId
    rules: Annotated[list[YearRule], Field(max_length=1000)]


type YearPattern = Annotated[
    FixedPattern | CyclePattern | RulesPattern, Field(discriminator="kind")
]


class YearException(_Model):
    year: SignedIntStr
    template: LevelId


class TopPattern(_Model):
    """Which template each top-level unit (year) uses."""

    pattern: YearPattern
    exceptions: Annotated[list[YearException], Field(max_length=100_000)] = []


# --- calendar definition: regimes, cycles, eras, overlays ----------------------------------------


class Alignment(_Model):
    """The start of the unit denoted by ``fields`` (astronomical year) happens at ``at``."""

    fields: DateFields
    at: TimePoint


class ResetMode(_Model):
    reset: LevelId


class CycleAnchor(_Model):
    fields: DateFields | None = None
    index: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 0


class Cycle(_Model):
    """A parallel cycle such as a week (chronology-engine §3.7)."""

    id: LevelId
    level: LevelId
    length: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    names: Annotated[list[Name], Field(max_length=1_000_000)] | None = None
    abbrs: Annotated[list[Name], Field(max_length=1_000_000)] | None = None
    number_start: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 1
    mode: Literal["continuous"] | ResetMode = "continuous"
    anchor: CycleAnchor | None = None
    continue_from_previous_regime: StrictBool = False


class Regime(_Model):
    """A complete calendar structure with its own epoch (chronology-engine §3.3)."""

    id: SlotId
    name: Name
    starts_at: DefinitionTimePoint | None = None
    templates: Annotated[dict[LevelId, Template], Field(min_length=1, max_length=500)]
    top: TopPattern
    alignment: Alignment
    cycles: Annotated[list[Cycle], Field(max_length=100)] = []


class EraNumbering(_Model):
    direction: Literal["forward", "backward"]
    first: SignedIntStr


class Era(_Model):
    """A partition of time with its own year numbering (chronology-engine §3.8)."""

    id: LevelId
    name: Name
    abbr: Name
    start: DefinitionTimePoint | None = None
    numbering: EraNumbering
    abbr_position: Literal["prefix", "suffix"] = "suffix"


class Phase(_Model):
    name: Name
    from_: Rational = Field(alias="from")


class Overlay(_Model):
    """An astronomical cycle that never affects date structure (chronology-engine §3.9)."""

    id: LevelId
    name: Name
    period: Rational
    epoch: DefinitionTimePoint
    phases: Annotated[list[Phase], Field(min_length=1, max_length=1000)]


FormatPattern = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Formats(BaseModel):
    """Format patterns by precision level id, plus ``intercalary`` overrides (§3.11)."""

    model_config = ConfigDict(frozen=True, extra="allow", use_attribute_docstrings=True)
    __pydantic_extra__: dict[LevelId, FormatPattern] = Field(init=False)

    intercalary: dict[LevelId, FormatPattern] = {}


class DisplayOptions(_Model):
    circa: Annotated[str, StringConstraints(max_length=50)] = "c. "
    digit_group: Annotated[str, StringConstraints(max_length=5)] = ","
    scientific_threshold: Annotated[StrictInt, Field(ge=1, le=MAX_DIGITS + 1)] = 16
    significant_digits: Annotated[StrictInt, Field(ge=1, le=50)] = 4
    range_separator: Annotated[str, StringConstraints(max_length=50)] = " \u2013 "  # en dash


class CalendarDefinition(_Model):
    """A calendar definition, schema v1 (chronology-engine §3)."""

    schema_version: SchemaVersion1
    levels: Annotated[list[Level], Field(min_length=1, max_length=20)]
    regimes: Annotated[list[Regime], Field(min_length=1, max_length=100)]
    eras: Annotated[list[Era], Field(max_length=1000)] = []
    overlays: Annotated[list[Overlay], Field(max_length=100)] = []
    formats: Formats | None = None
    display: DisplayOptions | None = None


class BaseUnit(_Model):
    singular: Name
    plural: Name
    abbr: Name


class CompileContext(_Model):
    """Inputs to ``compile`` besides the definition (chronology-engine §4)."""

    base_unit: BaseUnit
    dimension_duration: PositiveIntStr
    resolved: dict[Annotated[str, StringConstraints(pattern=r"^(/[^/]*)*$")], MomentStr] = {}
    """Resolved moments of every non-local time point, keyed by JSON pointer into the definition."""


# --- recurrence rules ----------------------------------------------------------------------------


class LevelFreq(_Model):
    level: LevelId


class CycleFreq(_Model):
    cycle: LevelId


class ModFilter(_Model):
    mod: PositiveIntStr
    eq: NonNegativeIntStr
    of: Literal["number", "ordinal"] = "number"


class InFilter(_Model):
    in_: Annotated[list[FieldValue], Field(min_length=1, max_length=10_000)] = Field(alias="in")


class CycleFilter(_Model):
    cycle: LevelId
    in_: Annotated[list[FieldValue], Field(min_length=1, max_length=10_000)] = Field(alias="in")


class AllFilter(_Model):
    all: Annotated[list[PeriodFilter], Field(min_length=1)]


class AnyFilter(_Model):
    any: Annotated[list[PeriodFilter], Field(min_length=1)]


class NotFilter(_Model):
    not_: PeriodFilter = Field(alias="not")


type PeriodFilter = ModFilter | InFilter | CycleFilter | AllFilter | AnyFilter | NotFilter
"""Which periods qualify (recurrence §2.2)."""


class ValuesSelector(_Model):
    level: LevelId
    values: Annotated[list[FieldValue], Field(min_length=1, max_length=10_000)]


class CycleMatch(_Model):
    id: LevelId
    values: Annotated[list[FieldValue], Field(min_length=1, max_length=10_000)]
    nth: Annotated[list[SignedIntStr], Field(min_length=1, max_length=1000)] | None = None


class CycleSelector(_Model):
    level: LevelId
    cycle: CycleMatch


class AllSelector(_Model):
    level: LevelId
    all: Literal[True]


type LevelSelector = ValuesSelector | CycleSelector | AllSelector


class Selector(_Model):
    """Positions inside a period, from the period's child level downward (recurrence §2.3)."""

    path: Annotated[list[LevelSelector], Field(min_length=1, max_length=20)]


class TimeOfDay(_Model):
    fields: DateFields


class NeverLimit(_Model):
    kind: Literal["never"]


class CountLimit(_Model):
    kind: Literal["count"]
    count: PositiveIntStr


class UntilLimit(_Model):
    kind: Literal["until"]
    until: TimePoint


type Limit = Annotated[NeverLimit | CountLimit | UntilLimit, Field(discriminator="kind")]


class Exclusion(_Model):
    """Skip occurrences starting in ``[from, to)``."""

    from_: TimePoint = Field(alias="from")
    to: TimePoint
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class CalendarRule(_Model):
    """An RRULE-like rule generalized to any calendar (recurrence §2)."""

    schema_version: SchemaVersion1 = 1
    kind: Literal["calendar"]
    calendar_id: RecordId
    freq: LevelFreq | CycleFreq
    interval: PositiveIntStr = "1"
    filters: Annotated[list[PeriodFilter], Field(max_length=100)] = []
    select: Selector | None = None
    missing: Literal["skip", "constrain"] = "skip"
    time: TimeOfDay | None = None
    limit: Limit
    exclusions: Annotated[list[Exclusion], Field(max_length=10_000)] = []


class IntervalRule(_Model):
    """A fixed interval in base units, independent of calendars."""

    schema_version: SchemaVersion1 = 1
    kind: Literal["interval"]
    every: PositiveIntStr
    limit: Limit
    exclusions: Annotated[list[Exclusion], Field(max_length=10_000)] = []


type RecurrenceRule = Annotated[CalendarRule | IntervalRule, Field(discriminator="kind")]


# --- correspondences -----------------------------------------------------------------------------


class SyncPoint(_Model):
    """``a`` in dimension A happens at the same time as ``b`` in dimension B."""

    a: TimePoint
    b: TimePoint


class CorrespondenceDef(_Model):
    """How time in two dimensions corresponds (time-model §12.1)."""

    extrapolation: Literal["none", "rate"] = "none"
    rate_before: Rational | None = None
    rate_after: Rational | None = None
    points: Annotated[list[SyncPoint], Field(min_length=1, max_length=10_000)]


# --- versioning ----------------------------------------------------------------------------------


class SchemaVersionError(ValueError):
    """A document has a schema version this engine cannot upgrade."""


def _upgrade(document: dict[str, Any], *, default: int | None) -> dict[str, Any]:
    version = document.get("schema_version", default)
    if version == SCHEMA_VERSION and type(version) is int:
        return document
    msg = f"unsupported schema_version {version!r} (current: {SCHEMA_VERSION})"
    raise SchemaVersionError(msg)


def upgrade_calendar_definition(document: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a stored calendar definition to the current version (v1 is the first)."""
    return _upgrade(document, default=None)


def upgrade_recurrence_rule(document: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a stored recurrence rule; an absent ``schema_version`` means 1."""
    return _upgrade(document, default=1)
