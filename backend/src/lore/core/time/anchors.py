"""Where a time point's anchors live: records that must stay in one dimension (sync points,
worldline segments) refuse an anchor to another dimension's records, which would otherwise
resolve without complaint (an absolute moment means nothing across dimensions)."""

from typing import Any

from lore.core.entities.models import Entity
from lore.core.modules.spec import VaultContext
from lore.core.time.dependencies import (
    CalendarNode,
    DimensionNode,
    SlotNode,
    Target,
    time_point_targets,
)
from lore.core.time.slots import SlotError, SlotKey


def target_dimension(context: VaultContext, target: Target) -> str | None:
    """The dimension of an anchor's target (``None``: unknown, e.g. a missing record)."""
    session = context.session
    match target:
        case SlotNode():
            key = SlotKey(target.id, target.slot)
            try:
                found = context.registry.slot_registry().load(session, target.type, [key])
            except SlotError:
                return None
            value = found.get(key)
            return None if value is None else value.dimension_id
        case CalendarNode():
            calendar = session.get(Entity, target.calendar_id)
            return None if calendar is None else calendar.dimension_id
        case DimensionNode():
            return target.dimension_id
    return None


def anchored_elsewhere(context: VaultContext, spec: Any, dimension_id: str) -> bool:
    """Whether a time point (or end spec) is anchored to a record of another dimension."""
    for target in time_point_targets(spec):
        found = target_dimension(context, target)
        if found is not None and found != dimension_id:
            return True
    return False


__all__ = ["anchored_elsewhere", "target_dimension"]
