"""The facts' purge hook (runs after anchor freezing, which reads the entity's facts)."""

from typing import Any

from sqlalchemy import select

from lore.core.facts.models import EntityFact
from lore.core.time.models import EntityTimeField


def purge_facts(context: Any, entity: Any) -> None:
    """Before an entity is purged: its facts and time-field values go with it, and other facts
    citing it as their source event forget it."""
    session = context.session
    for fact in session.scalars(select(EntityFact).where(EntityFact.entity_id == entity.id)):
        session.delete(fact)
    for row in session.scalars(
        select(EntityTimeField).where(EntityTimeField.entity_id == entity.id)
    ):
        session.delete(row)
    for fact in session.scalars(select(EntityFact).where(EntityFact.source_event_id == entity.id)):
        fact.source_event_id = None
    session.flush()
