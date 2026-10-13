"""Time-point field values in propagation (``time-model.md`` §6, ``data-model.md`` §5.6): record
type ``entity_field``, stored in ``entity_time_fields``.

The record id is the entity's id; the slot is the field key (``<key>.<index>`` for each value of
a ``multiple`` field) or ``fact:<fact id>`` for the value of a ``time_point`` fact. An entity's
own values resolve in its home dimension (a multiversal entity's can't: ``unresolved_ref``); a
fact's in its timeline's dimension.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.schema import TimePoint
from lore.core.entities.models import Entity
from lore.core.registry.types import FieldDef
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import EntityTimeField, Timeline
from lore.core.time.slots import (
    SlotDef,
    SlotKey,
    SlotMoment,
    SlotProvider,
    SlotUpdate,
    SlotValue,
    SpecUpdate,
)
from lore.core.time.status import TimeStatus

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

ENTITY_FIELD = "entity_field"
FACT_PREFIX = "fact:"
_BATCH = 500
_STATUSES = {status.value: status for status in TimeStatus}


def fact_slot(fact_id: str) -> str:
    return f"{FACT_PREFIX}{fact_id}"


def field_slots(key: str, value: Any, multiple: bool) -> dict[str, Any]:
    """The slots of a field value: the key, or ``<key>.<index>`` per value of a list."""
    if value is None:
        return {}
    if multiple:
        return {f"{key}.{index}": item for index, item in enumerate(value)}
    return {key: value}


def _rows(session: Session, keys: Sequence[SlotKey]) -> dict[tuple[str, str], EntityTimeField]:
    found: dict[tuple[str, str], EntityTimeField] = {}
    ids = sorted({key.id for key in keys})
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start : start + _BATCH]
        for row in session.scalars(
            select(EntityTimeField).where(EntityTimeField.entity_id.in_(chunk))
        ):
            found[(row.entity_id, row.field_key)] = row
    return found


def _fact_dimensions(session: Session, fact_ids: Sequence[str]) -> dict[str, str]:
    """The dimension of each fact's timeline."""
    from lore.core.facts.models import EntityFact  # noqa: PLC0415 (import cycle)

    if not fact_ids:
        return {}
    rows = session.execute(
        select(EntityFact.id, Timeline.dimension_id)
        .join(Timeline, Timeline.entity_id == EntityFact.timeline_id)
        .where(EntityFact.id.in_(list(fact_ids)))
    )
    return {str(fact_id): str(dimension_id) for fact_id, dimension_id in rows}


def load_field_slots(session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    session.flush()
    rows = _rows(session, keys)
    entities = {
        entity.id: entity
        for entity in session.scalars(
            select(Entity).where(Entity.id.in_(sorted({key.id for key in keys})))
        )
    }
    facts = _fact_dimensions(
        session,
        [key.slot.removeprefix(FACT_PREFIX) for key in keys if key.slot.startswith(FACT_PREFIX)],
    )
    result: dict[SlotKey, SlotValue] = {}
    for key in keys:
        row = rows.get((key.id, key.slot))
        entity = entities.get(key.id)
        if row is None or entity is None:
            continue
        dimension = (
            facts.get(key.slot.removeprefix(FACT_PREFIX))
            if key.slot.startswith(FACT_PREFIX)
            else entity.dimension_id
        )
        result[key] = SlotValue(
            spec=row.spec,
            t=row.t,
            status=None if row.time_status is None else _STATUSES[row.time_status],
            trashed=entity.deleted_at is not None,
            dimension_id=dimension,
        )
    return result


def write_field_slots(session: Session, updates: Sequence[SlotUpdate]) -> None:
    rows = _rows(session, [update.key for update in updates])
    for update in updates:
        row = rows.get((update.key.id, update.key.slot))
        if row is not None:
            row.t = update.t
            row.time_status = update.status.value


def write_field_specs(session: Session, updates: Sequence[SpecUpdate]) -> None:
    """New specs (anchor freezing)."""
    rows = _rows(session, [update.key for update in updates])
    for update in updates:
        row = rows.get((update.key.id, update.key.slot))
        if row is not None and isinstance(update.spec, TimePoint):
            row.spec = update.spec


def field_slot_keys(session: Session) -> list[SlotKey]:
    return [
        SlotKey(entity_id, field_key)
        for entity_id, field_key in session.execute(
            select(EntityTimeField.entity_id, EntityTimeField.field_key)
        )
    ]


def field_moments_beyond(session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
    """Values of the dimension's entities (and of facts in its timelines) resolved after
    ``bound``."""
    from lore.core.facts.models import EntityFact  # noqa: PLC0415 (import cycle)

    found: list[SlotMoment] = []
    rows = session.execute(
        select(EntityTimeField.entity_id, EntityTimeField.field_key, EntityTimeField.t)
        .join(Entity, Entity.id == EntityTimeField.entity_id)
        .where(EntityTimeField.t > bound, Entity.dimension_id == dimension_id)
    )
    found += [
        SlotMoment(ENTITY_FIELD, entity_id, key, t)
        for entity_id, key, t in rows
        if t is not None and not key.startswith(FACT_PREFIX)
    ]
    timelines = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
    facts = {
        fact_slot(str(fact_id))
        for fact_id in session.scalars(
            select(EntityFact.id).where(EntityFact.timeline_id.in_(timelines))
        )
    }
    rows = session.execute(
        select(EntityTimeField.entity_id, EntityTimeField.field_key, EntityTimeField.t).where(
            EntityTimeField.t > bound, EntityTimeField.field_key.startswith(FACT_PREFIX)
        )
    )
    found += [
        SlotMoment(ENTITY_FIELD, e, key, t) for e, key, t in rows if t is not None and key in facts
    ]
    return found


ENTITY_FIELD_SLOTS = SlotProvider(
    ENTITY_FIELD,
    EntityTimeField,
    (SlotDef("*"),),
    id_column="entity_id",
    entity_column="entity_id",
    load=load_field_slots,
    write=write_field_slots,
    write_spec=write_field_specs,
    keys=field_slot_keys,
    beyond=field_moments_beyond,
)


def stored_values(session: Session, entity_id: str) -> dict[str, EntityTimeField]:
    """The entity's rows, by slot."""
    return {
        row.field_key: row
        for row in session.scalars(
            select(EntityTimeField).where(EntityTimeField.entity_id == entity_id)
        )
    }


def sync_rows(
    session: Session, entity_id: str, wanted: Mapping[str, TimePoint], *, prefix_filter: Any
) -> list[tuple[str, TimePoint | None]]:
    """Make the entity's rows selected by ``prefix_filter(slot)`` hold exactly ``wanted``
    (slot → spec). Returns the slots whose spec changed (``None``: removed), for the caller's
    ``TimeWriter``."""
    stored = {
        slot: row for slot, row in stored_values(session, entity_id).items() if prefix_filter(slot)
    }
    changed: list[tuple[str, TimePoint | None]] = []
    for slot, row in stored.items():
        if slot not in wanted:
            session.delete(row)
            changed.append((slot, None))
    for slot, spec in wanted.items():
        existing = stored.get(slot)
        if existing is None:
            session.add(EntityTimeField(entity_id=entity_id, field_key=slot, spec=spec))
            changed.append((slot, spec))
        elif existing.spec != spec:
            existing.spec = spec
            changed.append((slot, spec))
    session.flush()
    return changed


def _base_key(slot: str) -> str:
    """The field key of an own-value slot (``custom.dates.1`` → ``custom.dates``)."""
    head, _, tail = slot.rpartition(".")
    return head if head and tail.isdigit() else slot


def write_time_fields(
    context: VaultContext,
    entity: Entity,
    active: Mapping[str, FieldDef],
    *,
    touch: bool = False,
    strict: bool = True,
) -> None:
    """Keep the entity's ``entity_time_fields`` rows in step with its ``time_point`` field
    values, and propagate what changed (``touch``: resolve them all again, after the entity
    moved to another dimension). Rows of fields the kind doesn't offer now (archived, disabled
    module) are left as they are. A multiversal entity's values are stored without a moment.
    ``strict=False``: values that don't resolve keep a status
    instead of refusing the write."""
    from lore.core.time.propagate import TimeWriter  # noqa: PLC0415 (import cycle)

    keys = {key for key, field in active.items() if field.type == "time_point"}
    wanted: dict[str, TimePoint] = {}
    for key in sorted(keys):
        slots = field_slots(key, entity.fields.get(key), active[key].multiple)
        wanted.update({slot: TimePoint.model_validate(value) for slot, value in slots.items()})
    changed = sync_rows(
        context.session,
        entity.id,
        wanted,
        prefix_filter=lambda slot: not slot.startswith(FACT_PREFIX) and _base_key(slot) in keys,
    )
    if not changed and not (touch and wanted):
        return
    writer = TimeWriter(context)
    if entity.dimension_id is None:
        # A multiversal entity's own values have no dimension to resolve in: they are kept
        # (with no moment) and depend on nothing.
        for slot in {slot for slot, _spec in changed} | (set(wanted) if touch else set()):
            writer.index.replace_edges(SlotNode(ENTITY_FIELD, entity.id, slot), set())
        return
    if touch:  # from another dimension (or none): every value's edges and moment are new
        changed = sorted({*changed, *wanted.items()}, key=lambda item: item[0])
    for slot, spec in changed:
        writer.set_spec(ENTITY_FIELD, entity.id, slot, spec)
    writer.propagate(path="fields", strict=strict)
