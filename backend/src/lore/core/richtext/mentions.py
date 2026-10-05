"""Maintains ``mentions`` (derived, ``data-model.md`` §6.4): rebuilt for an entity from its body and
its ``rich_text`` field values whenever they change (and after an undo). Mentions of the entity
itself and of entities that don't exist are not recorded (decided 2026-10-04)."""

from collections.abc import Iterable, Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lore.core.db.base import Visibility
from lore.core.entities.models import Entity
from lore.core.richtext.extract import MentionCounts, extract
from lore.core.richtext.handlers import Node, RichTextNodeHandler
from lore.core.richtext.models import Mention


def count_mentions(
    documents: Iterable[tuple[Node | None, Visibility]],
    handlers: Mapping[str, RichTextNodeHandler],
) -> dict[str, MentionCounts]:
    totals: dict[str, MentionCounts] = {}
    for doc, visibility in documents:
        for target, counts in extract(doc, handlers, visibility=visibility).mentions.items():
            total = totals.setdefault(target, MentionCounts())
            total.public += counts.public
            total.spoiler += counts.spoiler
            total.private += counts.private
    return totals


def mention_rows(
    session: Session, source_id: str, counts: Mapping[str, MentionCounts]
) -> dict[str, MentionCounts]:
    """The ``mentions`` rows these counts make: targets other than the source that exist."""
    targets = set(counts) - {source_id}
    existing = set(session.scalars(select(Entity.id).where(Entity.id.in_(targets))))
    return {target: counts[target] for target in sorted(existing)}


def replace_mentions(session: Session, source_id: str, counts: Mapping[str, MentionCounts]) -> None:
    session.execute(delete(Mention).where(Mention.source_entity_id == source_id))
    for target, c in mention_rows(session, source_id, counts).items():
        session.add(
            Mention(
                source_entity_id=source_id,
                target_entity_id=target,
                count_public=c.public,
                count_spoiler=c.spoiler,
                count_private=c.private,
            )
        )
    session.flush()
