"""The characters module's consistency rules (``docs/modules/characters.md``).

- ``characters.parent_born_after_child``: a parent's existence starts after their child's (in a
  timeline both have existence periods in).
- ``characters.concurrent_spouses`` (off): two spouse links of a character, to different spouses,
  overlap (a timeless link overlaps everything; links of different timelines don't).
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.consistency.existence import (
    OPEN_END,
    OPEN_START,
    Existences,
    Requirement,
    Requirements,
    Span,
    chunks,
    dimensions_of,
    disjoint,
    live,
    span,
    with_existence,
)
from lore.core.consistency.narrative import links_of, narrative_rule
from lore.core.db import unindexed
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.characters.links import PARENT_OF, SPOUSE_OF

LINK = "link"
_TIMELESS = Span(OPEN_START, OPEN_END)


def _parents(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    scope = with_existence(ctx) if subjects is None else subjects  # both need existence periods
    pairs = list(dict.fromkeys(links_of(ctx, scope, PARENT_OF)))
    names = live(ctx, {i for pair in pairs for i in pair})
    pairs = [(p, c) for p, c in pairs if p in names and c in names]
    existences = Existences(ctx)
    existences.load(i for pair in pairs for i in pair)
    dimensions = dimensions_of(ctx)
    requirements = Requirements(ctx)
    candidates: list[tuple[str, Requirement, str, str, str]] = []
    for parent_id, child_id in pairs:
        shared = set(existences.timelines(parent_id)) & set(existences.timelines(child_id))
        for timeline_id in sorted(shared):
            parent = existences.periods(parent_id, timeline_id) or []
            child = existences.periods(child_id, timeline_id) or []
            dimension_id = dimensions.get(timeline_id)
            if not parent or not child or dimension_id is None or child[0].start is OPEN_START:
                continue
            requirement: Requirement = [[(parent[0].start, child[0].start)]]
            if requirements.want(dimension_id, requirement):
                candidates.append((dimension_id, requirement, parent_id, child_id, timeline_id))
    requirements.load()
    for dimension_id, requirement, parent_id, child_id, timeline_id in candidates:
        certainty = requirements.violated(dimension_id, requirement)
        if certainty is not None:
            yield FindingDraft(
                "characters.parent_born_after_child",
                (parent_id, child_id),
                f"“{names[parent_id]}” starts existing after their child “{names[child_id]}”.",
                certainty=certainty,
                discriminator=timeline_id,
                timeline_id=timeline_id,
            )


def _spouse_links(ctx: RuleContext, people: list[str] | None) -> list[Any]:
    statement = select(
        Link.id, Link.source_id, Link.target_id, Link.timeline_id, Link.valid_from_t,
        Link.valid_to_t,
    ).where(Link.link_type == SPOUSE_OF, unindexed(Link.deleted_at).is_(None))  # fmt: skip
    if people is None:
        return list(ctx.session.execute(statement))
    found: dict[str, Any] = {}
    for batch in chunks(people):
        for column in (Link.source_id, Link.target_id):
            for row in ctx.session.execute(statement.where(column.in_(batch))):
                found[row[0]] = row
    return list(found.values())


def _spouses(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    if subjects is None:
        links = _spouse_links(ctx, None)
    else:
        # The subjects' spouses' other marriages are theirs too (a finding names all three).
        near = {i for row in _spouse_links(ctx, sorted(subjects)) for i in row[1:3]}
        links = _spouse_links(ctx, sorted(near | subjects))
    names = live(ctx, {i for row in links for i in row[1:3]})
    by_person: dict[str, list[tuple[str, Any]]] = {}
    for row in links:
        _id, source_id, target_id = row[:3]
        if source_id in names and target_id in names:
            by_person.setdefault(source_id, []).append((target_id, row))
            by_person.setdefault(target_id, []).append((source_id, row))
    dimensions = dimensions_of(ctx)
    requirements = Requirements(ctx)
    candidates: list[tuple[str, Requirement, str, Any, Any]] = []
    for person, married in by_person.items():
        married.sort(key=lambda item: item[1][0])
        for index, (spouse, a) in enumerate(married):
            for other, b in married[index + 1 :]:
                if spouse == other or (None not in (a[3], b[3]) and a[3] != b[3]):
                    continue
                timeline_id = a[3] or b[3]
                spans = [_TIMELESS if r[3] is None else span(LINK, r[0], r[4], r[5])
                         for r in (a, b)]  # fmt: skip
                requirement = disjoint(*spans)
                dimension_id = "" if timeline_id is None else dimensions.get(timeline_id, "")
                if requirements.want(dimension_id, requirement):
                    candidates.append((dimension_id, requirement, person, (spouse, a), (other, b)))
    requirements.load()
    for dimension_id, requirement, person, (spouse, a), (other, b) in candidates:
        if subjects is not None and not {person, spouse, other} & subjects:
            continue
        certainty = requirements.violated(dimension_id, requirement)
        if certainty is not None:
            yield FindingDraft(
                "characters.concurrent_spouses",
                (person, spouse, other),
                f"“{names[person]}” has two spouses at once: “{names[spouse]}” and "
                f"“{names[other]}”.",
                certainty=certainty,
                discriminator=f"{a[0]}:{b[0]}",
                timeline_id=a[3] or b[3],
            )


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "characters.parent_born_after_child",
        "characters",
        "Parent born after child",
        "A parent's existence starts after their child's.",
        _parents,
        triggers=(Trigger("record", "*"), Trigger("link_type", PARENT_OF)),
    ),
    narrative_rule(
        "characters.concurrent_spouses",
        "characters",
        "Concurrent spouses",
        "A character has spouse links to different people valid at the same time.",
        _spouses,
        triggers=(Trigger("link_type", SPOUSE_OF),),
        severity="off",
    ),
)

__all__ = ["CONSISTENCY_RULES"]
