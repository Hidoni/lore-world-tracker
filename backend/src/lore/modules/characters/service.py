"""Reads of the characters module: relationships by category, the events of a life and the
family tree. Every read goes through the request's ``VisibilityPolicy``; events through
``TimelineView``."""

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.facts.schemas import EXISTS
from lore.core.links.models import Link
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.time import TimelineView
from lore.core.time.dimensions import TIMELINE, prime_timeline
from lore.core.time.events import EventTimes, shown_events
from lore.core.time.models import Event
from lore.core.time.schemas import EventDisplay
from lore.core.time.state import AsOf, StateReader, as_of_for
from lore.core.types import Existence
from lore.core.visibility import VisibilityPolicy
from lore.modules.characters.kinds import CHARACTER
from lore.modules.characters.links import (
    CATEGORIES,
    PARENT_OF,
    SIBLING_OF,
    SPOUSE_OF,
    Category,
)
from lore.modules.characters.schemas import (
    Genealogy,
    GenealogyEdge,
    GenealogyPerson,
    Life,
    LifeEvent,
    RelationshipGroup,
    Relationships,
)

PARTICIPANT = "core.participant"
ORDER: tuple[Category, ...] = ("family", "social", "custom")
FAMILY: dict[str, Literal["parent", "spouse", "sibling"]] = {
    PARENT_OF: "parent",
    SPOUSE_OF: "spouse",
    SIBLING_OF: "sibling",
}


@dataclass
class _Tree:
    """The people of a family tree being gathered: generation by id, in the order found."""

    limit: int
    generations: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    def add(self, ids: Iterable[str], generation: int) -> list[str]:
        """Adds the people not in the tree yet; returns them (none once the limit is reached)."""
        added = []
        for person in ids:
            if person in self.generations:
                continue
            if len(self.generations) >= self.limit:
                self.truncated = True
                break
            self.generations[person] = generation
            added.append(person)
        return added


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

    def relationships(self, character_id: str, *, as_of: AsOf | None = None) -> Relationships:
        """The character's relationship links: the module's types by category, and links of
        user-defined types to other characters as custom ones (``as_of``: those valid then)."""
        self.character(character_id)
        context = self.context
        links = LinkService(context.session, context.registry, self.policy, context.vault)
        groups: dict[Category, RelationshipGroup] = {
            category: RelationshipGroup(category=category, items=[]) for category in ORDER
        }
        for item in links.entity_links(character_id, as_of=as_of).items:
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

    # --- family tree ----------------------------------------------------------------------------

    def _family_links(
        self, ids: Collection[str], types: Collection[str], *, side: str = "any"
    ) -> list[Link]:
        """The visible family links of ``types`` touching ``ids`` (``side``: ``source``,
        ``target`` or ``any``) whose ends are both characters that aren't in the trash."""
        if not ids:
            return []
        source = aliased(Entity)
        target = aliased(Entity)
        touching = {
            "source": Link.source_id.in_(ids),
            "target": Link.target_id.in_(ids),
            "any": or_(Link.source_id.in_(ids), Link.target_id.in_(ids)),
        }[side]
        statement = (
            select(Link)
            .join(source, source.id == Link.source_id)
            .join(target, target.id == Link.target_id)
            .where(
                Link.link_type.in_(list(types)),
                Link.deleted_at.is_(None),
                touching,
                *self.policy.links(Link),
                *(
                    condition
                    for end in (source, target)
                    for condition in (
                        end.kind == CHARACTER,
                        end.deleted_at.is_(None),
                        *self.policy.entities(end),
                    )
                ),
            )
            .order_by(Link.id)
        )
        return list(self.session.scalars(statement))

    def _add_symmetric(self, tree: _Tree, among: list[str], link_type: str) -> None:
        """Adds the people linked to ``among`` by a symmetric ``link_type``, in their generation."""
        for link in self._family_links(among, [link_type]):
            for person, other in (
                (link.source_id, link.target_id),
                (link.target_id, link.source_id),
            ):
                if person in among:
                    tree.add([other], tree.generations[person])

    def _add_siblings(self, tree: _Tree, line: list[str], root_id: str) -> None:
        """The siblings of the character and their ancestors: linked ones, and the other
        children of the parents in the tree."""
        self._add_symmetric(tree, line, SIBLING_OF)
        ancestors = [person for person in line if person != root_id]
        for link in self._family_links(ancestors, [PARENT_OF], side="source"):
            tree.add([link.target_id], tree.generations[link.source_id] + 1)

    def _add_spouses(self, tree: _Tree, root_id: str, up: int) -> None:
        """Everyone's spouses, and the other parents of children in the tree within the
        generations asked for (the parents of a half-sibling or of a grandchild)."""
        people = list(tree.generations)
        self._add_symmetric(tree, people, SPOUSE_OF)
        offspring = [
            person for person in people if person != root_id and tree.generations[person] - 1 >= -up
        ]
        for link in self._family_links(offspring, [PARENT_OF], side="target"):
            tree.add([link.source_id], tree.generations[link.target_id] - 1)

    def family_tree(
        self,
        character_id: str,
        *,
        up: int,
        down: int,
        include_spouses: bool,
        include_siblings: bool,
        timeline_id: str | None,
        at: str | None = None,
        limit: int,
    ) -> Genealogy:
        """The character's family: ``up`` generations of ancestors and ``down`` of descendants,
        with the siblings of the character and their ancestors, and everyone's spouses (and the
        other parents of their children), as people by generation and the family links between
        them. Gathered generation by generation, a set of links at a time. Lifespans are read on
        the timeline (default: the prime timeline of the character's dimension), and existence
        at ``at`` (the time cursor)."""
        root = self.character(character_id)
        if timeline_id is not None:
            timeline = self.entities.load_visible(timeline_id)
            if timeline.kind != TIMELINE or timeline.deleted_at is not None:
                raise NotFoundError(f"No timeline {timeline_id}.")
        as_of = as_of_for(self.context, self.policy, timeline_id=timeline_id, at=at,
                          dimension_id=root.dimension_id)  # fmt: skip
        if timeline_id is None and root.dimension_id is not None:
            prime = prime_timeline(self.session, root.dimension_id)
            timeline_id = None if prime is None else prime.id
        tree = _Tree(limit)
        tree.add([root.id], 0)
        line = [root.id]
        frontier = [root.id]
        for generation in range(1, up + 1):
            parents = self._family_links(frontier, [PARENT_OF], side="target")
            frontier = tree.add((link.source_id for link in parents), -generation)
            line += frontier
        frontier = [root.id]
        for generation in range(1, down + 1):
            children = self._family_links(frontier, [PARENT_OF], side="source")
            frontier = tree.add((link.target_id for link in children), generation)
        if include_siblings:
            self._add_siblings(tree, line, root.id)
        if include_spouses:
            self._add_spouses(tree, root.id, up)
        ids = list(tree.generations)
        names = {
            entity.id: entity
            for entity in self.session.scalars(select(Entity).where(Entity.id.in_(ids)))
        }
        edges = [
            GenealogyEdge(
                id=link.id,
                kind=FAMILY[link.link_type],
                source_id=link.source_id,
                target_id=link.target_id,
                relation=_relation(link.data),
            )
            for link in self._family_links(ids, list(FAMILY), side="source")
            if link.target_id in tree.generations
        ]
        order = sorted(ids, key=lambda person: (person != root.id, tree.generations[person]))
        lifespans: dict[str, tuple[int | None, int | None]] = {}
        existence: dict[str, Existence] = {}
        if timeline_id is not None:
            reader = StateReader(self.context, self.policy, timeline_id,
                                 0 if as_of is None else as_of.t)  # fmt: skip
            lifespans = {
                person: _lifespan(facts)
                for person, facts in reader.facts(ids, keys=[EXISTS]).items()
            }
            if as_of is not None:
                existence = reader.existence([names[person] for person in order])
        return Genealogy(
            root_id=root.id,
            people=[
                GenealogyPerson(
                    id=person,
                    name=names[person].name,
                    visibility=names[person].visibility,
                    generation=tree.generations[person],
                    from_t=lifespans.get(person, (None, None))[0],
                    to_t=lifespans.get(person, (None, None))[1],
                    existence=existence.get(person),
                )
                for person in order
            ],
            edges=edges,
            truncated=tree.truncated,
        )

    # --- static export --------------------------------------------------------------------------

    def static_data(self, timelines: Iterable[str]) -> dict[str, Any]:
        """What ``frontend/src/data/static-family.ts`` computes any family tree from (#386):
        every family link the request sees (``[id, type, source, target, relation]``, by id) and
        each character's lifespan per timeline (``[from, to]``, moments as strings)."""
        people = list(
            self.session.scalars(
                select(Entity.id).where(
                    Entity.kind == CHARACTER,
                    Entity.deleted_at.is_(None),
                    *self.policy.entities(Entity),
                )
            )
        )
        links = [
            [link.id, link.link_type, link.source_id, link.target_id, _relation(link.data)]
            for link in self._family_links(people, list(FAMILY))
        ]
        lifespans: dict[str, dict[str, list[str | None]]] = {}
        for timeline_id in timelines:
            reader = StateReader(self.context, self.policy, timeline_id, 0)
            lifespans[timeline_id] = {
                person: [None if t is None else str(t) for t in _lifespan(facts)]
                for person, facts in reader.facts(people, keys=[EXISTS]).items()
            }
        return {"links": links, "lifespans": lifespans}


def _lifespan(facts: Sequence[EntityFact]) -> tuple[int | None, int | None]:
    """The earliest start and latest end of existence periods (``None`` when one is open)."""
    starts = [fact.valid_from_t for fact in facts]
    ends = [fact.valid_to_t for fact in facts]
    return (
        None if not starts or None in starts else min(t for t in starts if t is not None),
        None if not ends or None in ends else max(t for t in ends if t is not None),
    )


def _relation(data: object) -> str | None:
    kind = data.get("kind") if isinstance(data, dict) else None
    return kind if isinstance(kind, str) else None
