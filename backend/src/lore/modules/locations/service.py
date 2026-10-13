"""Reads of the locations module: the containment tree and the events at a location. Every read
goes through the request's ``VisibilityPolicy``; events through ``TimelineView``."""

from dataclasses import dataclass

from sqlalchemy import and_, select

from lore.core.entities.models import Entity
from lore.core.entities.queries import EntityQueries
from lore.core.entities.schemas import TreeNode
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.modules.spec import VaultContext
from lore.core.time import TimelineView
from lore.core.time.dimensions import TIMELINE
from lore.core.time.events import EventTimes, shown_events
from lore.core.time.models import Event
from lore.core.time.schemas import EventDisplay
from lore.core.visibility import VisibilityPolicy
from lore.modules.locations.kinds import LOCATION
from lore.modules.locations.links import EVENT_SITE
from lore.modules.locations.schemas import LocationEvent, LocationEvents, LocationNode, LocationTree

TYPE_FIELD = "location_type"
# Descendants searched for "events here" at most (a deeper world cuts the search).
MAX_SITES = 5_000


@dataclass
class Locations:
    context: VaultContext
    policy: VisibilityPolicy

    def __post_init__(self) -> None:
        self.entities = EntityService(self.context, self.policy)
        self.queries = EntityQueries(self.entities)
        self.session = self.context.session

    def location(self, location_id: str) -> Entity:
        """A location the request sees (``404`` otherwise, also for other kinds)."""
        entity = self.entities.load_visible(location_id)
        if entity.kind != LOCATION:
            raise NotFoundError(f"No location {location_id}.")
        return entity

    # --- the containment tree -------------------------------------------------------------------

    def tree(
        self, *, dimension: str | None, root: str | None, depth: int, limit: int
    ) -> LocationTree:
        """``depth`` levels of child locations of ``root`` (default: the top-level locations, in
        ``dimension`` when given), each level at most ``limit`` nodes."""
        if root is not None:
            self.location(root)
        truncated = False

        def level(parent: str | None, remaining: int) -> list[LocationNode]:
            nonlocal truncated
            page = self.queries.tree(
                dimension=dimension,
                parent=parent,
                kinds=[LOCATION],
                group_by=TYPE_FIELD,
                limit=limit,
            )
            truncated = truncated or page.next_cursor is not None
            return [node(item, remaining) for item in page.items]

        def node(item: TreeNode, remaining: int) -> LocationNode:
            count = item.child_counts.get(LOCATION, 0)
            children = None
            if remaining > 1:
                children = level(item.id, remaining - 1) if count else []
            return LocationNode(
                id=item.id,
                name=item.name,
                visibility=item.visibility,
                dimension_id=item.dimension_id,
                parent_id=item.parent_id,
                multiversal=item.multiversal,
                location_type=item.group,
                child_count=count,
                children=children,
            )

        return LocationTree(root_id=root, items=level(root, depth), truncated=truncated)

    # --- events here ----------------------------------------------------------------------------

    def sites(self, location_id: str, *, descendants: bool) -> list[str]:
        """The location and, with ``descendants``, the live locations below it the request sees
        (through visible parents only: a hidden location hides its contents)."""
        found = [location_id]
        seen = {location_id}
        frontier = [location_id]
        while descendants and frontier and len(found) < MAX_SITES:
            children = list(
                self.session.scalars(
                    select(Entity.id)
                    .where(
                        Entity.parent_id.in_(frontier),
                        Entity.kind == LOCATION,
                        Entity.deleted_at.is_(None),
                        *self.policy.entities(Entity),
                    )
                    .order_by(Entity.id)
                )
            )
            frontier = [child for child in children if child not in seen]
            seen.update(frontier)
            found += frontier
        return found[:MAX_SITES]

    def events(
        self,
        location_id: str,
        *,
        timeline_id: str,
        descendants: bool,
        start: int | None,
        end: int | None,
        limit: int,
    ) -> LocationEvents:
        """Events the timeline shows that took place at the location (or below it), by start,
        then name; ``start``/``end`` keep those overlapping ``[start, end)``."""
        self.location(location_id)
        timeline = self.entities.load_visible(timeline_id)
        if timeline.kind != TIMELINE or timeline.deleted_at is not None:
            raise NotFoundError(f"No timeline {timeline_id}.")
        sites = self.sites(location_id, descendants=descendants)
        view = TimelineView.for_timeline(self.session, timeline_id)
        site = and_(
            Link.source_id == Entity.id,
            Link.link_type == EVENT_SITE,
            Link.target_id.in_(sites),
            Link.deleted_at.is_(None),
            *self.policy.links(Link),
        )
        statement = (
            shown_events(view.select(Event), view, self.policy)
            .add_columns(Entity, Link.target_id)
            .join(Link, site)
        )
        if start is not None:
            statement = statement.where(Event.end_t >= start)
        if end is not None:
            statement = statement.where(Event.start_t < end)
        statement = statement.order_by(Event.start_t, Entity.sort_name, Entity.id, Link.target_id)
        found: dict[str, tuple[Event, Entity, list[str]]] = {}
        truncated = False
        for row, entity, target in self.session.execute(statement):
            if entity.id in found:
                found[entity.id][2].append(target)
                continue
            if len(found) >= limit:
                truncated = True
                break
            found[entity.id] = (row, entity, [target])
        times = EventTimes(self.context, self.policy)
        return LocationEvents(
            items=[
                LocationEvent(
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
                    site_ids=targets,
                )
                for row, entity, targets in found.values()
            ],
            truncated=truncated,
        )
