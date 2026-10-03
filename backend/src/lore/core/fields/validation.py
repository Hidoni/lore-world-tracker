"""Validation of ``entities.fields`` and ``entities.field_visibility`` (``data-model.md`` §4).

``KindFields`` is the validation model of one kind, built from its field definitions (own fields
plus the contributions of enabled modules) and the field types the vault has. Writes are merges:
a key set to ``null`` removes the value (or the visibility override). Keys the kind doesn't
offer are rejected, except that stored values of archived fields, of fields contributed by
disabled modules and of fields whose type is unavailable are **preserved**: writes never touch
them and reads hide them (``KindFields.visible``), so re-enabling a module brings them back.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lore.core.db.base import VISIBILITIES
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.fields.values import CORE_VALIDATORS, Validator
from lore.core.registry.types import FieldDef, FieldTypeDef


def _accept(value: Any, _field: FieldDef) -> Any:
    return value


def validators_for(field_types: Sequence[FieldTypeDef]) -> dict[str, Validator]:
    """The validator of each available field type: core's own, or the module type's
    ``validate`` (any JSON value when it has none)."""
    return {
        field_type.key: CORE_VALIDATORS.get(field_type.key, field_type.validate or _accept)
        for field_type in field_types
    }


def _is_empty(value: Any) -> bool:
    return value is None or value in ("", [])


@dataclass(frozen=True)
class KindFields:
    active: Mapping[str, FieldDef]  # the fields a write may set and a read shows
    validators: Mapping[str, Validator]

    @classmethod
    def build(cls, fields: Sequence[FieldDef], field_types: Sequence[FieldTypeDef]) -> KindFields:
        validators = validators_for(field_types)
        return cls(
            active={
                field.key: field
                for field in fields
                if not field.archived and field.type in validators
            },
            validators=validators,
        )

    def visible(self, stored: Mapping[str, Any]) -> dict[str, Any]:
        """The stored values (or visibility overrides) of active fields."""
        return {key: value for key, value in stored.items() if key in self.active}

    def merge_values(self, stored: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
        """``stored`` with ``changes`` applied, every changed value validated and normalized.
        Every active required field must have a value afterwards, on every save (also when an
        entity predates the field becoming required). Raises ``InvalidInputError`` listing each
        problem (paths ``fields.<key>``)."""
        result = dict(stored)
        errors: list[ErrorItem] = []
        for key, value in changes.items():
            path = f"fields.{key}"
            field = self.active.get(key)
            if field is None:
                errors.append(_error(path, "unknown_field", f"{key!r} is not a field of this kind"))
            elif value is None:
                result.pop(key, None)
            else:
                try:
                    result[key] = self._validate(field, value)
                except ValueError as exc:
                    errors.append(_error(path, "invalid_value", str(exc)))
        for key, field in self.active.items():
            if field.required and _is_empty(result.get(key)) and not _has_error(errors, key):
                errors.append(_error(f"fields.{key}", "required", f"{field.label} is required"))
        if errors:
            raise InvalidInputError("Some field values are invalid.", errors=errors)
        return result

    def merge_visibility(
        self, stored: Mapping[str, Any], changes: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Per-field visibility overrides (``null`` removes one: the field's
        ``default_visibility`` applies again)."""
        result = dict(stored)
        errors: list[ErrorItem] = []
        for key, value in changes.items():
            path = f"field_visibility.{key}"
            if key not in self.active:
                errors.append(_error(path, "unknown_field", f"{key!r} is not a field of this kind"))
            elif value is None:
                result.pop(key, None)
            elif value not in VISIBILITIES:
                errors.append(_error(path, "invalid_value", "must be public, spoiler or private"))
            else:
                result[key] = value
        if errors:
            raise InvalidInputError("Some field visibilities are invalid.", errors=errors)
        return result

    def _validate(self, field: FieldDef, value: Any) -> Any:
        validate = self.validators[field.type]
        if not field.multiple or field.type == "multi_enum":
            return validate(value, field)
        if not isinstance(value, list):
            raise ValueError("must be a list (the field takes several values)")
        items = []
        for index, item in enumerate(value):
            try:
                items.append(validate(item, field))
            except ValueError as exc:
                raise ValueError(f"item {index}: {exc}") from exc
        return items


def _error(path: str, code: str, message: str) -> ErrorItem:
    return {"path": path, "code": code, "message": message}


def _has_error(errors: list[ErrorItem], key: str) -> bool:
    return any(error["path"] == f"fields.{key}" for error in errors)
