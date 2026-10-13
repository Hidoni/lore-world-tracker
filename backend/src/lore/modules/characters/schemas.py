"""API schemas of the characters module."""

from pydantic import BaseModel, Field

from lore.core.db.base import Visibility
from lore.core.links.schemas import EntityLink
from lore.core.time.schemas import EventDisplay
from lore.core.types import MomentStr
from lore.modules.characters.links import Category


class RelationshipGroup(BaseModel):
    category: Category
    items: list[EntityLink]


class Relationships(BaseModel):
    groups: list[RelationshipGroup] = Field(
        description="Family, social and custom relationships, in that order (empty ones too)."
    )


class LifeEvent(BaseModel):
    id: str
    name: str
    visibility: Visibility
    start_t: MomentStr | None
    end_t: MomentStr | None
    time_status: str | None
    importance: int
    display: EventDisplay
    roles: list[str] = Field(description="The roles of the character's participant links.")


class Life(BaseModel):
    items: list[LifeEvent]
    truncated: bool
