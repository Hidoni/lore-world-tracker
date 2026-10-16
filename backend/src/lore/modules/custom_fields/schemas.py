"""Request and response models of the custom_fields module (``docs/modules/custom_fields.md``,
API)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from lore.core.consistency.schemas import SuppressIn
from lore.core.db.base import Visibility
from lore.core.entities.schemas import Color
from lore.core.types import Affected

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,59}$")]
KindKey = Annotated[str, StringConstraints(pattern=r"^(\*|[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?)$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Section = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Help = Annotated[str, StringConstraints(max_length=1000)]


class FieldOptionIn(BaseModel):
    key: Slug
    label: Label
    color: Color | None = None


class CustomFieldOut(BaseModel):
    id: str
    kind_key: str = Field(description="A kind's key, or `*`: every kind but the system ones.")
    key: str = Field(description="`custom.<slug>`: the key of the values in `fields`.")
    label: str
    type: str
    options: list[FieldOptionIn]
    multiple: bool
    required: bool
    temporal: bool
    default_visibility: Visibility
    section: str | None
    sort_key: str
    help: str
    searchable: bool
    archived: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    entities_with_values: int = Field(description="Live entities with a value (or a fact).")


class CustomFieldList(BaseModel):
    items: list[CustomFieldOut]


class CustomFieldCreate(SuppressIn):
    kind_key: KindKey
    key: Slug = Field(description="The slug: the field's key is `custom.<slug>`.")
    label: Label
    type: str = Field(description="A field type of the vault (`GET /registry`, `field_types`).")
    options: list[FieldOptionIn] = Field(default_factory=list, description="`enum`, `multi_enum`.")
    multiple: bool = False
    required: bool = False
    temporal: bool = False
    default_visibility: Visibility = "public"
    section: Section | None = None
    help: Help = ""
    searchable: bool = True


type FactsChoice = Literal["drop", "keep"]


class CustomFieldUpdate(SuppressIn):
    """Only the members sent change. ``type`` changes along safe conversions only (``value_map``
    turns each existing text into an option key, or ``null`` to clear it, for text → enum).
    Turning ``temporal`` off with facts needs ``facts``: ``drop`` them (to the trash) or ``keep``
    them (hidden while the field isn't temporal)."""

    revision: int
    label: Label | None = None
    type: str | None = None
    value_map: dict[str, Slug | None] | None = None
    options: list[FieldOptionIn] | None = None
    multiple: bool | None = None
    required: bool | None = None
    temporal: bool | None = None
    facts: FactsChoice | None = None
    default_visibility: Visibility | None = None
    section: Section | None = None
    help: Help | None = None
    searchable: bool | None = None
    archived: bool | None = None


class FieldReorder(BaseModel):
    kind_key: KindKey
    ids: list[str] = Field(min_length=1, description="The kind's fields in their new order.")


class CustomFieldWriteResult(BaseModel):
    field: CustomFieldOut
    affected: Affected


class CustomFieldDeleteResult(BaseModel):
    id: str
    affected: Affected


def option_dicts(options: list[FieldOptionIn]) -> list[dict[str, Any]]:
    return [option.model_dump() for option in options]


# --- custom kinds --------------------------------------------------------------------------------

Icon = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,49}$")]
Description = Annotated[str, StringConstraints(max_length=2000)]


class KindCapabilitiesIn(BaseModel):
    """What entities of the kind can do (``data-model.md`` §3.3); a custom kind always has a
    body and is never time-bound or a system kind."""

    has_existence: bool = True
    can_be_multiversal: bool = True
    can_have_worldline: bool = False


class CustomKindOut(BaseModel):
    key: str = Field(description="`custom.<slug>`: the `kind` of its entities.")
    label: str
    plural: str
    icon: str
    color: str
    description: str
    allowed_parents: list[str]
    capabilities: KindCapabilitiesIn
    default_visibility: Visibility | None
    archived: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    entities: int = Field(description="Entities of the kind (the trash included).")


class CustomKindList(BaseModel):
    items: list[CustomKindOut]


class CustomKindCreate(SuppressIn):
    key: Slug = Field(description="The slug: the kind's key is `custom.<slug>`.")
    label: Label
    plural: Label
    icon: Icon = "box"
    color: Color = "#64748b"
    description: Description = ""
    allowed_parents: list[KindKey] = Field(
        default_factory=list,
        description="Kinds entities of the kind may be nested under (its own key included).",
    )
    capabilities: KindCapabilitiesIn = Field(default_factory=KindCapabilitiesIn)
    default_visibility: Visibility | None = Field(
        default=None, description="New entities' visibility (default: the vault's)."
    )


class CustomKindUpdate(SuppressIn):
    """Only the members sent change. Archiving hides the kind and its entities (nothing is
    deleted)."""

    revision: int
    label: Label | None = None
    plural: Label | None = None
    icon: Icon | None = None
    color: Color | None = None
    description: Description | None = None
    allowed_parents: list[KindKey] | None = None
    capabilities: KindCapabilitiesIn | None = None
    default_visibility: Visibility | None = None
    archived: bool | None = None


class CustomKindWriteResult(BaseModel):
    kind: CustomKindOut
    affected: Affected


class CustomKindDeleteResult(BaseModel):
    key: str
    affected: Affected


class ConvertKind(SuppressIn):
    """Give entities another kind (built-in ↔ custom), in one changeset. ``field_mapping`` moves
    values (and facts, visibility overrides) from a field key to one of the new kind (``null``:
    drop them); unmapped values stay stored, hidden unless the new kind has the field, so
    converting back restores them."""

    entity_ids: list[str] = Field(min_length=1, max_length=500)
    to_kind: KindKey
    field_mapping: dict[str, str | None] = Field(default_factory=dict)


class ConvertKindResult(BaseModel):
    entity_ids: list[str]
    affected: Affected
