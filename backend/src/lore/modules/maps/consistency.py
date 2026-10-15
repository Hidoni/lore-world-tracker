"""The maps module's consistency rules (``docs/modules/maps.md``):

- ``maps.pin_target_missing`` (warning): a live pin whose target is in the trash, or private
  while the pin and its map aren't (readers lose the pin).
- ``maps.pin_outside_map_location`` (off): a pinned location that isn't the map's location or
  inside it (its parent chain).
"""

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import or_, select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.entities.models import Entity
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.maps.models import Map, MapPin

MISSING = "maps.pin_target_missing"
OUTSIDE = "maps.pin_outside_map_location"
LOCATION = "location"
_BATCH = 5000


def _pins(ctx: RuleContext, subjects: Iterable[str] | None) -> list[Any]:
    """``(pin, map)`` of the live pins with a target: those of the subjects (as target or map
    location), or all."""
    statement = (
        select(MapPin, Map)
        .join(Map, Map.id == MapPin.map_id)
        .where(
            MapPin.deleted_at.is_(None),
            MapPin.overrides_id.is_(None),
            MapPin.target_entity_id.is_not(None),
            Map.deleted_at.is_(None),
        )
        .order_by(MapPin.id)
    )
    if subjects is None:
        return list(ctx.session.execute(statement).all())
    wanted = sorted(set(subjects))
    found: list[Any] = []
    for start in range(0, len(wanted), _BATCH):
        chunk = wanted[start : start + _BATCH]
        found += ctx.session.execute(
            statement.where(or_(MapPin.target_entity_id.in_(chunk), Map.location_id.in_(chunk)))
        ).all()
    return found


def _entities(ctx: RuleContext, ids: Iterable[str]) -> dict[str, Entity]:
    wanted = sorted(set(ids))
    return {e.id: e for e in ctx.session.scalars(select(Entity).where(Entity.id.in_(wanted)))}


def _missing(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    rows = _pins(ctx, subjects)
    entities = _entities(ctx, (p.target_entity_id for p, _ in rows))
    for pin, map_row in rows:
        target = entities.get(pin.target_entity_id)
        if target is None:
            continue
        trashed = target.deleted_at is not None
        hidden = (
            target.visibility == "private"
            and pin.visibility != "private"
            and map_row.visibility != "private"
        )
        if not trashed and not hidden:
            continue
        why = "is in the trash" if trashed else "is private, so readers don't see the pin"
        yield FindingDraft(
            MISSING,
            (map_row.location_id, target.id),
            f"A pin on the map “{map_row.name}” points to “{target.name}”, which {why}.",
            discriminator=pin.id,
            data={"pin_id": pin.id, "map_id": map_row.id},
        )


def _ancestors(ctx: RuleContext, entity: Entity) -> set[str]:
    chain: set[str] = set()
    current: Entity | None = entity
    while current is not None and current.parent_id and current.parent_id not in chain:
        chain.add(current.parent_id)
        current = ctx.session.get(Entity, current.parent_id)
    return chain


def _outside(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    rows = _pins(ctx, subjects)
    entities = _entities(ctx, (p.target_entity_id for p, _ in rows))
    for pin, map_row in rows:
        target = entities.get(pin.target_entity_id)
        if target is None or target.kind != LOCATION or target.deleted_at is not None:
            continue
        if target.id == map_row.location_id or map_row.location_id in _ancestors(ctx, target):
            continue
        yield FindingDraft(
            OUTSIDE,
            (map_row.location_id, target.id),
            f"“{target.name}” is pinned on the map “{map_row.name}” but isn't inside its location.",
            discriminator=pin.id,
            data={"pin_id": pin.id, "map_id": map_row.id},
        )


TRIGGERS = (Trigger("record", "*"),)

CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    RuleDef(
        id=MISSING,
        owner="maps",
        title="Pin target missing",
        description="A pin points to an entity in the trash, or to a private one on a map "
        "readers see.",
        category="structural",
        default_severity="warning",
        configurable=True,
        triggers=TRIGGERS,
        check=_missing,
        scan=lambda ctx: _missing(ctx, None),
    ),
    RuleDef(
        id=OUTSIDE,
        owner="maps",
        title="Pinned location outside the map",
        description="A location is pinned on a map of a place it doesn't belong to.",
        category="structural",
        default_severity="off",
        configurable=True,
        triggers=TRIGGERS,
        check=_outside,
        scan=lambda ctx: _outside(ctx, None),
    ),
)
