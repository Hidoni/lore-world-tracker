"""The custom_fields service (``docs/modules/custom_fields.md``): authors' fields on kinds.

Definitions live in ``custom_fields_defs``; ``provide_fields`` hands them to the core
(``ModuleSpec.field_providers``), so entities validate, index and show them like any other field
(``ModuleRegistry.vault_kinds``). Values live in ``entities.fields`` (and ``entity_facts`` for
temporal fields). Changes follow the rules for changes: archive keeps values (hidden), deleting a
field with values needs ``delete_values`` (undoable: one changeset), and types change only along
safe conversions, migrating the values in the same changeset.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.facts.service import Facts
from lore.core.fields import KindFields
from lore.core.history import recorder
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import ANY_KIND, FieldDef, FieldOption
from lore.core.search.indexer import SearchIndexer
from lore.core.time.fields import write_time_fields
from lore.core.types import Affected
from lore.modules.custom_fields.models import CustomFieldDef
from lore.modules.custom_fields.schemas import (
    CustomFieldCreate,
    CustomFieldDeleteResult,
    CustomFieldList,
    CustomFieldOut,
    CustomFieldUpdate,
    CustomFieldWriteResult,
    FieldOptionIn,
    FieldReorder,
    option_dicts,
)

PREFIX = "custom."
CHOICE_TYPES = frozenset({"enum", "multi_enum"})
# Safe type conversions (old, new): the values migrate in the same changeset.
CONVERSIONS = frozenset(
    {
        ("text", "long_text"),
        ("long_text", "text"),
        ("enum", "multi_enum"),
        ("text", "enum"),
        ("integer", "decimal"),
    }
)


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def field_def(row: CustomFieldDef) -> FieldDef:
    return FieldDef(
        key=row.key,
        label=row.label,
        type=row.type,
        options=tuple(FieldOption(o["key"], o["label"], o.get("color")) for o in row.options),
        multiple=row.multiple,
        required=row.required,
        temporal=row.temporal,
        default_visibility=row.default_visibility,  # type: ignore[arg-type]
        section=row.section,
        sort=int(row.sort_key),
        help=row.help,
        searchable=row.searchable,
        archived=row.archived,
    )


def provide_fields(session: Session, kind_keys: Sequence[str]) -> Mapping[str, Sequence[FieldDef]]:
    """The custom fields of each kind (``"*"``: of every kind but the system ones)."""
    wanted = {*kind_keys, ANY_KIND}
    found: dict[str, list[FieldDef]] = {}
    rows = session.scalars(
        select(CustomFieldDef)
        .where(CustomFieldDef.kind_key.in_(wanted))
        .order_by(CustomFieldDef.sort_key, CustomFieldDef.key)
    )
    for row in rows:
        found.setdefault(row.kind_key, []).append(field_def(row))
    return found


def _json_key(key: str) -> str:
    return f'$."{key}"'


class CustomFields:
    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.registry = context.registry
        enabled = enabled_modules(self.session, self.registry)
        self.kinds = {kind.key: kind for kind in self.registry.kinds_for(enabled)}
        self.field_types = self.registry.field_types_for(enabled)

    # --- reads ----------------------------------------------------------------------------------

    def _row(self, field_id: str) -> CustomFieldDef:
        row = self.session.get(CustomFieldDef, field_id)
        if row is None:
            raise NotFoundError(f"No custom field {field_id}.")
        return row

    def _kind_keys(self, kind_key: str) -> list[str]:
        """The kinds whose entities hold the field's values."""
        if kind_key != ANY_KIND:
            return [kind_key]
        return sorted(
            k for k, kind in self.kinds.items() if not kind.definition.capabilities.is_system
        )

    def _holders(self, row: CustomFieldDef, *, live: bool) -> list[Entity]:
        """Entities with a value of the field (``live``: not in the trash)."""
        statement = select(Entity).where(
            Entity.kind.in_(self._kind_keys(row.kind_key)),
            func.json_extract(Entity.fields, _json_key(row.key)).is_not(None),
        )
        if live:
            statement = statement.where(Entity.deleted_at.is_(None))
        return list(self.session.scalars(statement.order_by(Entity.id)))

    def _facts(self, row: CustomFieldDef) -> list[EntityFact]:
        """The live facts of the field, of entities of its kinds."""
        return list(
            self.session.scalars(
                select(EntityFact)
                .join(Entity, Entity.id == EntityFact.entity_id)
                .where(
                    EntityFact.field_key == row.key,
                    EntityFact.deleted_at.is_(None),
                    Entity.kind.in_(self._kind_keys(row.kind_key)),
                )
                .order_by(EntityFact.id)
            )
        )

    def _usage(self, row: CustomFieldDef) -> int:
        ids = {entity.id for entity in self._holders(row, live=True)}
        ids |= {fact.entity_id for fact in self._facts(row)}
        return len(ids)

    def out(self, row: CustomFieldDef) -> CustomFieldOut:
        return CustomFieldOut(
            id=row.id, kind_key=row.kind_key, key=row.key, label=row.label, type=row.type,
            options=[FieldOptionIn.model_validate(o) for o in row.options], multiple=row.multiple,
            required=row.required, temporal=row.temporal,
            default_visibility=row.default_visibility,  # type: ignore[arg-type]
            section=row.section, sort_key=row.sort_key, help=row.help, searchable=row.searchable,
            archived=row.archived, revision=row.revision, created_at=row.created_at,
            updated_at=row.updated_at, entities_with_values=self._usage(row),
        )  # fmt: skip

    def list_fields(self, kind: str | None = None) -> CustomFieldList:
        """The custom fields (of a kind: its own and the ``"*"`` ones), by kind then order."""
        statement = select(CustomFieldDef)
        if kind is not None:
            statement = statement.where(CustomFieldDef.kind_key.in_({kind, ANY_KIND}))
        rows = self.session.scalars(
            statement.order_by(CustomFieldDef.kind_key, CustomFieldDef.sort_key, CustomFieldDef.key)
        )
        return CustomFieldList(items=[self.out(row) for row in rows])

    def get(self, field_id: str) -> CustomFieldOut:
        return self.out(self._row(field_id))

    # --- checks ---------------------------------------------------------------------------------

    def _check_kind(self, kind_key: str) -> None:
        if kind_key != ANY_KIND and kind_key not in self.kinds:
            raise _invalid("kind_key", f"Unknown kind {kind_key!r}.")

    def _check_type(self, type_key: str, path: str = "type") -> None:
        if type_key not in {field_type.key for field_type in self.field_types}:
            raise _invalid(path, f"{type_key!r} isn't a field type of this vault.")

    def _check_key(self, kind_key: str, key: str, own_id: str | None = None) -> None:
        """Keys are unique per kind; a ``"*"`` key is unique everywhere."""
        statement = select(CustomFieldDef.id).where(CustomFieldDef.key == key)
        if kind_key != ANY_KIND:
            statement = statement.where(CustomFieldDef.kind_key.in_({kind_key, ANY_KIND}))
        taken = [found for found in self.session.scalars(statement) if found != own_id]
        if taken:
            raise _invalid("key", f"{key!r} is taken.", "taken")

    def _check_options(self, type_key: str, options: Sequence[FieldOptionIn]) -> None:
        if type_key in CHOICE_TYPES:
            if not options:
                raise _invalid("options", "A choice field needs options.", "required")
            keys = [option.key for option in options]
            if len(set(keys)) != len(keys):
                raise _invalid("options", "Option keys must be unique.")
        elif options:
            raise _invalid("options", "Only enum and multi_enum fields have options.")

    def _next_sort_key(self, kind_key: str) -> str:
        last = self.session.scalar(
            select(func.max(CustomFieldDef.sort_key)).where(CustomFieldDef.kind_key == kind_key)
        )
        return f"{(int(last) + 1) if last else 1:06d}"

    def _affected(self, entity_ids: Iterable[str], *, time_changed: bool = False) -> Affected:
        ids = sorted(set(entity_ids))
        return Affected(entities=ids, dimensions=[], time_changed=time_changed,
                        search_changed=bool(ids))  # fmt: skip

    # --- writes ---------------------------------------------------------------------------------

    def create(self, data: CustomFieldCreate) -> CustomFieldWriteResult:
        self._check_kind(data.kind_key)
        self._check_type(data.type)
        self._check_options(data.type, data.options)
        key = PREFIX + data.key
        self._check_key(data.kind_key, key)
        row = CustomFieldDef(
            kind_key=data.kind_key, key=key, label=data.label, type=data.type,
            options=option_dicts(data.options), multiple=data.multiple, required=data.required,
            temporal=data.temporal, default_visibility=data.default_visibility,
            section=data.section, sort_key=self._next_sort_key(data.kind_key), help=data.help,
            searchable=data.searchable,
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        recorder.describe(self.session, f"Added the field {row.label}")
        return CustomFieldWriteResult(field=self.out(row), affected=self._affected([]))

    def update(self, field_id: str, data: CustomFieldUpdate) -> CustomFieldWriteResult:
        row = self._row(field_id)
        if data.revision != row.revision:
            raise ConflictError(
                f"The field changed (revision {row.revision}, the edit is based on "
                f"{data.revision}).",
                context={"current_revision": row.revision},
            )
        sent = data.model_fields_set - {"revision", "suppress"}
        new_type, options, multiple, converter = self._shape(row, data, sent)
        drop_facts = "temporal" in sent and data.temporal is False and row.temporal
        if drop_facts and self._facts(row) and data.facts is None:
            raise _invalid("facts", "The field has facts: drop them or keep them.", "required")
        for name in ("label", "required", "default_visibility", "help", "searchable", "archived"):
            if name in sent and getattr(data, name) is not None:
                setattr(row, name, getattr(data, name))
        if "section" in sent:
            row.section = data.section
        if "temporal" in sent and data.temporal is not None:
            row.temporal = data.temporal
        row.type, row.options, row.multiple = new_type, option_dicts(options), multiple
        self.session.flush()
        touched: set[str] = set()
        if converter is not None:
            touched |= self._migrate_values(row, converter)
        if drop_facts and data.facts == "drop":
            touched |= self._drop_facts(row)
        if touched:
            SearchIndexer(self.context).index_entities(touched)
        recorder.describe(self.session, f"Changed the field {row.label}")
        return CustomFieldWriteResult(field=self.out(row), affected=self._affected(touched))

    def _shape(
        self, row: CustomFieldDef, data: CustomFieldUpdate, sent: set[str]
    ) -> tuple[str, list[FieldOptionIn], bool, Callable[[Any], Any] | None]:
        """The field's new type, options and ``multiple``, and how its values follow (``None``:
        they stay as they are)."""
        current = [FieldOptionIn.model_validate(o) for o in row.options]
        new_type = data.type if "type" in sent and data.type is not None else row.type
        options = data.options if "options" in sent and data.options is not None else current
        multiple = (
            data.multiple if "multiple" in sent and data.multiple is not None else row.multiple
        )
        if new_type != row.type:
            self._check_type(new_type)
            if (row.type, new_type) not in CONVERSIONS:
                raise _invalid(
                    "type",
                    f"{row.type} can't become {new_type}: create a new field and move the values.",
                    "unsafe_type_change",
                )
        self._check_options(new_type, options)
        if not sent & {"type", "options", "multiple"}:
            return new_type, options, multiple, None
        if new_type == "multi_enum":
            multiple = False  # a multi_enum value is a list already
        return (
            new_type,
            options,
            multiple,
            self._converter(row, new_type, options, multiple, data.value_map),
        )

    def _converter(
        self,
        row: CustomFieldDef,
        new_type: str,
        options: Sequence[FieldOptionIn],
        multiple: bool,
        value_map: Mapping[str, str | None] | None,
    ) -> Callable[[Any], Any]:
        """How each stored value (entity or fact) becomes the new one: ``None`` clears it. Refuses
        a change existing values can't follow (options in use removed, several values into one,
        texts without a mapping)."""
        old_type, was_multiple = row.type, row.multiple
        values = [entity.fields.get(row.key) for entity in self._holders(row, live=False)]
        values += [fact.value for fact in self._facts(row)]
        items = [
            item
            for value in values
            for item in (value if isinstance(value, list) else [value])
            if item is not None
        ]
        option_keys = {option.key for option in options}
        if old_type == "text" and new_type == "enum":
            mapping = dict(value_map or {})
            missing = sorted({str(item) for item in items} - set(mapping))
            if missing:
                raise _invalid("value_map", f"Map every value to an option (missing: {missing}).",
                               "required")  # fmt: skip
            unknown = sorted({v for v in mapping.values() if v is not None} - option_keys)
            if unknown:
                raise _invalid("value_map", f"Unknown options: {unknown}.")
        elif new_type in CHOICE_TYPES:
            in_use = {str(item) for item in items} - option_keys
            if in_use:
                raise _invalid("options", f"Options in use can't be removed: {sorted(in_use)}.")
        if (
            was_multiple
            and not multiple
            and new_type != "multi_enum"
            and any(isinstance(value, list) and len(value) > 1 for value in values)
        ):
            raise _invalid("multiple", "Some entities have several values: keep one first.")

        def item(value: Any) -> Any:
            if old_type == new_type:
                return value
            if (old_type, new_type) == ("long_text", "text"):
                return " ".join(str(value).split())
            if (old_type, new_type) == ("text", "enum"):
                return (value_map or {}).get(str(value))
            return value

        def convert(value: Any) -> Any:
            listed = value if isinstance(value, list) else [value]
            converted = [found for found in (item(v) for v in listed) if found is not None]
            if new_type == "multi_enum":
                return list(dict.fromkeys(converted)) or None
            if multiple:
                return converted or None
            return converted[0] if converted else None

        return convert

    def _migrate_values(self, row: CustomFieldDef, convert: Callable[[Any], Any]) -> set[str]:
        """The field's values (entities, trashed ones too, and facts) through ``convert``,
        checked against the new definition."""
        fields = KindFields.build([field_def(row)], self.field_types)
        definition = fields.active.get(row.key)
        touched: set[str] = set()
        for entity in self._holders(row, live=False):
            value = convert(entity.fields.get(row.key))
            stored = dict(entity.fields)
            if value is None:
                stored.pop(row.key, None)
            else:
                stored[row.key] = self._checked(fields, definition, value, f"fields.{row.key}")
            if stored != entity.fields:
                entity.fields = stored
                touched.add(entity.id)
        for fact in self.session.scalars(select(EntityFact).where(EntityFact.field_key == row.key)):
            value = convert(fact.value)
            if value is not None and value != fact.value:
                fact.value = self._checked(fields, definition, value, "value")
                touched.add(fact.entity_id)
        self.session.flush()
        return touched

    def _checked(
        self, fields: KindFields, definition: FieldDef | None, value: Any, path: str
    ) -> Any:
        if definition is None:  # archived: kept as converted
            return value
        try:
            return fields.validate_value(definition, value)
        except ValueError as error:
            raise _invalid(path, f"A value can't be converted: {error}") from error

    def _drop_facts(self, row: CustomFieldDef) -> set[str]:
        """The field's facts to the trash (roots through the facts service, so what is anchored
        to them keeps its moments; facts of trashed entities directly)."""
        facts = Facts(self.context)
        touched: set[str] = set()
        for fact in self._facts(row):
            if fact.overrides_id is not None or fact.deleted_at is not None:
                continue
            entity = self.session.get(Entity, fact.entity_id)
            if entity is not None and entity.deleted_at is None:
                facts.delete(fact.id)
            else:
                fact.deleted_at = utc_now()
            touched.add(fact.entity_id)
        self.session.flush()
        return touched

    def delete(self, field_id: str, *, delete_values: bool = False) -> CustomFieldDeleteResult:
        """Delete the field; with values (entities' or facts) only with ``delete_values``: they go
        in the same changeset, so undo brings them back."""
        row = self._row(field_id)
        holders = self._holders(row, live=False)
        facts = self._facts(row)
        if (holders or facts) and not delete_values:
            raise ConflictError(
                f"The field {row.label} has values: delete them too, or archive the field.",
                context={"entities": len({e.id for e in holders} | {f.entity_id for f in facts})},
            )
        definition = field_def(row)
        time_point = definition.type == "time_point"
        touched = self._drop_facts(row)
        for entity in holders:
            entity.fields = {k: v for k, v in entity.fields.items() if k != row.key}
            entity.field_visibility = {
                k: v for k, v in entity.field_visibility.items() if k != row.key
            }
            if time_point:  # its rows go (and what is anchored to them keeps its moments)
                write_time_fields(self.context, entity, {row.key: definition}, strict=False)
            touched.add(entity.id)
        self.session.delete(row)
        self.session.flush()
        if touched:
            SearchIndexer(self.context).index_entities(touched)
        recorder.describe(self.session, f"Deleted the field {definition.label}")
        return CustomFieldDeleteResult(
            id=field_id, affected=self._affected(touched, time_changed=time_point and bool(touched))
        )

    def reorder(self, data: FieldReorder) -> CustomFieldList:
        """The kind's custom fields in this order (every one of them, once)."""
        rows = {
            row.id: row
            for row in self.session.scalars(
                select(CustomFieldDef).where(CustomFieldDef.kind_key == data.kind_key)
            )
        }
        if sorted(data.ids) != sorted(rows) or len(set(data.ids)) != len(data.ids):
            raise _invalid("ids", "List each of the kind's custom fields once.")
        for index, field_id in enumerate(data.ids, start=1):
            key = f"{index:06d}"
            if rows[field_id].sort_key != key:
                rows[field_id].sort_key = key
        self.session.flush()
        recorder.describe(self.session, "Reordered fields")
        return CustomFieldList(items=[self.out(rows[field_id]) for field_id in data.ids])
