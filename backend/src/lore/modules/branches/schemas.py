"""Request bodies of the branches module."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, EntityName
from lore.core.types import Affected, MomentStr


class BranchCreate(SuppressIn):
    parent_timeline_id: EntityId = Field(description="The timeline to branch from.")
    branch_point: TimePoint = Field(
        description="Where the branch diverges: records starting before it are inherited. "
        "It may be anchored, but only to records of the parent timeline."
    )
    name: EntityName
    summary: str = Field(default="", description="The premise (“What if…”).")
    visibility: Visibility | None = Field(
        default=None, description="Defaults to the parent timeline's."
    )


RECORD_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$"


class OverrideCreate(SuppressIn):
    record_type: Annotated[str, StringConstraints(pattern=RECORD_TYPE_PATTERN)] = Field(
        description="What is overridden: `event`, `fact`, `link`, or a module's validity record "
        "(`maps.pin`)."
    )
    root_id: EntityId = Field(description="The inherited record: an event's entity id, or the "
                              "fact's or link's id.")  # fmt: skip
    timeline_id: EntityId = Field(description="The branch overriding it.")
    changes: dict[str, Any] = Field(
        description="Events: `end` (an end spec), `recurrence` (the rule with a new `limit` or "
        "more `exclusions`); facts: `value`, `valid_to`; links: `role`, `data`, `valid_to`. "
        "Only what lies after the branch point may change."
    )


class OverrideOut(BaseModel):
    record_type: str
    id: str = Field(description="The override row (what reverting it takes).")
    root_id: str
    timeline_id: str
    affected: Affected


class BranchProposalIn(SuppressIn):
    operation: Literal["reparent", "merge"] = Field(
        description="`reparent`: move the branch under `parent_timeline_id`; `merge`: merge it "
        "into its parent (`time-model.md` §4.7)."
    )
    parent_timeline_id: EntityId | None = Field(
        default=None, description="`reparent` only: the new parent, a timeline of the dimension."
    )


class BranchRecord(BaseModel):
    record_type: str = Field(description="`event`, `fact`, `link`, `segment` or a module's.")
    id: str = Field(description="The row.")
    entity_id: str | None = Field(description="The entity the row belongs to.")
    name: str | None
    override: bool = Field(description="Whether the row is an override.")
    start_t: MomentStr | None
    end_t: MomentStr | None
    action: str | None = Field(
        default=None,
        description="Records of the branch: `move` (to the parent), `replace` (the parent's own "
        "override is reverted, this one moves), `apply` (the parent's record takes its changes), "
        "`rehome` (the override moves to the parent); re-parenting: `drop`.",
    )
    key: str | None = Field(default=None, description="Conflicts: the key strategies use.")
    strategies: list[str] | None = Field(
        default=None, description="Conflicts: `keep`, and `discard` where possible."
    )
    default_strategy: str | None = None


class TimelineMove(BaseModel):
    id: str
    name: str | None
    from_parent_id: str | None
    to_parent_id: str


class OriginChange(BaseModel):
    id: str
    name: str | None
    to_origin_id: str | None = Field(description="Null: shown in every timeline.")


class NamedTimeline(BaseModel):
    id: str
    name: str | None


class BranchProposalSummary(BaseModel):
    records: int
    by_action: dict[str, int]
    conflicts: int
    timelines: int
    entities: int
    pinned: int
    notes_moved: int
    notes_kept: int
    hidden_references: int = Field(
        description="Re-parenting: slots of the branch's records anchored to records it no "
        "longer sees."
    )


class BranchProposalOut(BaseModel):
    id: str
    timeline_id: str
    operation: Literal["reparent", "merge"]
    parent_timeline_id: str = Field(description="The new parent, or the parent merged into.")
    base_revision: int
    created_at: datetime
    expires_at: datetime
    records: list[BranchRecord] = Field(
        description="The branch's records the operation moves or changes (at most 200; the "
        "summary counts them all)."
    )
    conflicts: list[BranchRecord] = Field(
        description="Merging: the parent's live records starting at or after the branch point, "
        "each kept or discarded."
    )
    timelines: list[TimelineMove]
    entities: list[OriginChange] = Field(description="Entities whose origin timeline changes.")
    pinned: list[NamedTimeline] = Field(
        description="Branches whose branch point is pinned to its moment (anchored to records "
        "their parent would no longer see)."
    )
    siblings: list[NamedTimeline] = Field(
        description="Merging: the parent's other branches after the branch point, which will "
        "inherit merged records."
    )
    summary: BranchProposalSummary


class BranchProposalApply(SuppressIn):
    strategies: dict[str, Literal["keep", "discard"]] = Field(
        default_factory=dict, description="Conflicts by key: `keep` or `discard`."
    )
    default_strategy: Literal["keep", "discard"] = Field(
        default="keep", description="For conflicts without a strategy (where possible)."
    )


class BranchApplied(BaseModel):
    operation: Literal["reparent", "merge"]
    moved: int
    discarded: int
    timelines: int
    pinned: int
    affected: Affected
