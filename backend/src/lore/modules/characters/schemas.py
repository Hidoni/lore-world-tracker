"""API schemas of the characters module."""

from typing import Literal

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


class GenealogyPerson(BaseModel):
    id: str
    name: str
    visibility: Visibility
    generation: int = Field(
        description="Generations from the character: negative for ancestors, 0 for the character "
        "(and siblings and spouses), positive for descendants."
    )
    from_t: MomentStr | None = Field(
        description="Start of the existence on the timeline (`null`: unknown; existence comes "
        "with temporal facts)."
    )
    to_t: MomentStr | None


class GenealogyEdge(BaseModel):
    id: str = Field(description="The link's id.")
    kind: Literal["parent", "spouse", "sibling"]
    source_id: str = Field(description="The parent for `parent` edges.")
    target_id: str = Field(description="The child for `parent` edges.")
    relation: str | None = Field(
        description="The link's `data.kind`: biological, adoptive, half, marriage, …"
    )


class Genealogy(BaseModel):
    root_id: str
    people: list[GenealogyPerson] = Field(description="The character first, then by generation.")
    edges: list[GenealogyEdge]
    truncated: bool = Field(description="More relatives than the limit: the farthest are left out.")
