"""Reads of the groups module: members (with sub-groups), the leadership succession, the
territory and the org chart. Links come from the core link listing or are read through the
request's ``VisibilityPolicy``."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import aliased

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.time.dimensions import TIMELINE
from lore.core.visibility import VisibilityPolicy
from lore.modules.groups.kinds import GROUP
from lore.modules.groups.links import CONTROLS, LED_BY, MEMBER_OF, PART_OF
from lore.modules.groups.schemas import (
    Leaders,
    Leadership,
    Members,
    Membership,
    OrgChart,
    OrgLeader,
    OrgUnit,
)

# Sub-groups searched for members at most.
MAX_SUBGROUPS = 1_000
# Units of an org chart at most.
MAX_UNITS = 500


def valid_at(at: int | None) -> list[ColumnElement[bool]]:
    """Conditions for a link valid at ``at`` (open bounds count; none without ``at``)."""
    if at is None:
        return []
    return [
        or_(Link.valid_from_t.is_(None), Link.valid_from_t <= at),
        or_(Link.valid_to_t.is_(None), Link.valid_to_t > at),
    ]


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

    def _bounds(self, link_ids: Sequence[str]) -> dict[str, tuple[int | None, int | None]]:
        """The resolved validity of links (``(None, None)``: open)."""
        return {
            link_id: (start, end)
            for link_id, start, end in self.session.execute(
                select(Link.id, Link.valid_from_t, Link.valid_to_t).where(
                    Link.id.in_(list(link_ids))
                )
            )
        }

    def members(self, group_id: str, *, include_subgroups: bool) -> Members:
        """Members of the group (and of its sub-groups), at any time, with the validity of their
        memberships (the history Gantt)."""
        self.group(group_id)
        groups = [group_id, *(self.subgroups(group_id) if include_subgroups else [])]
        found = [
            (group, item)
            for group in groups
            for item in self.links.entity_links(group, direction="in", types=[MEMBER_OF]).items
        ]
        bounds = self._bounds([item.link.id for _, item in found])
        return Members(
            items=[
                Membership(
                    group_id=group,
                    item=item,
                    from_t=bounds.get(item.link.id, (None, None))[0],
                    to_t=bounds.get(item.link.id, (None, None))[1],
                )
                for group, item in found
            ]
        )

    def leaders(self, group_id: str) -> Leaders:
        """The leadership succession: ``led_by`` links, timeless ones first, then by the start
        and end of their validity."""
        self.group(group_id)
        items = self.links.entity_links(group_id, direction="out", types=[LED_BY]).items
        bounds = self._bounds([item.link.id for item in items])

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

    # --- org chart ------------------------------------------------------------------------------

    def _visible_links(
        self, link_type: str, *, ids: Collection[str], side: str, at: int | None
    ) -> list[tuple[Link, Entity]]:
        """Visible ``link_type`` links with ``side`` (``source``/``target``) in ``ids``, valid at
        ``at``, with the entity at their other end (visible and not in the trash)."""
        other = aliased(Entity)
        column, other_column = (
            (Link.source_id, Link.target_id)
            if side == "source"
            else (Link.target_id, Link.source_id)
        )
        statement = (
            select(Link, other)
            .join(other, other.id == other_column)
            .where(
                Link.link_type == link_type,
                Link.deleted_at.is_(None),
                column.in_(list(ids)),
                other.deleted_at.is_(None),
                *self.policy.links(Link),
                *self.policy.entities(other),
                *valid_at(at),
            )
            .order_by(other.sort_name, other.id, Link.id)
        )
        return [(link, entity) for link, entity in self.session.execute(statement)]

    def org_chart(
        self, group_id: str, *, depth: int, at: int | None, timeline_id: str | None
    ) -> OrgChart:
        """The group's structure for the org chart: its sub-groups (``parent_id``) and parts
        (``part_of`` links valid at ``at``), ``depth`` levels down, each with its leaders and
        member count (links valid at ``at``; all of them without ``at``)."""
        root = self.group(group_id)
        if timeline_id is not None:
            timeline = self.entities.load_visible(timeline_id)
            if timeline.kind != TIMELINE or timeline.deleted_at is not None:
                raise NotFoundError(f"No timeline {timeline_id}.")
        units: dict[str, dict[str, Any]] = {
            root.id: {"entity": root, "parent_id": None, "via": "root", "depth": 0}
        }
        truncated = False
        frontier = [root.id]
        for level in range(1, depth + 1):
            if not frontier:
                break
            below: list[tuple[str, Entity, str]] = [
                (str(child.parent_id), child, "subgroup")
                for child in self.session.scalars(
                    select(Entity)
                    .where(
                        Entity.parent_id.in_(frontier),
                        Entity.kind == GROUP,
                        Entity.deleted_at.is_(None),
                        *self.policy.entities(Entity),
                    )
                    .order_by(Entity.sort_name, Entity.id)
                )
            ]
            below += [
                (link.target_id, part, "part_of")
                for link, part in self._visible_links(PART_OF, ids=frontier, side="target", at=at)
                if part.kind == GROUP
            ]
            frontier = []
            for parent_id, entity, via in below:
                if entity.id in units:
                    continue
                if len(units) >= MAX_UNITS:
                    truncated = True
                    break
                units[entity.id] = {
                    "entity": entity,
                    "parent_id": parent_id,
                    "via": via,
                    "depth": level,
                }
                frontier.append(entity.id)
        ids = list(units)
        leaders: dict[str, list[OrgLeader]] = {unit: [] for unit in ids}
        for link, leader in self._visible_links(LED_BY, ids=ids, side="source", at=at):
            title = link.data.get("title") if isinstance(link.data, dict) else None
            leaders[link.source_id].append(
                OrgLeader(
                    id=leader.id, name=leader.name, title=title if isinstance(title, str) else None
                )
            )
        member = aliased(Entity)
        counts: dict[str, int] = dict(
            self.session.execute(
                select(Link.target_id, func.count(Link.id))
                .join(member, member.id == Link.source_id)
                .where(
                    Link.link_type == MEMBER_OF,
                    Link.deleted_at.is_(None),
                    Link.target_id.in_(ids),
                    member.deleted_at.is_(None),
                    *self.policy.links(Link),
                    *self.policy.entities(member),
                    *valid_at(at),
                )
                .group_by(Link.target_id)
            ).all()
        )
        return OrgChart(
            root_id=root.id,
            units=[
                OrgUnit(
                    id=unit_id,
                    name=unit["entity"].name,
                    visibility=unit["entity"].visibility,
                    parent_id=unit["parent_id"],
                    via=unit["via"],
                    depth=unit["depth"],
                    leaders=leaders[unit_id],
                    member_count=counts.get(unit_id, 0),
                )
                for unit_id, unit in units.items()
            ],
            truncated=truncated,
        )
