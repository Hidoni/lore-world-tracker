"""Request bodies of the branches module."""

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, EntityName
from lore.core.types import Affected


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
