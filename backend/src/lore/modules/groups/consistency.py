"""The groups module's consistency rules (``docs/modules/groups.md``).

- ``groups.member_outside_group_existence``: a membership is valid while the group doesn't
  exist.
- ``groups.leader_not_member`` (off): a leadership overlaps none of the leader's memberships of
  the group (a timeless link overlaps everything; links of different timelines don't).
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.consistency.existence import (
    OPEN_END,
    OPEN_START,
    Requirement,
    Requirements,
    Span,
    dimensions_of,
    live,
    overlapping,
    span,
)
from lore.core.consistency.narrative import links_within, narrative_rule
from lore.core.db import unindexed
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.groups.links import LED_BY, MEMBER_OF

LINK = "link"
_TIMELESS = Span(OPEN_START, OPEN_END)


def _span(row: Any) -> Span:
    _id, _source, _target, timeline_id, from_t, to_t = row
    return _TIMELESS if timeline_id is None else span(LINK, row[0], from_t, to_t)


def _links(ctx: RuleContext, link_type: str, column: Any, ids: list[str] | None) -> list[Any]:
    statement = select(
        Link.id, Link.source_id, Link.target_id, Link.timeline_id, Link.valid_from_t,
        Link.valid_to_t,
    ).where(Link.link_type == link_type, unindexed(Link.deleted_at).is_(None))  # fmt: skip
    if ids is not None:
        statement = statement.where(column.in_(ids))
    return list(ctx.session.execute(statement))


def _leaders(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    ids = None if subjects is None else sorted(subjects)
    leaderships = {
        row[0]: row
        for column in (Link.source_id, Link.target_id)
        for row in _links(ctx, LED_BY, column, ids)
    }
    if not leaderships:
        return
    leaders = sorted({row[2] for row in leaderships.values()})
    memberships: dict[tuple[str, str], list[Any]] = {}
    for row in _links(ctx, MEMBER_OF, Link.source_id, leaders):
        memberships.setdefault((row[1], row[2]), []).append(row)
    names = live(ctx, {i for row in leaderships.values() for i in row[1:3]})
    dimensions = dimensions_of(ctx)
    requirements = Requirements(ctx)
    candidates: list[tuple[str, Requirement, Any]] = []
    for lead in leaderships.values():
        _id, group_id, leader_id, timeline_id = lead[:4]
        if group_id not in names or leader_id not in names:
            continue
        found = [m for m in memberships.get((leader_id, group_id), [])
                 if timeline_id is None or m[3] in (None, timeline_id)]  # fmt: skip
        requirement: Requirement = [overlapping(_span(lead), _span(m)) for m in found]
        timelines = [timeline_id, *(m[3] for m in found)]
        dimension_id = next((dimensions.get(t, "") for t in timelines if t is not None), "")
        if requirements.want(dimension_id, requirement):
            candidates.append((dimension_id, requirement, lead))
    requirements.load()
    for dimension_id, requirement, lead in candidates:
        certainty = requirements.violated(dimension_id, requirement)
        if certainty is not None:
            link_id, group_id, leader_id, timeline_id = lead[:4]
            yield FindingDraft(
                "groups.leader_not_member",
                (leader_id, group_id),
                f"“{names[leader_id]}” leads “{names[group_id]}” without being a member then.",
                certainty=certainty,
                discriminator=link_id,
                timeline_id=timeline_id,
            )


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "groups.member_outside_group_existence",
        "groups",
        "Member outside the group's existence",
        "A membership is valid while the group doesn't exist.",
        links_within(
            "groups.member_outside_group_existence",
            (MEMBER_OF,),
            ("target",),
            lambda member, group, _side: (
                f"“{member}” is a member of “{group}” while it doesn't exist."
            ),
        ),
        triggers=(Trigger("record", "*"), Trigger("link_type", MEMBER_OF)),
    ),
    narrative_rule(
        "groups.leader_not_member",
        "groups",
        "Leader isn't a member",
        "A group's leader has no membership of it overlapping the leadership.",
        _leaders,
        triggers=(Trigger("link_type", LED_BY), Trigger("link_type", MEMBER_OF)),
        severity="off",
    ),
)

__all__ = ["CONSISTENCY_RULES"]
