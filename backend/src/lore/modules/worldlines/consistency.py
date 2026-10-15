"""The worldlines module's consistency rules (``docs/modules/worldlines.md``, ``time-model.md``
§11.4). Both look at entities with explicit segments only (an implicit worldline is the
existence, which ``core.event.participant_not_existing`` checks):

- ``worldlines.absent_participant`` (warning): no segment covers the event's start in a timeline
  that sees it (or the segment the link chose doesn't).
- ``worldlines.ambiguous_participation`` (warning): several segments cover it and the link
  doesn't choose one (``data.segment_id``).
"""

from collections.abc import Callable, Iterable, Iterator

from sqlalchemy import select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.models import WorldlineSegment
from lore.core.visibility import AUTHOR
from lore.modules.worldlines.service import Worldlines

ABSENT = "worldlines.absent_participant"
AMBIGUOUS = "worldlines.ambiguous_participation"
PARTICIPANT = "core.participant"


def _travelers(ctx: RuleContext, subjects: Iterable[str] | None) -> list[str]:
    """Entities with explicit segments among the subjects (or the participants of subject
    events); all of them without subjects."""
    with_segments = select(WorldlineSegment.entity_id).distinct()
    if subjects is None:
        return sorted(ctx.session.scalars(with_segments))
    wanted = set(subjects)
    wanted |= set(
        ctx.session.scalars(
            select(Link.target_id).where(
                Link.source_id.in_(sorted(wanted)),
                Link.link_type == PARTICIPANT,
                unindexed(Link.deleted_at).is_(None),
            )
        )
    )
    return sorted(
        ctx.session.scalars(with_segments.where(WorldlineSegment.entity_id.in_(sorted(wanted))))
    )


def _findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    service = Worldlines(ctx.context, AUTHOR)
    for entity_id in _travelers(ctx, subjects):
        entity = ctx.session.get(Entity, entity_id)
        if entity is None or entity.deleted_at is not None:
            continue
        lived = service.lived(entity)
        if lived.implicit:
            continue
        for participation in service.participations(lived):
            event = participation.event
            if participation.assignment == "absent":
                chosen = isinstance((participation.link.data or {}).get("segment_id"), str)
                yield FindingDraft(
                    ABSENT,
                    (entity.id, event.id),
                    f"“{entity.name}” takes part in “{event.name}”, but "
                    + ("the visit chosen for it doesn't cover the event."
                       if chosen else "isn't there then in any part of their worldline."),
                    discriminator=participation.link.id,
                    timeline_id=participation.timeline_id,
                    data={"link_id": participation.link.id},
                )  # fmt: skip
            elif participation.assignment == "ambiguous":
                ids = [lived.spans[i].id for i in participation.covering]
                yield FindingDraft(
                    AMBIGUOUS,
                    (entity.id, event.id),
                    f"“{entity.name}” is there {len(ids)} times when “{event.name}” happens: "
                    "choose which visit takes part in it.",
                    discriminator=participation.link.id,
                    timeline_id=participation.timeline_id,
                    data={"link_id": participation.link.id, "segment_ids": ids},
                )


type Check = Callable[[RuleContext, Iterable[str] | None], Iterator[FindingDraft]]


def _check(rule_id: str) -> Check:
    def check(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
        return (f for f in _findings(ctx, subjects) if f.rule_id == rule_id)

    return check


TRIGGERS = (Trigger("record", "*"), Trigger("link_type", PARTICIPANT))

CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    RuleDef(
        id=ABSENT,
        owner="worldlines",
        title="Participant isn't there",
        description="An entity with a worldline takes part in an event that none of its "
        "segments covers (or the chosen visit doesn't). Change its worldline, the event or the "
        "participation.",
        category="advanced_time",
        default_severity="warning",
        configurable=True,
        triggers=TRIGGERS,
        check=_check(ABSENT),
        scan=lambda ctx: _check(ABSENT)(ctx, None),
    ),
    RuleDef(
        id=AMBIGUOUS,
        owner="worldlines",
        title="Which visit takes part?",
        description="A time traveler is present more than once when an event happens, and the "
        "participation doesn't say which visit takes part in it.",
        category="advanced_time",
        default_severity="warning",
        configurable=True,
        triggers=TRIGGERS,
        check=_check(AMBIGUOUS),
        scan=lambda ctx: _check(AMBIGUOUS)(ctx, None),
    ),
)
