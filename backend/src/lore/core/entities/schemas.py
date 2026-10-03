"""API schemas of the generic entity endpoints (``docs/architecture/api.md`` §2, Entities)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lore.core.db.base import Visibility

ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
MAX_NAME_LENGTH = 500

type EntityId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
type EntityName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)
]
type AliasKind = Literal["alias", "title", "former_name", "translation", "nickname"]
type TagName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
type Icon = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type SortKey = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z]+$", max_length=128)]
type Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
type JsonObject = dict[str, Any]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AliasIn(_Input):
    """An alias. Send the ``id`` of an existing alias to keep it (and its history)."""

    id: EntityId | None = None
    alias: EntityName
    alias_kind: AliasKind = "alias"
    visibility: Visibility = "public"


class _EntityWrite(_Input):
    summary: str = ""
    body: JsonObject | None = None
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Field values to set (merged into the stored values; null removes a value).",
    )
    field_visibility: dict[str, Visibility | None] = Field(
        default_factory=dict,
        description="Per-field visibility overrides (merged; null removes an override).",
    )
    icon: Icon | None = None
    color: Color | None = None
    sort_key: SortKey | None = None
    aliases: list[AliasIn] = Field(default_factory=list, max_length=500)
    tags: list[TagName] = Field(default_factory=list, max_length=500)
    ext: JsonObject | None = Field(
        default=None, description="Kind extension data (e.g. a dimension's time spec, M3+)."
    )


class EntityCreate(_EntityWrite):
    kind: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    name: EntityName
    dimension_id: EntityId | None = Field(
        default=None, description="Home dimension; null = multiversal (if the kind allows it)."
    )
    parent_id: EntityId | None = None
    visibility: Visibility | None = Field(
        default=None, description="Defaults to the vault's default visibility."
    )


class EntityUpdate(_EntityWrite):
    """Only the members sent are changed. ``aliases`` and ``tags`` replace the whole list;
    ``fields`` and ``field_visibility`` are merged."""

    revision: int = Field(description="The revision the edit is based on (409 on mismatch).")
    name: EntityName | None = None
    dimension_id: EntityId | None = None
    parent_id: EntityId | None = None
    visibility: Visibility | None = None


class AliasOut(BaseModel):
    id: str
    alias: str
    alias_kind: AliasKind
    visibility: Visibility


class TagOut(BaseModel):
    id: str
    name: str
    color: str | None


class EntityOut(BaseModel):
    """A full entity. ``fields`` and ``field_visibility`` only hold the kind's active fields
    (values of archived fields and of disabled modules' fields are kept but not shown)."""

    id: str
    kind: str
    dimension_id: str | None
    origin_timeline_id: str | None
    parent_id: str | None
    name: str
    slug: str
    summary: str
    body: JsonObject | None
    body_schema_version: int | None
    fields: dict[str, Any]
    field_visibility: dict[str, Visibility]
    visibility: Visibility
    icon: str | None
    color: str | None
    cover_media_id: str | None
    sort_key: str | None
    aliases: list[AliasOut]
    tags: list[TagOut]
    ext: JsonObject | None
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class Affected(BaseModel):
    """What a write changed, for client cache invalidation (``frontend.md`` §5)."""

    entities: list[str]
    dimensions: list[str]
    time_changed: bool
    search_changed: bool


class EntityWriteResult(BaseModel):
    entity: EntityOut
    affected: Affected


class EntityDeleteResult(BaseModel):
    """``entity`` is the trashed entity, or null when it was purged."""

    id: str
    purged: bool
    entity: EntityOut | None
    affected: Affected
