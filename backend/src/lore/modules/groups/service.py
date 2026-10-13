"""Reads of the groups module: members (with sub-groups), the leadership succession and the
territory. Links come from the core link listing (the request's ``VisibilityPolicy``)."""

from dataclasses import dataclass

from sqlalchemy import select

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.groups.kinds import GROUP
from lore.modules.groups.links import CONTROLS, LED_BY, MEMBER_OF
from lore.modules.groups.schemas import Leaders, Leadership, Members, Membership

# Sub-groups searched for members at most.
MAX_SUBGROUPS = 1_000


@dataclass
class Groups:
    context: VaultContext
    policy: VisibilityPolicy

    def __post_init__(self) -> None:
        self.entities = EntityService(self.context, self.policy)
        self.session = self.context.session
        context = self.context
        self.links = LinkService(context.session, context.registry, self.policy, context.vault)

    def group(self, group_id: str) -> Entity:
        """A group the request sees (``404`` otherwise, also for other kinds)."""
        entity = self.entities.load_visible(group_id)
        if entity.kind != GROUP:
            raise NotFoundError(f"No group {group_id}.")
        return entity

    def subgroups(self, group_id: str) -> list[str]:
        """The live sub-groups below a group (by ``parent_id``) the request sees, through
        visible parents only, nearest first."""
        found: list[str] = []
        seen = {group_id}
        frontier = [group_id]
        while frontier and len(found) < MAX_SUBGROUPS:
            children = [
                child
                for child in self.session.scalars(
                    select(Entity.id)
                    .where(
                        Entity.parent_id.in_(frontier),
                        Entity.kind == GROUP,
                        Entity.deleted_at.is_(None),
                        *self.policy.entities(Entity),
                    )
                    .order_by(Entity.sort_name, Entity.id)
                )
                if child not in seen
            ]
            seen.update(children)
            found += children
            frontier = children
        return found[:MAX_SUBGROUPS]

    def members(self, group_id: str, *, include_subgroups: bool) -> Members:
        """Members of the group (and of its sub-groups), at any time."""
        self.group(group_id)
        groups = [group_id, *(self.subgroups(group_id) if include_subgroups else [])]
        return Members(
            items=[
                Membership(group_id=group, item=item)
                for group in groups
                for item in self.links.entity_links(group, direction="in", types=[MEMBER_OF]).items
            ]
        )

    def leaders(self, group_id: str) -> Leaders:
        """The leadership succession: ``led_by`` links, timeless ones first, then by the start
        and end of their validity."""
        self.group(group_id)
        items = self.links.entity_links(group_id, direction="out", types=[LED_BY]).items
        bounds = {
            link_id: (start, end)
            for link_id, start, end in self.session.execute(
                select(Link.id, Link.valid_from_t, Link.valid_to_t).where(
                    Link.id.in_([item.link.id for item in items])
                )
            )
        }

        def key(leadership: Leadership) -> tuple[bool, int, bool, int, str]:
            start, end = leadership.from_t, leadership.to_t
            return (
                start is not None,
                int(start or 0),
                end is None,
                int(end or 0),
                leadership.item.other.name,
            )

        leaderships = [
            Leadership(
                item=item,
                from_t=bounds.get(item.link.id, (None, None))[0],
                to_t=bounds.get(item.link.id, (None, None))[1],
            )
            for item in items
        ]
        return Leaders(items=sorted(leaderships, key=key))

    def territory(self, group_id: str) -> EntityLinks:
        """The locations the group controls (``controls`` links), at any time."""
        self.group(group_id)
        return self.links.entity_links(group_id, direction="out", types=[CONTROLS])
