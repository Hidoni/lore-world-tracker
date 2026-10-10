"""What a transaction's writes changed in time, for ``affected`` (``frontend.md`` §5.1).

Time writes propagate (``time-model.md`` §7.2): moving an event moves everything anchored to it
in the same transaction. Clients invalidate their caches from a write's ``affected``, so it has
to name those records too. Every propagation notes the slots whose stored moment or status it
changed (``Propagation.updated``) in the session, and services note the moments they store
themselves (a dimension's present, a series' bounds); ``report`` adds their entities and
dimensions to an ``Affected`` and sets ``time_changed``. The notes last for the transaction.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from lore.core.db.types import SortableBigInt
from lore.core.entities.models import Entity
from lore.core.time.dependencies import SlotNode
from lore.core.time.slots import SlotRegistry
from lore.core.types import Affected

if TYPE_CHECKING:
    from lore.core.modules.registry import ModuleRegistry

_CHANGES = "lore_time_changes"  # session.info
CALENDAR = "calendar"  # its record id is the calendar's entity id
DIMENSION = "dimension"
BATCH = 5000  # ids per query (SQLite's variable limit)


@dataclass
class TimeChanges:
    """The slots and entities whose stored moments or statuses a transaction changed."""

    slots: set[SlotNode] = field(default_factory=set)
    entities: set[str] = field(default_factory=set)
    reverted: bool = False
    """An undo put back rows with other moments (their entities are the undo's own)."""


def _changes(session: Session) -> TimeChanges:
    changes: TimeChanges | None = session.info.get(_CHANGES)
    if changes is None:
        changes = session.info[_CHANGES] = TimeChanges()
    return changes


def _forget(session: Session) -> None:
    session.info.pop(_CHANGES, None)


event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)


def note_slots(session: Session, nodes: Iterable[SlotNode]) -> None:
    """Slots whose stored moment or status changed (a propagation's ``updated``)."""
    _changes(session).slots.update(nodes)


def note_entities(session: Session, entity_ids: Iterable[str]) -> None:
    """Entities whose moments a service stored itself, outside propagation."""
    _changes(session).entities.update(entity_ids)


def note_reverted(session: Session, registry: SlotRegistry, changes: Sequence[Any]) -> None:
    """An undo wrote rows back (``history.service``): time changed when a reverted row of a
    time-bearing table differs in a moment or status column."""
    columns: dict[str, list[str]] = {}
    for provider in registry.providers:
        table = getattr(provider.model, "__table__", None)
        if table is None:
            continue
        names = {c.name for c in table.columns if isinstance(c.type, SortableBigInt)}
        names |= {s.status_column for s in provider.slots if s.status_column in table.columns}
        columns[table.name] = sorted(names)
    for change in changes:
        wanted = columns.get(change.table_name)
        if wanted and _values(change.before, wanted) != _values(change.after, wanted):
            _changes(session).reverted = True
            return


def _values(row: Mapping[str, Any] | None, columns: Sequence[str]) -> list[Any]:
    return [None if row is None else row.get(column) for column in columns]


def moved_entities(session: Session, registry: SlotRegistry) -> list[str]:
    """The entities of the noted slots (through their providers' ``entity_column``; records
    without an entity, such as link rows, have none) and the noted entities, sorted."""
    changes: TimeChanges | None = session.info.get(_CHANGES)
    if changes is None:
        return []
    found = set(changes.entities)
    by_type: dict[str, set[str]] = {}
    for node in changes.slots:
        by_type.setdefault(node.type, set()).add(node.id)
    for record_type, ids in by_type.items():
        provider = registry.get(record_type)
        if provider is None:
            continue
        if record_type == CALENDAR or provider.entity_column == provider.id_column:
            found.update(ids)
            continue
        if provider.entity_column is None:
            continue
        model: Any = provider.model
        id_column = getattr(model, provider.id_column)
        entity_column = getattr(model, provider.entity_column)
        wanted = sorted(ids)
        for start in range(0, len(wanted), BATCH):
            rows: Iterable[Any] = session.scalars(
                select(entity_column).where(id_column.in_(wanted[start : start + BATCH]))
            )
            found.update(str(entity_id) for entity_id in rows if entity_id is not None)
    return sorted(found)


def report(session: Session, registry: ModuleRegistry, affected: Affected) -> Affected:
    """``affected`` with what the transaction's time writes changed so far: the entities whose
    moments or statuses changed, their dimensions, and ``time_changed``."""
    changes: TimeChanges | None = session.info.get(_CHANGES)
    if changes is None:
        return affected
    moved = moved_entities(session, registry.slot_registry())
    if not moved:
        return affected.model_copy(update={"time_changed": True}) if changes.reverted else affected
    dimensions: set[str] = set()
    for start in range(0, len(moved), BATCH):
        rows = session.execute(
            select(Entity.id, Entity.kind, Entity.dimension_id).where(
                Entity.id.in_(moved[start : start + BATCH])
            )
        )
        for entity_id, kind, dimension_id in rows:
            if dimension_id is not None:
                dimensions.add(dimension_id)
            elif kind == DIMENSION:
                dimensions.add(entity_id)
    return affected.model_copy(
        update={
            "entities": list(dict.fromkeys([*affected.entities, *moved])),
            "dimensions": list(dict.fromkeys([*affected.dimensions, *sorted(dimensions)])),
            "time_changed": True,
        }
    )


__all__ = [
    "TimeChanges",
    "moved_entities",
    "note_entities",
    "note_reverted",
    "note_slots",
    "report",
]
