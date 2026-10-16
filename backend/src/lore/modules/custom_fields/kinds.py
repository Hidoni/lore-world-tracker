"""Custom kinds (``docs/modules/custom_fields.md``): authors' own kinds, and converting entities
between kinds.

``provide_kinds`` hands the live (not archived) kinds to the core (``ModuleSpec.kind_providers``),
so entity APIs, search, graph and consistency treat them like built-in kinds
(``ModuleRegistry.vault_kinds``). Archiving a kind hides it and its entities; deleting one is only
possible while no entity (the trash included) has it.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.facts.service import Facts
from lore.core.fields import KindFields
from lore.core.history import recorder
from lore.core.modules.registry import RegisteredKind
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef, KindCapabilities, KindDef
from lore.core.search.indexer import SearchIndexer
from lore.core.time.fields import write_time_fields
from lore.core.types import Affected
from lore.modules.custom_fields.models import CustomFieldDef, CustomKind
from lore.modules.custom_fields.schemas import (
    ConvertKind,
    ConvertKindResult,
    CustomKindCreate,
    CustomKindDeleteResult,
    CustomKindList,
    CustomKindOut,
    CustomKindUpdate,
    CustomKindWriteResult,
    KindCapabilitiesIn,
)

PREFIX = "custom."


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def kind_def(row: CustomKind) -> KindDef:
    capabilities = KindCapabilitiesIn.model_validate(row.capabilities)
    return KindDef(
        key=row.key,
        label=row.label,
        plural=row.plural,
        icon=row.icon,
        color=row.color,
        description=row.description,
        allowed_parents=tuple(row.allowed_parents),
        capabilities=KindCapabilities(has_body=True, **capabilities.model_dump()),
        default_visibility=row.default_visibility,  # type: ignore[arg-type]
    )


def provide_kinds(session: Session) -> Sequence[KindDef]:
    """The live custom kinds, by key."""
    rows = session.scalars(
        select(CustomKind).where(CustomKind.archived.is_(False)).order_by(CustomKind.key)
    )
    return [kind_def(row) for row in rows]


class CustomKinds:
    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.registry = context.registry
        enabled = enabled_modules(self.session, self.registry)
        self.kinds = {kind.key: kind for kind in self.registry.vault_kinds(self.session, enabled)}
        self.extensions = self.registry.kind_extensions_for(enabled)

    # --- reads ----------------------------------------------------------------------------------

    def _row(self, key: str) -> CustomKind:
        row = self.session.get(CustomKind, key)
        if row is None:
            raise NotFoundError(f"No custom kind {key}.")
        return row

    def _count(self, key: str) -> int:
        return (
            self.session.scalar(select(func.count()).select_from(Entity).where(Entity.kind == key))
            or 0
        )

    def out(self, row: CustomKind) -> CustomKindOut:
        return CustomKindOut(
            key=row.key, label=row.label, plural=row.plural, icon=row.icon, color=row.color,
            description=row.description, allowed_parents=list(row.allowed_parents),
            capabilities=KindCapabilitiesIn.model_validate(row.capabilities),
            default_visibility=row.default_visibility,  # type: ignore[arg-type]
            archived=row.archived, revision=row.revision, created_at=row.created_at,
            updated_at=row.updated_at, entities=self._count(row.key),
        )  # fmt: skip

    def list_kinds(self) -> CustomKindList:
        """The custom kinds (archived ones too), by key."""
        rows = self.session.scalars(select(CustomKind).order_by(CustomKind.key))
        return CustomKindList(items=[self.out(row) for row in rows])

    def get(self, key: str) -> CustomKindOut:
        return self.out(self._row(key))

    # --- writes ---------------------------------------------------------------------------------

    def _check_parents(self, own: str, parents: Sequence[str]) -> list[str]:
        known = set(self.kinds) | self.registry.all_kind_keys() | {own}
        known |= set(self.session.scalars(select(CustomKind.key)))
        unknown = [f"allowed_parents.{i}" for i, key in enumerate(parents) if key not in known]
        if unknown:
            raise InvalidInputError(
                "Unknown kinds.",
                errors=[ErrorItem(path=p, code="invalid_value", message="unknown kind")
                        for p in unknown],
            )  # fmt: skip
        return list(dict.fromkeys(parents))

    def create(self, data: CustomKindCreate) -> CustomKindWriteResult:
        key = PREFIX + data.key
        if self.session.get(CustomKind, key) is not None or key in self.registry.all_kind_keys():
            raise _invalid("key", f"{key!r} is taken.", "taken")
        row = CustomKind(
            key=key, label=data.label, plural=data.plural, icon=data.icon, color=data.color,
            description=data.description,
            allowed_parents=self._check_parents(key, data.allowed_parents),
            capabilities=data.capabilities.model_dump(),
            default_visibility=data.default_visibility,
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        recorder.describe(self.session, f"Added the kind {row.label}")
        return CustomKindWriteResult(kind=self.out(row), affected=_affected([]))

    def update(self, key: str, data: CustomKindUpdate) -> CustomKindWriteResult:
        row = self._row(key)
        if data.revision != row.revision:
            raise ConflictError(
                f"The kind changed (revision {row.revision}, the edit is based on "
                f"{data.revision}).",
                context={"current_revision": row.revision},
            )
        sent = data.model_fields_set - {"revision", "suppress"}
        if "allowed_parents" in sent and data.allowed_parents is not None:
            row.allowed_parents = self._check_parents(key, data.allowed_parents)
        if "capabilities" in sent and data.capabilities is not None:
            self._check_capabilities(key, data.capabilities)
            row.capabilities = data.capabilities.model_dump()
        for name in ("label", "plural", "icon", "color", "description", "archived"):
            if name in sent and getattr(data, name) is not None:
                setattr(row, name, getattr(data, name))
        if "default_visibility" in sent:
            row.default_visibility = data.default_visibility
        self.session.flush()
        touched: list[str] = []
        if "archived" in sent:  # its entities leave (or come back to) search
            touched = list(self.session.scalars(select(Entity.id).where(Entity.kind == key)))
            if touched:
                SearchIndexer(self.context).index_entities(touched)
        recorder.describe(self.session, f"Changed the kind {row.label}")
        return CustomKindWriteResult(kind=self.out(row), affected=_affected(touched))

    def _check_capabilities(self, key: str, capabilities: KindCapabilitiesIn) -> None:
        if not capabilities.can_be_multiversal and self.session.scalar(
            select(func.count())
            .select_from(Entity)
            .where(Entity.kind == key, Entity.dimension_id.is_(None))
        ):
            raise _invalid(
                "capabilities.can_be_multiversal",
                "Some entities of the kind are multiversal: give them a home dimension first.",
            )

    def delete(self, key: str) -> CustomKindDeleteResult:
        """Delete an unused kind (with its custom fields); a kind in use is ``409 conflict``:
        archive it, or convert its entities to another kind first."""
        row = self._row(key)
        used = self._count(key)
        if used:
            raise ConflictError(
                f"{used} entities have the kind {row.label}: convert them or archive the kind.",
                context={"entities": used},
            )
        for field in self.session.scalars(
            select(CustomFieldDef).where(CustomFieldDef.kind_key == key)
        ):
            self.session.delete(field)
        label = row.label
        self.session.delete(row)
        self.session.flush()
        recorder.describe(self.session, f"Deleted the kind {label}")
        return CustomKindDeleteResult(key=key, affected=_affected([]))

    # --- convert --------------------------------------------------------------------------------

    def _convertible(self, kind: RegisteredKind | None, path: str, key: str) -> RegisteredKind:
        if kind is None:
            raise _invalid(path, f"Unknown kind {key!r}.")
        capabilities = kind.definition.capabilities
        if capabilities.is_system or capabilities.is_time_bound or kind.key in self.extensions:
            raise _invalid(
                path, f"{kind.definition.plural} keep data of their own: they can't be converted."
            )
        return kind

    def convert(self, data: ConvertKind) -> ConvertKindResult:
        """Give the entities ``to_kind`` in one changeset (``ConvertKind``)."""
        target = self._convertible(self.kinds.get(data.to_kind), "to_kind", data.to_kind)
        entities = EntityService(self.context)
        target_fields = entities.kind_fields(target)
        mapping = dict(data.field_mapping)
        for source_key, target_key in mapping.items():
            if target_key is not None and target_key not in target_fields.active:
                raise _invalid(
                    f"field_mapping.{source_key}",
                    f"{target_key!r} isn't a field of {target.definition.plural}.",
                )
        rows: list[Entity] = []
        for index, entity_id in enumerate(dict.fromkeys(data.entity_ids)):
            entity = self.session.get(Entity, entity_id)
            if entity is None or entity.deleted_at is not None:
                raise _invalid(f"entity_ids.{index}", f"No entity {entity_id}.", "not_found")
            self._convertible(self.kinds.get(entity.kind), f"entity_ids.{index}", entity.kind)
            if (
                entity.dimension_id is None
                and not target.definition.capabilities.can_be_multiversal
            ):
                raise _invalid(
                    f"entity_ids.{index}",
                    f"{entity.name} is multiversal; {target.definition.plural} can't be.",
                )
            rows.append(entity)
        touched: list[str] = []
        for index, entity in enumerate(rows):
            source = self.kinds[entity.kind]
            source_points = {
                key: field
                for key, field in entities.kind_fields(source).active.items()
                if field.type == "time_point"
            }
            entity.fields = self._moved(entity.fields, mapping, target_fields.active, index)
            entity.field_visibility = self._renamed(entity.field_visibility, mapping)
            self._move_facts(entity, mapping, target_fields.active, index)
            if entity.kind != target.key:
                entity.kind = target.key
                touched.append(entity.id)
            elif mapping:
                touched.append(entity.id)
            # Time-point rows of the old fields go (or follow their new keys).
            write_time_fields(self.context, entity, source_points, strict=False)
            write_time_fields(self.context, entity, target_fields.active, strict=False)
        self.session.flush()
        if touched:
            SearchIndexer(self.context).index_entities(touched)
        recorder.describe(
            self.session,
            f"Converted {len(rows)} {'entity' if len(rows) == 1 else 'entities'} to "
            f"{target.definition.plural}",
        )
        return ConvertKindResult(
            entity_ids=[entity.id for entity in rows],
            affected=_affected(touched, time_changed=bool(touched)),
        )

    def _moved(
        self,
        stored: Mapping[str, Any],
        mapping: Mapping[str, str | None],
        target: Mapping[str, FieldDef],
        index: int,
    ) -> dict[str, Any]:
        """``stored`` with mapped values under their new keys (checked), dropped ones removed
        and the others kept as they are."""
        result = {key: value for key, value in stored.items() if key not in mapping}
        for source_key, target_key in mapping.items():
            if source_key not in stored or target_key is None:
                continue
            field = target[target_key]
            try:
                result[target_key] = self._validate(field, stored[source_key])
            except ValueError as error:
                raise _invalid(f"entity_ids.{index}",
                               f"{source_key} → {target_key}: {error}") from error  # fmt: skip
        return result

    def _validate(self, field: FieldDef, value: Any) -> Any:
        enabled = enabled_modules(self.session, self.registry)
        fields = KindFields.build([field], self.registry.field_types_for(enabled))
        return fields.validate_value(field, value)

    @staticmethod
    def _renamed(stored: Mapping[str, Any], mapping: Mapping[str, str | None]) -> dict[str, Any]:
        result = {key: value for key, value in stored.items() if key not in mapping}
        for source_key, target_key in mapping.items():
            if source_key in stored and target_key is not None:
                result[target_key] = stored[source_key]
        return result

    def _move_facts(
        self,
        entity: Entity,
        mapping: Mapping[str, str | None],
        target: Mapping[str, FieldDef],
        index: int,
    ) -> None:
        """Mapped facts take their new field key (it must be temporal); dropped ones go to the
        trash with the entity's changeset."""
        if not mapping:
            return
        facts = list(
            self.session.scalars(
                select(EntityFact).where(
                    EntityFact.entity_id == entity.id,
                    EntityFact.field_key.in_(list(mapping)),
                    EntityFact.deleted_at.is_(None),
                )
            )
        )
        for fact in facts:
            target_key = mapping[fact.field_key]
            if target_key is None:
                Facts(self.context).delete(fact.id)
                continue
            field = target[target_key]
            if not field.temporal:
                raise _invalid(
                    f"field_mapping.{fact.field_key}",
                    f"{entity.name} has facts of {fact.field_key}, and {target_key} isn't "
                    "temporal: map it to a temporal field or drop them.",
                )
            if fact.value is not None:
                try:
                    fact.value = self._validate(field, fact.value)
                except ValueError as error:
                    raise _invalid(f"entity_ids.{index}",
                                   f"A fact of {fact.field_key}: {error}") from error  # fmt: skip
            fact.field_key = target_key


def _affected(entity_ids: Sequence[str], *, time_changed: bool = False) -> Affected:
    ids = sorted(set(entity_ids))
    return Affected(entities=ids, dimensions=[], time_changed=time_changed,
                    search_changed=bool(ids))  # fmt: skip
