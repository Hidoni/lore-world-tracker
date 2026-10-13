"""API schemas of facts (``api.md``, Facts; ``time-model.md`` §10.2)."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressItem
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId
from lore.core.types import Affected, MomentStr

EXISTS = "core.exists"
NAME = "core.name"
FACT_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$"

Note = Annotated[str, StringConstraints(max_length=5000)]
SortKey = Annotated[str, StringConstraints(max_length=100)]


class FactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: Annotated[str, StringConstraints(pattern=FACT_KEY_PATTERN, max_length=200)] = Field(
        description="A temporal field of the entity's kind, `core.exists` or `core.name`."
    )
    value: Any = Field(
        default=None,
        description="The field's value (checked by its type); `true` for `core.exists` (the "
        "default), a name for `core.name`.",
    )
    timeline_id: EntityId = Field(
        description="The timeline it holds in: of the entity's dimension (any for a multiversal "
        "entity)."
    )
    valid_from: TimePoint | None = Field(default=None, description="Start (`null`: always).")
    valid_to: TimePoint | None = Field(default=None, description="End, excluded (`null`: on).")
    visibility: Visibility = "public"
    source_event_id: EntityId | None = Field(default=None, description="The event that caused it.")
    note: Note | None = None
    sort_key: SortKey | None = None
    overrides_id: EntityId | None = Field(
        default=None, description="A branch's override of a fact (with branches, M9)."
    )
    suppress: list[SuppressItem] | None = None


class FactUpdate(BaseModel):
    """Only the members sent change (``null`` clears a nullable one)."""

    model_config = ConfigDict(extra="forbid")

    revision: int
    value: Any = None
    timeline_id: EntityId | None = None
    valid_from: TimePoint | None = None
    valid_to: TimePoint | None = None
    visibility: Visibility | None = None
    source_event_id: EntityId | None = None
    note: Note | None = None
    sort_key: SortKey | None = None
    suppress: list[SuppressItem] | None = None


class FactOut(BaseModel):
    id: str
    entity_id: str
    field_key: str
    value: Any
    value_t: MomentStr | None = Field(
        description="A `time_point` value's resolved moment (other types: `null`)."
    )
    timeline_id: str
    valid_from: TimePoint | None
    valid_to: TimePoint | None
    valid_from_t: MomentStr | None
    valid_to_t: MomentStr | None
    time_status: str | None
    visibility: Visibility
    source_event_id: str | None = Field(
        description="`null` also when the request may not see the event."
    )
    note: str | None
    sort_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class FactList(BaseModel):
    items: list[FactOut] = Field(
        description="By field, then start (open starts first), manual order and creation."
    )


class FactWriteResult(BaseModel):
    fact: FactOut
    affected: Affected
