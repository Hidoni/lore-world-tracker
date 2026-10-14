"""The fact service (``time-model.md`` §10.2-§10.4): an entity's field values over time,
existence (``core.exists``) and names over time (``core.name``).

Writes run in the request's transaction (one changeset) and keep derived data in step: the
validity slots and a ``time_point`` value's slot (``TimeWriter``), and the entity's search
document. Reads go through the request's ``VisibilityPolicy``: a fact is shown when the policy
shows it, its entity, its timeline and its field; the source event is left out when hidden, and
time points referring to hidden records are shown as moments.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from sqlalchemy import select

from lore.chronology.schema import TimePoint
from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.facts.schemas import (
    EXISTS,
    NAME,
    FactCreate,
    FactList,
    FactOut,
    FactUpdate,
    FactWriteResult,
)
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef
from lore.core.search.indexer import SearchIndexer
from lore.core.time.changes import report as report_time
from lore.core.time.dependencies import SlotNode
from lore.core.time.dimensions import TIMELINE
from lore.core.time.events import EVENT
from lore.core.time.fields import ENTITY_FIELD, FACT_PREFIX, fact_slot, sync_rows
from lore.core.time.models import EntityTimeField, Timeline
from lore.core.time.overrides import overrides_of, sync_starts
from lore.core.time.propagate import TimeWriter
from lore.core.time.redact import ReaderTimes
from lore.core.time.timeline_view import TimelineView
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityPolicy

FACT = "fact"
SLOTS = ("valid_from", "valid_to")
MAX_NAME = 500


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


@dataclass
class Facts:
    context: VaultContext
    policy: VisibilityPolicy = AUTHOR

    def __post_init__(self) -> None:
        self.session = self.context.session
        self.entities = EntityService(self.context, self.policy)

    # --- reads ----------------------------------------------------------------------------------

    def of_entity(
        self, entity_id: str, *, field_key: str | None = None, timeline_id: str | None = None
    ) -> FactList:
        """The entity's live facts the policy shows (``404`` for an entity it hides): of every
        timeline, or those visible in ``timeline_id`` (its own and those its lineage inherits,
        ``time-model.md`` §4.3)."""
        entity = self.entities.load_visible(entity_id)
        if timeline_id is None:
            statement = select(EntityFact).where(
                EntityFact.entity_id == entity.id, EntityFact.deleted_at.is_(None)
            )
        else:
            view = TimelineView.for_timeline(self.session, timeline_id)
            statement = view.select(
                EntityFact,
                where=lambda row: [row.entity_id == entity.id, row.deleted_at.is_(None)],
            )
        statement = statement.where(
            *self.policy.rows(EntityFact), *self.policy.entity_ref(EntityFact.timeline_id)
        )
        if field_key is not None:
            statement = statement.where(EntityFact.field_key == field_key)
        facts = [
            fact
            for fact in self.session.scalars(statement)
            if self.field_shown(entity, fact.field_key)
        ]
        facts.sort(
            key=lambda f: (
                f.field_key,
                f.valid_from_t is not None,
                f.valid_from_t or 0,
                f.sort_key or "",
                f.created_at,
                f.id,
            )
        )
        return FactList(items=self.out_many(entity, facts))

    def caused_by(self, event_id: str) -> FactList:
        """The live facts the policy shows whose source is the event (its "changes caused"), by
        entity, field and start. ``404`` for an event the policy hides (or not an event)."""
        event = self.entities.load_visible(event_id)
        if event.kind != EVENT:
            raise NotFoundError(f"No event {event_id}.")
        facts = list(
            self.session.scalars(
                select(EntityFact).where(
                    EntityFact.source_event_id == event.id,
                    EntityFact.deleted_at.is_(None),
                    *self.policy.rows(EntityFact),
                    *self.policy.entity_ref(EntityFact.timeline_id),
                )
            )
        )
        shown = self.policy.visible_ids(self.session, {fact.entity_id for fact in facts})
        by_entity: dict[str, list[EntityFact]] = {}
        for fact in facts:
            if fact.entity_id in shown:
                by_entity.setdefault(fact.entity_id, []).append(fact)
        items: list[FactOut] = []
        for entity_id in sorted(by_entity):
            entity = self.session.get(Entity, entity_id)
            if entity is None or entity.kind not in self.entities.kinds:
                continue
            own = [f for f in by_entity[entity_id] if self.field_shown(entity, f.field_key)]
            own.sort(key=lambda f: (f.field_key, f.valid_from_t is not None, f.valid_from_t or 0,
                                    f.created_at, f.id))  # fmt: skip
            items += self.out_many(entity, own)
        return FactList(items=items)

    def get(self, fact_id: str) -> FactOut:
        fact, entity = self._visible(fact_id)
        return self.out_many(entity, [fact])[0]

    def _visible(self, fact_id: str) -> tuple[EntityFact, Entity]:
        """A live fact the policy shows, with its entity (``404`` otherwise)."""
        fact = self.session.scalar(
            select(EntityFact).where(
                EntityFact.id == fact_id,
                *self.policy.rows(EntityFact),
                *self.policy.entity_ref(EntityFact.timeline_id),
            )
        )
        if fact is None or fact.deleted_at is not None:
            raise NotFoundError(f"No fact {fact_id}.")
        entity = self.entities.load_visible(fact.entity_id)
        if not self.field_shown(entity, fact.field_key):
            raise NotFoundError(f"No fact {fact_id}.")
        return fact, entity

    def field_shown(self, entity: Entity, key: str) -> bool:
        """Facts of a field follow the field's visibility for this entity."""
        if key in (EXISTS, NAME):
            return True
        field = self._field(entity, key)
        return field is not None and self.policy.shows(
            self.policy.field_level(field, entity.field_visibility)
        )

    def _field(self, entity: Entity, key: str) -> FieldDef | None:
        kind = self.entities.kinds.get(entity.kind)
        if kind is None:
            return None
        return self.entities.kind_fields(kind).active.get(key)

    @cached_property
    def reader_times(self) -> ReaderTimes:
        return ReaderTimes(self.context, self.policy)

    def out_many(self, entity: Entity, facts: Sequence[EntityFact]) -> list[FactOut]:
        events = self.policy.visible_ids(self.session, [f.source_event_id for f in facts])
        moments = dict(
            self.session.execute(
                select(EntityTimeField.field_key, EntityTimeField.t).where(
                    EntityTimeField.entity_id == entity.id,
                    EntityTimeField.field_key.in_([fact_slot(f.id) for f in facts]),
                )
            ).all()
        )
        dimensions = dict(
            self.session.execute(
                select(Timeline.entity_id, Timeline.dimension_id).where(
                    Timeline.entity_id.in_({f.timeline_id for f in facts})
                )
            ).all()
        )
        return [
            self._out(
                entity,
                fact,
                events,
                moments.get(fact_slot(fact.id)),
                dimensions.get(fact.timeline_id),
            )
            for fact in facts
        ]

    def _out(
        self,
        entity: Entity,
        fact: EntityFact,
        events: frozenset[str],
        value_t: int | None,
        dimension_id: str | None,
    ) -> FactOut:
        times = self.reader_times
        value = fact.value
        field = self._field(entity, fact.field_key)
        if self.policy.reader and field is not None and value is not None:
            if field.type == "time_point":
                value = times.point(value, dimension_id, owner=fact.id)
            elif field.type == "rich_text":
                value = self.policy.filter_richtext(self.session, value, self.entities.richtext)
        return FactOut(
            id=fact.id,
            entity_id=fact.entity_id,
            field_key=fact.field_key,
            value=value,
            value_t=value_t,
            timeline_id=fact.timeline_id,
            valid_from=times.point(fact.valid_from_spec, dimension_id, owner=fact.id),
            valid_to=times.point(fact.valid_to_spec, dimension_id, owner=fact.id),
            valid_from_t=fact.valid_from_t,
            valid_to_t=fact.valid_to_t,
            time_status=fact.time_status,
            visibility=fact.visibility,
            source_event_id=fact.source_event_id if fact.source_event_id in events else None,
            note=fact.note,
            sort_key=fact.sort_key,
            revision=fact.revision,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            deleted_at=fact.deleted_at,
        )

    # --- writes ---------------------------------------------------------------------------------

    def create(self, entity_id: str, data: FactCreate) -> FactWriteResult:
        entity = self._writable_entity(entity_id)
        if data.overrides_id is not None:
            raise _invalid("overrides_id", "Branch overrides of facts come with branches (M9).",
                           "not_supported")  # fmt: skip
        value = self._value(entity, data.field_key, data.value, "value")
        self._check_timeline(entity, data.timeline_id)
        self._check_source(data.source_event_id)
        fact = EntityFact(
            entity_id=entity.id,
            field_key=data.field_key,
            value=value,
            timeline_id=data.timeline_id,
            valid_from_spec=data.valid_from,
            valid_to_spec=data.valid_to,
            visibility=data.visibility,
            source_event_id=data.source_event_id,
            note=data.note,
            sort_key=data.sort_key,
        )
        self.session.add(fact)
        self.session.flush()
        self._write_times(entity, fact, set(SLOTS), value_changed=True)
        return self._result(entity, fact)

    def update(self, fact_id: str, data: FactUpdate) -> FactWriteResult:
        fact = self._fact(fact_id)
        entity = self._writable_entity(fact.entity_id)
        if data.revision != fact.revision:
            raise RevisionConflictError(
                f"The fact was changed meanwhile (revision {fact.revision}, the edit is based on "
                f"{data.revision}).",
                context={"current": self.out_many(entity, [fact])[0].model_dump(mode="json")},
            )
        sent = data.model_fields_set - {"revision", "suppress"}
        self._check_override_edit(fact, sent)
        if "value" in sent:
            fact.value = self._value(entity, fact.field_key, data.value, "value")
        if "timeline_id" in sent:
            if data.timeline_id is None:
                raise _invalid("timeline_id", "A fact needs a timeline.", "required")
            self._check_timeline(entity, data.timeline_id)
            fact.timeline_id = data.timeline_id
        if "visibility" in sent:
            if data.visibility is None:
                raise _invalid("visibility", "Visibility must be public, spoiler or private.")
            fact.visibility = data.visibility
        if "source_event_id" in sent:
            self._check_source(data.source_event_id)
            fact.source_event_id = data.source_event_id
        for name in ("note", "sort_key"):
            if name in sent:
                setattr(fact, name, getattr(data, name))
        if "valid_from" in sent:
            fact.valid_from_spec = data.valid_from
        if "valid_to" in sent:
            fact.valid_to_spec = data.valid_to
        if sent:
            fact.updated_at = utc_now()
        self.session.flush()
        # A new timeline can mean a new dimension: every slot of the fact resolves again.
        moved = "timeline_id" in sent
        slots = {slot for slot in SLOTS if slot in sent or moved}
        self._write_times(entity, fact, slots, value_changed="value" in sent or moved,
                          sync="valid_from" in sent)  # fmt: skip
        return self._result(entity, fact)

    def _check_override_edit(self, fact: EntityFact, sent: set[str]) -> None:
        """Override rows change through the branches module; a root with overrides stays in its
        timeline."""
        if fact.overrides_id is not None:
            message = ("The fact is a branch override: change it through the branches module (or "
                       "delete it to revert).")  # fmt: skip
            raise _invalid("overrides_id", message, "override_not_allowed")
        if "timeline_id" in sent and overrides_of(self.session, EntityFact, fact.id):
            message = "Branches override the fact: it can't move to another timeline."
            raise _invalid("timeline_id", message, "override_not_allowed")

    def delete(self, fact_id: str) -> FactWriteResult:
        """Move the fact to the trash: what is anchored to it keeps its last moments
        (``trashed_ref``)."""
        fact = self._fact(fact_id)
        entity = self._writable_entity(fact.entity_id)
        fact.deleted_at = utc_now()
        # Its branch overrides go with it (a branch can't keep a record the parent removed).
        trashed = [fact, *overrides_of(self.session, EntityFact, fact.id)]
        for row in trashed[1:]:
            row.deleted_at = fact.deleted_at
        self.session.flush()
        writer = TimeWriter(self.context)
        nodes = [SlotNode(FACT, row.id, slot) for row in trashed for slot in SLOTS]
        writer.touch(*(d for node in nodes for d in writer.index.dependents_of(node)))
        writer.propagate(path="")
        SearchIndexer(self.context).index_entities([entity.id])
        return self._result(entity, fact)

    def _fact(self, fact_id: str) -> EntityFact:
        fact = self.session.get(EntityFact, fact_id)
        if fact is None or fact.deleted_at is not None:
            raise NotFoundError(f"No fact {fact_id}.")
        return fact

    def _writable_entity(self, entity_id: str) -> Entity:
        entity = self.entities.load_visible(entity_id)
        if entity.deleted_at is not None:
            raise ConflictError("The entity is in the trash: restore it before editing it.")
        return entity

    def _result(self, entity: Entity, fact: EntityFact) -> FactWriteResult:
        return FactWriteResult(
            fact=self.out_many(entity, [fact])[0], affected=self._affected(entity, fact)
        )

    def _affected(self, entity: Entity, fact: EntityFact) -> Affected:
        timeline = self.session.get(Timeline, fact.timeline_id)
        dimensions = {d for d in (entity.dimension_id,
                                  timeline.dimension_id if timeline else None) if d}  # fmt: skip
        affected = Affected(
            entities=[entity.id],
            dimensions=sorted(dimensions),
            time_changed=False,
            search_changed=True,
        )
        return report_time(self.session, self.context.registry, affected)

    # --- validation -----------------------------------------------------------------------------

    def _value(self, entity: Entity, key: str, value: Any, path: str) -> Any:
        """The fact's value, checked against its field (``core.exists``: ``true``)."""
        if key == EXISTS:
            if value not in (None, True):
                raise _invalid(path, "An existence fact's value is true.")
            return True
        if key == NAME:
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME:
                raise _invalid(path, f"A name (1 to {MAX_NAME} characters) is required.")
            return value.strip()
        field = self._field(entity, key)
        if field is None:
            raise _invalid("field_key", f"{key!r} is not a field of this kind.", "unknown_field")
        if not field.temporal:
            raise _invalid("field_key", f"{field.label} doesn't change over time: set the "
                           "entity's value instead.", "not_temporal")  # fmt: skip
        if value is None:
            raise _invalid(path, "A value is required.", "required")
        kind = self.entities.kinds[entity.kind]
        try:
            normalized = self.entities.kind_fields(kind).validate_value(field, value)
        except ValueError as error:
            raise _invalid(path, str(error)) from error
        if field.type == "rich_text":
            from lore.core.richtext.schema import validate_document  # noqa: PLC0415

            normalized = validate_document(normalized, self.entities.richtext, path=path)
        return normalized

    def _check_timeline(self, entity: Entity, timeline_id: str) -> None:
        try:
            timeline = self.entities.load_visible(timeline_id)
        except NotFoundError as error:
            raise _invalid("timeline_id", f"No timeline {timeline_id}.") from error
        if timeline.kind != TIMELINE or timeline.deleted_at is not None:
            raise _invalid("timeline_id", f"{timeline_id} is not a timeline.")
        if entity.dimension_id is not None and timeline.dimension_id != entity.dimension_id:
            raise _invalid("timeline_id", "The timeline is not in the entity's dimension.")

    def _check_source(self, event_id: str | None) -> None:
        if event_id is None:
            return
        try:
            event = self.entities.load_visible(event_id)
        except NotFoundError as error:
            raise _invalid("source_event_id", f"No event {event_id}.") from error
        if event.kind != EVENT or event.deleted_at is not None:
            raise _invalid("source_event_id", f"{event_id} is not an event.")

    # --- time -----------------------------------------------------------------------------------

    def _write_times(
        self,
        entity: Entity,
        fact: EntityFact,
        slots: set[str],
        *,
        value_changed: bool,
        sync: bool = False,
    ) -> None:
        """Store the changed slots' specs and propagate: the bounds, and a ``time_point``
        value (slot ``fact:<id>`` of the entity's ``entity_field`` record). ``sync``: the start
        changed, which the fact's branch overrides copy."""
        writer = TimeWriter(self.context)
        for slot in sorted(slots):
            spec = fact.valid_from_spec if slot == "valid_from" else fact.valid_to_spec
            writer.set_spec(FACT, fact.id, slot, spec)
        if sync:
            sync_starts(self.context, writer, FACT, fact)
        if value_changed:
            field = self._field(entity, fact.field_key)
            wanted: dict[str, TimePoint] = {}
            if field is not None and field.type == "time_point":
                values = fact.value if field.multiple else [fact.value]
                # A multiple field's fact holds a list: its first value is the one that resolves.
                if values:
                    wanted[fact_slot(fact.id)] = TimePoint.model_validate(values[0])
            slot = fact_slot(fact.id)
            for changed, spec in sync_rows(self.session, entity.id, wanted,
                                           prefix_filter=lambda s: s == slot):  # fmt: skip
                writer.set_spec(ENTITY_FIELD, entity.id, changed, spec)
            if wanted:  # also when only the timeline (its dimension) changed
                writer.touch(SlotNode(ENTITY_FIELD, entity.id, slot))
        writer.propagate(path="")
        SearchIndexer(self.context).index_entities([entity.id])


__all__ = ["FACT", "FACT_PREFIX", "Facts"]
