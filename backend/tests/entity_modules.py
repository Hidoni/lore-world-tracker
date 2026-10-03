"""Test-only modules for the entity service: a kind with every field type, parent rules, a
toggleable module with a field contribution and a field type, a kind extension and a purge hook.
"""

from typing import Any

from lore.core.entities.extensions import KindExtension
from lore.core.entities.models import Entity
from lore.core.errors import InvalidInputError
from lore.core.modules import ModuleSpec, VaultContext
from lore.core.registry import FieldContribution, FieldDef, FieldOption, FieldTypeDef, KindDef
from lore.core.registry import KindCapabilities as Caps

OPTIONS = (FieldOption("red", "Red"), FieldOption("blue", "Blue"))

EVERY_TYPE = (
    FieldDef("text", "Text", "text"),
    FieldDef("long_text", "Long text", "long_text"),
    FieldDef("rich_text", "Rich text", "rich_text"),
    FieldDef("integer", "Integer", "integer"),
    FieldDef("decimal", "Decimal", "decimal"),
    FieldDef("boolean", "Boolean", "boolean"),
    FieldDef("enum", "Enum", "enum", options=OPTIONS),
    FieldDef("multi_enum", "Multi enum", "multi_enum", options=OPTIONS),
    FieldDef("url", "URL", "url"),
    FieldDef("color", "Color", "color"),
    FieldDef("duration", "Duration", "duration"),
    FieldDef("time_point", "Time point", "time_point"),
    FieldDef("measurement", "Measurement", "measurement"),
    FieldDef("nicknames", "Nicknames", "text", multiple=True),
    FieldDef("secret", "Secret", "text", default_visibility="private"),
)


def _kind(key: str, **values: Any) -> KindDef:
    return KindDef(key, key.title(), key.title() + "s", icon="box", color="#000000", **values)


def _stars(value: Any, _field: FieldDef) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise ValueError("must be 1 to 5 stars")
    return value


EXT_STORE: dict[str, dict[str, Any]] = {}
PURGED: list[str] = []


def _write_ext(
    _context: VaultContext, entity: Entity, ext: dict[str, Any] | None, _new: bool
) -> None:
    if ext is not None and "habitat" not in ext:
        raise InvalidInputError(
            "habitat is required",
            errors=[{"path": "ext.habitat", "code": "required", "message": "habitat is required"}],
        )
    EXT_STORE[entity.id] = ext or {"habitat": "unknown"}


def _read_ext(_context: VaultContext, entity: Entity) -> dict[str, Any] | None:
    return EXT_STORE.get(entity.id)


def _purge_hook(_context: VaultContext, entity: Entity) -> None:
    PURGED.append(entity.id)


WORLD = ModuleSpec(
    id="world",
    name="World",
    description="Kinds for entity tests.",
    kinds=(
        _kind("misc", allowed_parents=("misc",)),
        _kind("gadget", allowed_parents=("gadget", "misc"), fields=EVERY_TYPE),
        _kind(
            "relic",
            allowed_parents=("misc",),
            fields=(
                FieldDef("origin", "Origin", "text", required=True),
                FieldDef("tags", "Tags", "multi_enum", options=OPTIONS),
                FieldDef("old", "Old", "text", archived=True),
            ),
            capabilities=Caps(has_body=False, can_be_multiversal=False),
        ),
    ),
    purge_hooks=(_purge_hook,),
)

EXTRA = ModuleSpec(
    id="extra",
    name="Extra",
    description="Toggleable: a kind with an extension, a contribution and a field type.",
    kinds=(_kind("beast", allowed_parents=("misc",)),),
    field_contributions=(
        FieldContribution(
            "gadget",
            (
                FieldDef("extra.wings", "Wings", "boolean"),
                FieldDef("extra.stars", "Stars", "extra_stars"),
            ),
        ),
    ),
    field_types=(FieldTypeDef("extra_stars", "Stars", validate=_stars),),
    kind_extensions=(KindExtension("beast", write=_write_ext, read=_read_ext),),
)

ENTITY_MODULES = (WORLD, EXTRA)
