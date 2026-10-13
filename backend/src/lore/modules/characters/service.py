"""Reads of the characters module: relationships by category and the events of a life. Every
read goes through the request's ``VisibilityPolicy``; events through ``TimelineView``."""

from dataclasses import dataclass

from sqlalchemy import and_

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.time import TimelineView
from lore.core.time.dimensions import TIMELINE
from lore.core.time.events import EventTimes, shown_events
from lore.core.time.models import Event
from lore.core.time.schemas import EventDisplay
from lore.core.visibility import VisibilityPolicy
from lore.modules.characters.kinds import CHARACTER
from lore.modules.characters.links import CATEGORIES, Category
from lore.modules.characters.schemas import (
    Life,
    LifeEvent,
    RelationshipGroup,
    Relationships,
)

PARTICIPANT = "core.participant"
ORDER: tuple[Category, ...] = ("family", "social", "custom")


@dataclass
class Characters:
    context: VaultContext
    policy: VisibilityPolicy

    def __post_init__(self) -> None:
        self.entities = EntityService(self.context, self.policy)
        self.session = self.context.session

    def character(self, character_id: str) -> Entity:
        """A character the request sees (``404`` otherwise, also for other kinds)."""
        entity = self.entities.load_visible(character_id)
        if entity.kind != CHARACTER:
            raise NotFoundError(f"No character {character_id}.")
        return entity

    def relationships(self, character_id: str) -> Relationships:
        """The character's relationship links: the module's types by category, and links of
        user-defined types to other characters as custom ones."""
        self.character(character_id)
        context = self.context
        links = LinkService(context.session, context.registry, self.policy, context.vault)
        groups: dict[Category, RelationshipGroup] = {
            category: RelationshipGroup(category=category, items=[]) for category in ORDER
        }
        for item in links.entity_links(character_id).items:
            category = CATEGORIES.get(item.link.link_type)
            if category is None and item.link.link_type.startswith("custom."):
                category = "custom" if item.other.kind == CHARACTER else None
            if category is not None:
                groups[category].items.append(item)
        return Relationships(groups=list(groups.values()))

    def life(self, character_id: str, *, timeline_id: str, limit: int) -> Life:
        """The events the timeline shows that the character takes part in (a visible
        ``core.participant`` link), by start, with the roles."""
        self.character(character_id)
        timeline = self.entities.load_visible(timeline_id)
        if timeline.kind != TIMELINE or timeline.deleted_at is not None:
            raise NotFoundError(f"No timeline {timeline_id}.")
        view = TimelineView.for_timeline(self.session, timeline_id)
        participant = and_(
            Link.source_id == Entity.id,
            Link.link_type == PARTICIPANT,
            Link.target_id == character_id,
            Link.deleted_at.is_(None),
            *self.policy.links(Link),
        )
        statement = (
            shown_events(view.select(Event), view, self.policy)
            .add_columns(Entity, Link.role)
            .join(Link, participant)
            .order_by(Event.start_t, Entity.sort_name, Entity.id, Link.id)
        )
        found: dict[str, tuple[Event, Entity, list[str]]] = {}
        truncated = False
        for row, entity, role in self.session.execute(statement):
            if entity.id not in found:
                if len(found) >= limit:
                    truncated = True
                    break
                found[entity.id] = (row, entity, [])
            if role:
                found[entity.id][2].append(role)
        times = EventTimes(self.context, self.policy)
        return Life(
            items=[
                LifeEvent(
                    id=entity.id,
                    name=entity.name,
                    visibility=entity.visibility,
                    start_t=row.start_t,
                    end_t=row.end_t,
                    time_status=row.time_status,
                    importance=row.importance,
                    display=EventDisplay.model_validate(
                        times.displays(str(entity.dimension_id), row)
                    ),
                    roles=roles,
                )
                for row, entity, roles in found.values()
            ],
            truncated=truncated,
        )
