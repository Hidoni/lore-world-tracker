"""As-of state (``time-model.md`` §10.4-§10.5): what was true of entities at moment ``t`` in
timeline ``T``.

    reader = StateReader(context, policy, timeline_id, t)
    states = reader.states(entities)        # one query for all their facts
    states[entity.id].existence             # exists | not_exists | unknown | possible

Facts are read through ``TimelineView`` (lineage, overrides) and the request's policy. A fact
covers ``t`` when ``valid_from <= t < valid_to`` (open bounds are unbounded). When ``t`` lies
inside the uncertainty extent of a bound (a bound given at year precision covers a whole year),
the fact covers it only **possibly**; exact bounds (``base`` precision) are certain.

- Existence: no visible ``core.exists`` fact in ``T`` is ``unknown``; else ``exists`` when one
  covers ``t`` certainly, ``possible`` when one covers it possibly, ``not_exists`` otherwise.
- Name: the covering ``core.name`` fact with the latest start, else the entity's name.
- Fields: the covering facts of each key, latest start first (open starts are earliest);
  ``lore.core.facts.state`` turns them into field values (it knows the field definitions).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from lore.core.entities.models import Entity
from lore.core.facts.models import EntityFact
from lore.core.facts.schemas import EXISTS, NAME
from lore.core.modules.spec import VaultContext
from lore.core.time.dependencies import SlotNode
from lore.core.time.models import Dimension, Timeline
from lore.core.time.resolve import Resolver
from lore.core.time.timeline_view import Conditions, RowFilter, TimelineView
from lore.core.types import Certainty, Existence
from lore.core.visibility import VisibilityPolicy

FACT = "fact"
_BATCH = 500


@dataclass(frozen=True)
class Cover:
    """A fact covering ``t``, certainly or possibly."""

    fact: EntityFact
    certainty: Certainty


@dataclass
class EntityState:
    """An entity's existence and name at ``t``, and the facts covering ``t`` by field key (latest
    start first). Fields are assembled by the caller, which knows their definitions."""

    existence: Existence
    name: str
    name_certainty: Certainty = "certain"
    name_fact_id: str | None = None
    existence_fact_ids: list[str] = field(default_factory=list)
    covers: dict[str, list[Cover]] = field(default_factory=dict)


def present_of(context: VaultContext, timeline_id: str) -> int | None:
    """The present moment of the timeline's dimension (``None``: not set)."""
    dimension_id = context.session.scalar(
        select(Timeline.dimension_id).where(Timeline.entity_id == timeline_id)
    )
    if dimension_id is None:
        return None
    row = context.session.get(Dimension, dimension_id)
    return None if row is None else row.present_t


class StateReader:
    """As-of state in one timeline at one moment, for one request's policy."""

    def __init__(
        self, context: VaultContext, policy: VisibilityPolicy, timeline_id: str, t: int
    ) -> None:
        self.context = context
        self.session = context.session
        self.policy = policy
        self.timeline_id = timeline_id
        self.t = t
        self.view = TimelineView.for_timeline(self.session, timeline_id)
        dimension_id = self.session.scalar(
            select(Timeline.dimension_id).where(Timeline.entity_id == timeline_id)
        )
        self.resolver = (
            None
            if dimension_id is None
            else Resolver(context, str(dimension_id), timeline_id, policy)
        )

    def facts(
        self, entity_ids: Sequence[str], *, keys: Sequence[str] | None = None
    ) -> dict[str, list[EntityFact]]:
        """The live facts of these entities that the timeline and the policy show (of the field
        ``keys`` only, when given)."""
        found: dict[str, list[EntityFact]] = defaultdict(list)
        for start in range(0, len(entity_ids), _BATCH):
            chunk = list(entity_ids[start : start + _BATCH])
            statement = self.view.select(EntityFact, where=self._fact_filter(chunk, keys))
            for fact in self.session.scalars(statement):
                found[fact.entity_id].append(fact)
        return found

    def _fact_filter(self, entity_ids: list[str], keys: Sequence[str] | None) -> RowFilter:
        def where(row: Any) -> Conditions:
            conditions: Conditions = [
                row.deleted_at.is_(None),
                row.entity_id.in_(entity_ids),
                *self.policy.rows(row),
                *self.policy.entity_ref(row.timeline_id),
            ]
            if keys is not None:
                conditions.append(row.field_key.in_(keys))
            return conditions

        return where

    def _extents(self, facts: Iterable[EntityFact]) -> dict[tuple[str, str], tuple[int, int]]:
        """The uncertainty extents of the bounds given at a coarser precision than base."""
        wanted = [
            SlotNode(FACT, fact.id, slot)
            for fact in facts
            for slot, spec, t in (
                ("valid_from", fact.valid_from_spec, fact.valid_from_t),
                ("valid_to", fact.valid_to_spec, fact.valid_to_t),
            )
            if spec is not None and t is not None and spec.precision != "base"
        ]
        if not wanted or self.resolver is None:
            return {}
        self.resolver.preload(wanted)
        extents: dict[tuple[str, str], tuple[int, int]] = {}
        for node in wanted:
            resolution = self.resolver.slot(FACT, node.id, node.slot)
            if resolution.extent is not None and resolution.extent[1] - resolution.extent[0] > 1:
                extents[(node.id, node.slot)] = resolution.extent
        return extents

    def _cover(
        self, fact: EntityFact, extents: dict[tuple[str, str], tuple[int, int]]
    ) -> Certainty | None:
        """Whether the fact covers ``t``: certainly, possibly, or not (``None``). An exact bound
        is a moment; a coarser one may lie anywhere in its extent ``[lo, hi)``."""
        t, possible = self.t, False
        if fact.valid_from_t is not None:
            lo, hi = extents.get(
                (fact.id, "valid_from"), (fact.valid_from_t, fact.valid_from_t + 1)
            )
            if t < lo:
                return None
            possible = t < hi - 1  # the start may still lie ahead (never for an exact bound)
        if fact.valid_to_t is not None:
            lo, hi = extents.get((fact.id, "valid_to"), (fact.valid_to_t, fact.valid_to_t + 1))
            if t >= hi - 1:
                return None  # the end is at or before t whatever moment it is
            possible = possible or t >= lo
        return "possible" if possible else "certain"

    def existence(self, entities: Sequence[Entity]) -> dict[str, Existence]:
        """Only the existence of each entity (for lists: reads only ``core.exists`` facts)."""
        return {key: state.existence for key, state in self.states(entities, keys=[EXISTS]).items()}

    def states(
        self, entities: Sequence[Entity], *, keys: Sequence[str] | None = None
    ) -> dict[str, EntityState]:
        """The state of each entity at ``t``: one query for all their facts (of ``keys`` only,
        when given)."""
        facts = self.facts([e.id for e in entities], keys=keys)
        extents = self._extents(f for found in facts.values() for f in found)
        result: dict[str, EntityState] = {}
        for entity in entities:
            covering: dict[str, list[Cover]] = defaultdict(list)
            has_existence = False
            for fact in facts.get(entity.id, []):
                if fact.field_key == EXISTS:
                    has_existence = True
                certainty = self._cover(fact, extents)
                if certainty is not None:
                    covering[fact.field_key].append(Cover(fact, certainty))
            result[entity.id] = self._state(entity, covering, has_existence)
        return result

    def _state(
        self, entity: Entity, covering: dict[str, list[Cover]], has_existence: bool
    ) -> EntityState:
        exists = covering.pop(EXISTS, [])
        existence: Existence
        if not has_existence:
            existence = "unknown"
        elif any(c.certainty == "certain" for c in exists):
            existence = "exists"
        elif exists:
            existence = "possible"
        else:
            existence = "not_exists"
        state = EntityState(existence=existence, name=entity.name)
        state.existence_fact_ids = [c.fact.id for c in _latest(exists)]
        names = _latest(covering.pop(NAME, []))
        if names:
            chosen = names[0]
            state.name = str(chosen.fact.value)
            state.name_certainty = chosen.certainty
            state.name_fact_id = chosen.fact.id
        state.covers = {key: _latest(covers) for key, covers in covering.items()}
        return state


def _latest(covers: list[Cover]) -> list[Cover]:
    """Latest start first (open starts are earliest), then the latest created."""
    return sorted(
        covers,
        key=lambda c: (
            c.fact.valid_from_t is not None,
            c.fact.valid_from_t or 0,
            c.fact.created_at,
            c.fact.id,
        ),
        reverse=True,
    )
