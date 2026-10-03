"""API schemas of links and link types (``docs/architecture/api.md`` §2, Links & link types)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.db.base import Visibility
from lore.core.types import Affected

ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
LINK_TYPE_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
CUSTOM_KEY_PATTERN = r"^custom\.[a-z][a-z0-9_]*$"

type Id = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
type LinkTypeKey = Annotated[str, StringConstraints(pattern=LINK_TYPE_KEY_PATTERN, max_length=200)]
type Role = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
type SortKey = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z]+$", max_length=128)]
type Temporal = Literal["never", "optional", "required"]
type UniquePolicy = Literal["none", "per_pair", "per_pair_per_period"]
type KindKey = Annotated[str, StringConstraints(min_length=1, max_length=100)]
type KindList = Annotated[list[KindKey], Field(min_length=1, max_length=100)] | Literal["*"]
type Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- link types ----------------------------------------------------------------------------------


class GraphStyleOut(BaseModel):
    color: str | None
    dashed: bool
    weight: int


class LinkTypeOut(BaseModel):
    key: str
    module: str  # "core" (incl. user-defined types) or the owning module id
    user_defined: bool
    label: str
    inverse_label: str | None
    description: str
    source_kinds: list[str] | Literal["*"]
    target_kinds: list[str] | Literal["*"]
    symmetric: bool
    temporal: Temporal
    unique: UniquePolicy
    max_targets_per_source: int | None
    max_sources_per_target: int | None
    data_schema: dict[str, Any] | None
    graph: GraphStyleOut
    archived: bool
    revision: int | None = Field(
        default=None, description="User-defined types: the revision a PATCH must send."
    )


class LinkTypeList(BaseModel):
    """Every offered link type (built-in and user-defined), archived ones included."""

    items: list[LinkTypeOut]


class GraphStyleIn(_Input):
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    dashed: bool = False
    weight: Annotated[int, Field(ge=1, le=10)] = 1


class _LinkTypeWrite(_Input):
    inverse_label: Label | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    source_kinds: KindList = "*"
    target_kinds: KindList = "*"
    temporal: Temporal = "optional"
    unique: UniquePolicy = "none"
    max_targets_per_source: Annotated[int, Field(ge=1)] | None = None
    max_sources_per_target: Annotated[int, Field(ge=1)] | None = None
    data_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema (draft 2020-12) that link `data` must match."
    )
    graph: GraphStyleIn = Field(default_factory=GraphStyleIn)


class LinkTypeCreate(_LinkTypeWrite):
    key: Annotated[str, StringConstraints(pattern=CUSTOM_KEY_PATTERN, max_length=100)] | None = (
        Field(default=None, description="`custom.<slug>`; derived from the label when omitted.")
    )
    label: Label
    symmetric: bool = False


class LinkTypeUpdate(_LinkTypeWrite):
    """Only the members sent change. Changes that existing links would break are refused
    (``409 conflict``, ``context.conflicts``)."""

    revision: int
    label: Label | None = None
    symmetric: bool | None = None
    archived: bool | None = None


class LinkTypeDeleted(BaseModel):
    key: str


# --- links ---------------------------------------------------------------------------------------


class _LinkFields(_Input):
    role: Role | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    visibility: Visibility = "public"
    timeline_id: Id | None = Field(
        default=None, description="Required when the link has validity bounds; null = timeless."
    )
    valid_from: TimePoint | None = None
    valid_to: TimePoint | None = None
    sort_key: SortKey | None = None


class LinkCreate(_LinkFields):
    link_type: LinkTypeKey
    source_id: Id
    target_id: Id


class EntityLinkAdd(_LinkFields):
    """A link created with an entity write: give the other end as ``target_id`` (the entity is
    the source) or ``source_id`` (the entity is the target)."""

    link_type: LinkTypeKey
    source_id: Id | None = None
    target_id: Id | None = None


class LinkUpdate(_LinkFields):
    """Only the members sent change. Type and endpoints are fixed (delete and re-create)."""

    revision: int
    data: dict[str, Any] | None = None  # type: ignore[assignment]
    visibility: Visibility | None = None  # type: ignore[assignment]


class LinkOut(BaseModel):
    """A link. Symmetric links are stored with ``source_id < target_id``."""

    id: str
    link_type: str
    source_id: str
    target_id: str
    role: str | None
    data: dict[str, Any]
    visibility: Visibility
    timeline_id: str | None
    valid_from: dict[str, Any] | None
    valid_to: dict[str, Any] | None
    time_status: str | None
    sort_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class LinkedEntity(BaseModel):
    id: str
    kind: str
    name: str
    icon: str | None
    color: str | None
    dimension_id: str | None
    deleted_at: datetime | None


class EntityLink(BaseModel):
    """A link seen from one entity. ``direction``: ``out`` (the entity is the source), ``in`` (the
    target) or ``both`` (symmetric type). ``label`` reads from the entity's side (the inverse
    label for ``in``)."""

    link: LinkOut
    direction: Literal["out", "in", "both"]
    label: str
    other: LinkedEntity


class EntityLinks(BaseModel):
    items: list[EntityLink]


class LinkWriteResult(BaseModel):
    link: LinkOut
    affected: Affected


class LinkDeleteResult(BaseModel):
    """The trashed link."""

    id: str
    link: LinkOut
    affected: Affected


class MentionCountsOut(BaseModel):
    """Mentions in the source's text, by the visibility of the block they're in."""

    public: int
    spoiler: int
    private: int


class Backlink(BaseModel):
    """One entity pointing at this one: its incoming links and its mentions."""

    entity: LinkedEntity
    links: list[EntityLink]
    mentions: MentionCountsOut


class Backlinks(BaseModel):
    items: list[Backlink]
