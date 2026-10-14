"""Request bodies of the branches module."""

from pydantic import Field

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, EntityName


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
