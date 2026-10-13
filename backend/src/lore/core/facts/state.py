"""As-of state for the API (``time-model.md`` §10.5): an entity's existence, name and temporal
fields at a moment in a timeline, as the request's policy may see them.

``lore.core.time.state.StateReader`` finds the facts covering the moment; this module knows the
field definitions: a single-valued field takes the covering fact with the latest start (flagged
``ambiguous`` when several cover), a ``multiple`` field joins the values of every covering fact,
and a field without one falls back to the entity's static value. Facts of fields the policy
hides are left out; for readers, values are redacted like fact values (``facts.service``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from lore.core.entities.models import Entity
from lore.core.entities.queries import ExistenceOf
from lore.core.entities.schemas import EntityStateOut, FieldStateOut
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef
from lore.core.time.dimensions import prime_timeline
from lore.core.time.models import Timeline
from lore.core.time.redact import ReaderTimes
from lore.core.time.state import Cover, EntityState, StateReader, present_of
from lore.core.visibility import AUTHOR, VisibilityPolicy

PRESENT = "present"


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(
        message, errors=[ErrorItem(path=path, code="invalid_value", message=message)]
    )


@dataclass
class AsOf:
    """A resolved ``(timeline, at)`` pair of a request."""

    timeline_id: str
    dimension_id: str
    t: int


def resolve_as_of(
    context: VaultContext, policy: VisibilityPolicy, timeline_id: str, at: str
) -> AsOf:
    """The timeline (a live one the policy shows, else ``404``) and the moment: a decimal moment,
    or ``present`` for its dimension's present (``422`` when the dimension has none)."""
    session = context.session
    row = session.get(Timeline, timeline_id)
    entity = session.get(Entity, timeline_id)
    if (
        row is None
        or entity is None
        or entity.deleted_at is not None
        or timeline_id not in policy.visible_ids(session, [timeline_id])
    ):
        raise NotFoundError(f"No timeline {timeline_id}.")
    if at == PRESENT:
        t = present_of(context, timeline_id)
        if t is None:
            raise _invalid("at", "The timeline's dimension has no present moment.")
    else:
        t = int(at)
    return AsOf(timeline_id, row.dimension_id, t)


@dataclass
class EntityStates:
    context: VaultContext
    policy: VisibilityPolicy = AUTHOR

    def __post_init__(self) -> None:
        self.session = self.context.session
        self.entities = EntityService(self.context, self.policy)

    @cached_property
    def reader_times(self) -> ReaderTimes:
        return ReaderTimes(self.context, self.policy)

    def default_timeline(self, entity: Entity) -> str:
        """The prime timeline of the entity's dimension (multiversal entities have none)."""
        if entity.dimension_id is None:
            raise _invalid("timeline", "A multiversal entity needs a timeline.")
        prime = prime_timeline(self.session, entity.dimension_id)
        if prime is None:
            raise _invalid("timeline", "The entity's dimension has no prime timeline.")
        return prime.id

    def of_entity(self, entity_id: str, *, timeline_id: str | None, at: str) -> EntityStateOut:
        """The state of a visible entity (``404`` otherwise)."""
        entity = self.entities.load_visible(entity_id)
        return self.state(entity, timeline_id=timeline_id, at=at)

    def state(self, entity: Entity, *, timeline_id: str | None, at: str) -> EntityStateOut:
        as_of = resolve_as_of(
            self.context,
            self.policy,
            timeline_id if timeline_id is not None else self.default_timeline(entity),
            at,
        )
        if entity.dimension_id not in (None, as_of.dimension_id):
            raise _invalid("timeline", "The timeline belongs to another dimension.")
        reader = StateReader(self.context, self.policy, as_of.timeline_id, as_of.t)
        found = reader.states([entity])[entity.id]
        return EntityStateOut(
            entity_id=entity.id,
            timeline_id=as_of.timeline_id,
            at=as_of.t,
            existence=found.existence,
            existence_fact_ids=found.existence_fact_ids,
            name=found.name,
            name_certainty=found.name_certainty,
            name_fact_id=found.name_fact_id,
            fields=self._fields(entity, found, as_of.dimension_id),
        )

    def _fields(
        self, entity: Entity, found: EntityState, dimension_id: str
    ) -> dict[str, FieldStateOut]:
        kind = self.entities.kinds[entity.kind]
        kind_fields = self.entities.kind_fields(kind)
        static, _ = self.entities.shown_fields(entity, kind_fields)
        result: dict[str, FieldStateOut] = {}
        for key, field in kind_fields.active.items():
            if not field.temporal or not self._shown(entity, field):
                continue
            covers = found.covers.get(key, [])
            if covers:
                result[key] = self._from_facts(field, covers, dimension_id)
            else:
                result[key] = FieldStateOut(
                    value=static.get(key),
                    source="static",
                    fact_ids=[],
                    certainty="certain",
                    ambiguous=False,
                )
        return result

    def _shown(self, entity: Entity, field: FieldDef) -> bool:
        level = self.policy.field_level(field, entity.field_visibility or {})
        return self.policy.shows(level)

    def _from_facts(
        self, field: FieldDef, covers: Sequence[Cover], dimension_id: str
    ) -> FieldStateOut:
        """Covers are latest start first."""
        used = list(covers) if field.multiple else [covers[0]]
        if field.multiple:
            value: Any = []
            for cover in used:
                for item in cover.fact.value or []:
                    shown = self._value(field, item, dimension_id, cover.fact.id)
                    if shown is not None and shown not in value:
                        value.append(shown)
        else:
            value = self._value(field, used[0].fact.value, dimension_id, used[0].fact.id)
        return FieldStateOut(
            value=value,
            source="fact",
            fact_ids=[c.fact.id for c in used],
            certainty="possible" if any(c.certainty == "possible" for c in used) else "certain",
            ambiguous=not field.multiple and len(covers) > 1,
        )

    def _value(self, field: FieldDef, value: Any, dimension_id: str, owner: str) -> Any:
        """One value as the policy may see it (time points to hidden records become moments,
        hidden references in rich text are dropped)."""
        if not self.policy.reader or value is None:
            return value
        if field.type == "time_point":
            return self.reader_times.point(value, dimension_id, owner=owner)
        if field.type == "rich_text":
            return self.policy.filter_richtext(self.session, value, self.entities.richtext)
        return value


def existence_of(
    context: VaultContext,
    policy: VisibilityPolicy,
    *,
    timeline_id: str | None,
    at: str | None,
    dimension_id: str | None = None,
) -> ExistenceOf | None:
    """The existence reader of a list's time cursor (``None`` without ``at``). The timeline
    defaults to the prime timeline of ``dimension_id``."""
    if at is None:
        return None
    if timeline_id is None:
        prime = None if dimension_id is None else prime_timeline(context.session, dimension_id)
        if prime is None:
            raise _invalid("timeline", "`at` needs a timeline (or a dimension).")
        timeline_id = prime.id
    as_of = resolve_as_of(context, policy, timeline_id, at)
    return StateReader(context, policy, as_of.timeline_id, as_of.t).existence
