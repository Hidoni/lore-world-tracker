"""API models of the time routes (``docs/architecture/api.md`` §2, Time)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lore.chronology.schema import BaseUnit, EndSpec, TimePoint
from lore.chronology.schema import MomentStr as ChronologyMomentStr
from lore.core.db.base import Visibility
from lore.core.entities.schemas import ID_PATTERN, EntityId, EntityName, EntityOut
from lore.core.time.calendars import CalendarSource
from lore.core.time.status import TimeStatus
from lore.core.types import Affected, BigIntStr, MomentStr


class TimelineNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    is_prime: bool
    parent_timeline_id: str | None
    branch_point: dict[str, Any] | None = Field(description="The branch point time point.")
    branch_t: MomentStr | None = Field(description="The resolved branch moment.")
    time_status: str | None
    trashed: bool
    children: list[TimelineNode] = Field(description="Branches, by name.")


class TimelineTree(BaseModel):
    dimension_id: str
    items: list[TimelineNode] = Field(
        description="The root timelines: the prime, unless the request may not see it."
    )


class PresetOut(BaseModel):
    id: str
    name: str
    description: str
    origin: str = Field(description="What the preset's origin moment is.")
    duration_seconds: str = Field(
        description="The dimension must last at least this long after the origin (seconds)."
    )
    definition: dict[str, Any] = Field(description="The definition, written in seconds.")


class PresetList(BaseModel):
    items: list[PresetOut]


class TimeSpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_unit: BaseUnit
    duration: ChronologyMomentStr


class CalendarPreviewIn(BaseModel):
    """Exactly one of ``dimension_id`` (an existing dimension) and ``time_spec`` (one about to be
    created, e.g. in the wizard)."""

    model_config = ConfigDict(extra="forbid")

    dimension_id: EntityId | None = None
    time_spec: TimeSpecIn | None = None
    calendar_id: EntityId | None = Field(
        default=None, description="The calendar being edited (detects self-references)."
    )
    source: CalendarSource


class WizardCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: EntityName
    summary: str = ""
    source: CalendarSource


class DimensionWizardIn(BaseModel):
    """A dimension with its time spec, its prime timeline and its first calendar, in one go."""

    model_config = ConfigDict(extra="forbid")

    name: EntityName
    summary: str = ""
    visibility: Visibility | None = None
    ext: dict[str, Any] = Field(description="The time spec: `{base_unit, duration, present?}`.")
    calendar: WizardCalendar


class DimensionCreated(BaseModel):
    dimension: EntityOut
    prime_timeline: EntityOut
    calendar: EntityOut


# --- /time/resolve and /time/convert ------------------------------------------------------------

MAX_BATCH = 500
CalendarRef = Annotated[str, StringConstraints(pattern=f"^(absolute|{ID_PATTERN.strip('^$')})$")]


class TimeProblem(BaseModel):
    code: str = Field(
        description="`invalid_date`, `reform_gap`, `reform_ambiguous`, `out_of_bounds`, "
        "`unresolved_ref`, `calendar_error`, `time_cycle`, `unknown_slot`, "
        "`slot_not_referenceable` or `not_supported`."
    )
    message: str
    path: str = Field(description="Where in the item (dotted, e.g. `anchor.fields.month`).")


class Extent(BaseModel):
    lo: BigIntStr
    hi: BigIntStr = Field(description="Exclusive.")


class ResolvedPoint(BaseModel):
    t: BigIntStr | None = Field(
        description="The moment (outside `[0, D]` when `out_of_bounds`); null if unresolvable."
    )
    status: TimeStatus | None = Field(
        description="The resolution status; null for specs that can never resolve."
    )
    extent: Extent | None = Field(description="The uncertainty extent `[lo, hi)`.")
    precision: str | None
    approximate: bool
    display: str | None = Field(description="Formatted in the response's calendar.")
    error: TimeProblem | None


class ResolveRequestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_point: TimePoint
    end: EndSpec | None = Field(default=None, description="An end spec resolved from the point.")


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: EntityId
    timeline_id: EntityId | None = Field(
        default=None, description="The timeline relative anchors resolve in (the prime)."
    )
    calendar_id: CalendarRef | None = Field(
        default=None, description="Display calendar (default: the dimension's default)."
    )
    items: Annotated[list[ResolveRequestItem], Field(max_length=MAX_BATCH)]


class ResolveItem(BaseModel):
    start: ResolvedPoint
    end: ResolvedPoint | None


class ResolveOut(BaseModel):
    calendar_id: str = Field(description="The calendar the displays use.")
    items: list[ResolveItem]


class ConvertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: EntityId
    moments: Annotated[list[MomentStr], Field(max_length=MAX_BATCH)]
    calendars: Annotated[list[CalendarRef], Field(min_length=1, max_length=20)]
    precision: str | None = Field(
        default=None,
        description="Display precision (a level id or `base`; default: the finest level).",
    )


class ConvertResult(BaseModel):
    calendar_id: str
    fields: dict[str, Any] | None = Field(
        default=None, description="`to_fields` (`chronology-engine.md` §5.6); null for absolute."
    )
    display: str | None = None
    error: TimeProblem | None = None


class ConvertItem(BaseModel):
    t: MomentStr
    results: list[ConvertResult] = Field(description="One per requested calendar, in order.")


class ConvertOut(BaseModel):
    items: list[ConvertItem]


class EventDisplay(BaseModel):
    calendar_id: str = Field(
        description="The calendar of the displays: the dimension's default, or `absolute`."
    )
    start: str | None
    end: str | None = Field(description='`"?"` for an unknown end.')


class EventTreeNode(BaseModel):
    id: str
    name: str
    visibility: Visibility
    parent_id: str | None
    start_t: MomentStr | None
    end_t: MomentStr | None
    time_status: str | None
    importance: int
    category: str | None
    display: EventDisplay
    has_children: bool = Field(description="Whether the tree shows sub-events under it.")


class EventTreePage(BaseModel):
    items: list[EventTreeNode]
    next_cursor: str | None


class WindowItemOut(BaseModel):
    entity_id: str
    row_id: str
    name: str
    visibility: Visibility
    parent_id: str | None = Field(description="Null when the request can't see the parent.")
    has_children: bool = Field(description="Whether the timeline shows sub-events under it.")
    start_t: MomentStr | None
    end_t: MomentStr | None
    start_precision: str = Field(description="The start's precision (a calendar level or `base`).")
    start_approximate: bool
    end_kind: str = Field(
        description="`time_point`, `duration`, `instant`, `end_of_time` or `unknown` (open end)."
    )
    end_precision: str | None = Field(
        description="A `time_point` end's precision; other ends derive theirs from the start."
    )
    end_approximate: bool
    importance: int
    category: str | None
    time_status: str | None
    occurrence_key: str | None = Field(
        description="For an occurrence of a recurring series (the item is the series' event): "
        "its key (`k`, or `k.j`), also for materialized occurrences; null for other events."
    )
    series_id: str | None = Field(
        description="The series of an occurrence (computed: `entity_id`; materialized: its "
        "series, null when the request can't see it)."
    )
    occurrence_state: str | None = Field(
        description="A materialized occurrence's `referenced`, `modified` or `cancelled`."
    )


class SeriesBandOut(BaseModel):
    entity_id: str
    row_id: str
    name: str
    visibility: Visibility
    importance: int
    category: str | None
    from_t: MomentStr = Field(serialization_alias="from")
    to_t: MomentStr = Field(serialization_alias="to")
    estimated_count: MomentStr = Field(
        description="The occurrences overlapping the window (exact when the rule can be counted)."
    )


class WindowBucket(BaseModel):
    from_t: MomentStr = Field(serialization_alias="from")
    to_t: MomentStr = Field(serialization_alias="to")
    starts: int = Field(
        description="Culled events starting in the bucket (the first: or before the window); "
        "they add up to `culled`."
    )
    active: int = Field(description="Culled events covering any part of the bucket.")


class TimelineWindow(BaseModel):
    items: list[WindowItemOut] = Field(description="The kept events, by start (then longer first).")
    buckets: list[WindowBucket] = Field(
        description="Culled events per bucket of the window (buckets with any)."
    )
    series_bands: list[SeriesBandOut] = Field(
        description="Recurring series with too many occurrences in the window to list, over the "
        "part of the window they cover."
    )
    total: int = Field(
        description="Events and occurrences overlapping the window after the filters (bands "
        "excluded)."
    )
    culled: int = Field(
        description="Events and occurrences left out of `items` (the sum of `buckets[].starts`)."
    )


class OccurrenceOut(BaseModel):
    key: str = Field(description="`k`, or `k.j` for rules with several positions per period.")
    start_t: MomentStr
    end_t: MomentStr
    number: int | None = Field(
        description="The occurrence number (1-based, among the occurrences that happen)."
    )
    entity_id: str | None = Field(description="The materialized occurrence, if any.")
    state: str | None = Field(
        description="`referenced`, `modified` or `cancelled` (materialized occurrences)."
    )


class OccurrencePage(BaseModel):
    items: list[OccurrenceOut] = Field(description="By start; empty when `truncated`.")
    truncated: bool = Field(description="More than `limit` occurrences overlap the window.")
    estimated_count: MomentStr | None = Field(
        description="When truncated: how many overlap (exact when the rule can be counted)."
    )


# --- proposals (time-model.md §7.4-§7.5, recurrence.md §8) ---------------------------------------

type CalendarStrategy = Literal["keep_date", "pin_moment", "constrain"]
type RecurrenceStrategy = Literal["keep_key", "rekey", "detach", "trash"]


class CalendarProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any] = Field(description="The new calendar definition.")


class ProposalProblem(BaseModel):
    code: str
    message: str


class CalendarProposalItem(BaseModel):
    """A slot whose moment or status the edit changes, or that it breaks (slot ``recurrence``: a
    series rule that no longer evaluates; slot ``definition``: a calendar that no longer
    compiles)."""

    key: str = Field(description="`<record type>/<id>/<slot>`: the key of `strategies`.")
    record_type: str
    id: str
    slot: str
    entity_id: str | None = Field(description="The entity the record belongs to.")
    name: str | None = Field(description="That entity's name.")
    old_t: MomentStr | None = Field(description="The stored moment now.")
    old_status: TimeStatus | None
    new_t: BigIntStr | None = Field(
        description="The moment with the new definition (`keep_date`); may lie outside "
        "`[0, D]` (`out_of_bounds`); null when it doesn't resolve."
    )
    status: TimeStatus | None = Field(description="The status with the new definition.")
    problem: ProposalProblem | None = Field(
        description="Why the record breaks (hard rule), if it does."
    )
    old_display: str | None = Field(description="`old_t` in the display calendar, before.")
    new_display: str | None = Field(description="`new_t` in the display calendar, after.")
    constrained_t: MomentStr | None = Field(
        description="`constrain`: the moment of the nearest valid date (invalid dates only)."
    )
    constrained_display: str | None
    strategies: list[CalendarStrategy] = Field(description="The strategies the record takes.")


class SeriesBoundsChange(BaseModel):
    entity_id: str
    name: str | None
    old_start_t: MomentStr | None
    old_end_t: MomentStr | None
    new_start_t: MomentStr | None
    new_end_t: MomentStr | None


class CalendarProposalSummary(BaseModel):
    affected: int = Field(description="Nodes the change reached (slots, calendars, dimensions).")
    changed: int = Field(description="Items (records that change or break).")
    problems: int = Field(description="Items with a problem.")
    by_problem: dict[str, int] = Field(description="Items per problem code.")
    series: int = Field(description="Series whose bounds move.")


class CalendarProposalOut(BaseModel):
    id: str
    calendar_id: str
    base_revision: int = Field(description="The definition revision the preview is based on.")
    created_at: datetime
    expires_at: datetime
    display_calendar_id: str = Field(
        description="The calendar of the displays: the dimension's default (or `absolute`)."
    )
    definition: dict[str, Any] = Field(description="The new definition, as it will be stored.")
    items: list[CalendarProposalItem]
    series: list[SeriesBoundsChange]
    summary: CalendarProposalSummary


class CalendarApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategies: dict[str, CalendarStrategy] = Field(
        default_factory=dict, description="Item key → strategy."
    )
    default_strategy: CalendarStrategy = Field(
        default="keep_date",
        description="For items without a strategy, where it applies (else `keep_date`).",
    )


class CalendarApplyOut(BaseModel):
    calendar: EntityOut
    kept: int
    pinned: int
    constrained: int
    accepted: int = Field(description="Records left with a problem by an explicit `keep_date`.")
    backup: str | None = Field(description="The backup taken first (more than 100 items).")
    affected: Affected


class RecurrenceProposalIn(BaseModel):
    """The series' new rule (null: it stops recurring) and, optionally, its new start and end."""

    model_config = ConfigDict(extra="forbid")

    rule: dict[str, Any] | None = Field(description="The new recurrence rule, or null.")
    start: TimePoint | None = None
    end: EndSpec | None = None


class RecurrenceProposalItem(BaseModel):
    """A materialized occurrence (not in the trash) and what the change does to it."""

    entity_id: str
    name: str
    key: str
    state: str = Field(description="`referenced`, `modified` or `cancelled`.")
    original_start_t: MomentStr | None = Field(description="Its computed start when materialized.")
    start_t: MomentStr | None = Field(description="Its stored start now.")
    status: Literal["unchanged", "moved", "orphaned"]
    new_start_t: MomentStr | None = Field(
        description="The key's computed start with the new rule (null when orphaned)."
    )
    rekey_key: str | None = Field(
        description="`rekey` target: the occurrence starting at `original_start_t` (moved), or "
        "the first at or after it (orphaned)."
    )
    rekey_start_t: MomentStr | None
    rekey_held_by: str | None = Field(
        description="The materialized occurrence already holding `rekey_key`, if any."
    )
    strategies: list[RecurrenceStrategy]
    default_strategy: RecurrenceStrategy | None


class RecurrenceProposalSummary(BaseModel):
    unchanged: int
    moved: int
    orphaned: int


class RecurrenceProposalOut(BaseModel):
    id: str
    event_id: str
    base_revision: int = Field(description="The series row's revision the preview is based on.")
    created_at: datetime
    expires_at: datetime
    items: list[RecurrenceProposalItem]
    summary: RecurrenceProposalSummary


class RecurrenceApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategies: dict[str, RecurrenceStrategy] = Field(
        default_factory=dict,
        description="Occurrence entity id → strategy (others: their default).",
    )


class RecurrenceApplyOut(BaseModel):
    event: EntityOut
    kept: int
    rekeyed: int
    detached: int
    trashed: int
    affected: Affected
