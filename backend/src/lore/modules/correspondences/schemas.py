"""Request and response bodies of the correspondences module (``time-model.md`` §12)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from lore.chronology.schema import Rational, TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, EntityName
from lore.core.types import Affected, MomentStr

Extrapolation = Literal["none", "rate"]

RATE_HELP = (
    "Dimension B units per dimension A unit beyond the sync points (`rate` extrapolation); null: "
    "the slope of the adjacent segment (a single sync point needs both)."
)


class SyncPointIn(BaseModel):
    a: TimePoint = Field(description="The moment in dimension A (may be anchored to its events).")
    b: TimePoint = Field(description="The same moment in dimension B.")
    note: str | None = Field(default=None, max_length=5000)


class CorrespondenceCreate(SuppressIn):
    dimension_a_id: EntityId
    dimension_b_id: EntityId
    name: EntityName
    extrapolation: Extrapolation = "none"
    rate_before: Rational | None = Field(default=None, description=RATE_HELP)
    rate_after: Rational | None = Field(default=None, description=RATE_HELP)
    note: str | None = Field(default=None, max_length=5000)
    visibility: Visibility = "public"
    points: list[SyncPointIn] = Field(min_length=1, max_length=10_000)


class CorrespondenceUpdate(SuppressIn):
    """Changes to a correspondence (its dimensions never change); ``points`` replaces them all."""

    revision: int
    name: EntityName | None = None
    extrapolation: Extrapolation | None = None
    rate_before: Rational | None = Field(default=None, description=RATE_HELP)
    rate_after: Rational | None = Field(default=None, description=RATE_HELP)
    note: str | None = Field(default=None, max_length=5000)
    visibility: Visibility | None = None
    points: list[SyncPointIn] | None = Field(default=None, min_length=1, max_length=10_000)


class SyncPointOut(BaseModel):
    id: str
    a: dict[str, Any] | None = Field(description="Readers: as moments when anchored to hidden "
                                     "records.")  # fmt: skip
    b: dict[str, Any] | None
    a_t: MomentStr | None
    b_t: MomentStr | None
    time_status: str | None
    note: str | None


class CorrespondenceOut(BaseModel):
    id: str
    dimension_a_id: str
    dimension_b_id: str
    name: str
    extrapolation: Extrapolation
    rate_before: Rational | None
    rate_after: Rational | None
    note: str | None
    visibility: Visibility
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    points: list[SyncPointOut] = Field(description="In the order given.")


class CorrespondenceList(BaseModel):
    items: list[CorrespondenceOut] = Field(description="By name.")


class CorrespondenceWriteResult(BaseModel):
    correspondence: CorrespondenceOut
    affected: Affected


class MapOut(BaseModel):
    from_dimension: str
    to_dimension: str
    t: MomentStr
    result_t: MomentStr | None = Field(description="Null when there is no corresponding moment.")
    defined: bool
    path: list[str] = Field(
        description="The correspondences mapped through, in order (empty when unconnected)."
    )


class MapBatchIn(BaseModel):
    from_dimension: EntityId
    to_dimension: EntityId
    t: list[MomentStr] = Field(min_length=1, max_length=10_000)


class MappedMoment(BaseModel):
    t: MomentStr
    result_t: MomentStr | None
    defined: bool


class MapBatchOut(BaseModel):
    from_dimension: str
    to_dimension: str
    items: list[MappedMoment] = Field(description="In the order asked.")
    path: list[str]
