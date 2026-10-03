"""``ModuleSpec``: everything a module plugs into (``docs/architecture/modules.md`` §2.1).

Extension points whose machinery doesn't exist yet are accepted and stored as opaque objects;
the issue that builds each one replaces its alias with a real protocol:

- ``SlotProvider``, ``TimelineTableSpec``: time core (M3)
- ``SearchContributor``: search (#39)
- ``GraphContributor``: graph module (M8)
- ``VisibilityFilter``: visibility framework (#40)
- ``RichTextNodeHandler``: rich text (#38)
- ``BackupContributor``: backups (#41)
- ``PublishContributor``: published snapshots (M12)
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lore.core.entities.extensions import KindExtension, PurgeHook
from lore.core.registry.types import (
    FieldContribution,
    FieldTypeDef,
    KindDef,
    LinkTypeDef,
    RuleDef,
)

if TYPE_CHECKING:
    from lore.core.modules.registry import ModuleRegistry
    from lore.core.vaults import OpenVault

type SlotProvider = object
type TimelineTableSpec = object
type SearchContributor = object
type GraphContributor = object
type VisibilityFilter = object
type RichTextNodeHandler = object
type BackupContributor = object
type PublishContributor = object


@dataclass(frozen=True)
class VaultContext:
    """What ``on_enable``/``on_disable`` hooks get: the vault, the request's session (inside its
    transaction) and the registry."""

    vault: OpenVault
    session: Session
    registry: ModuleRegistry


@dataclass(frozen=True)
class ModuleSpec:
    id: str  # ^[a-z][a-z0-9_]*$
    name: str
    description: str
    depends_on: tuple[str, ...] = ()
    default_enabled: bool = True
    kinds: tuple[KindDef, ...] = ()
    field_contributions: tuple[FieldContribution, ...] = ()  # fields on other modules' kinds
    field_types: tuple[FieldTypeDef, ...] = ()  # e.g. the media module's ``media`` type
    link_types: tuple[LinkTypeDef, ...] = ()  # keys start with "<id>."
    # SQLAlchemy model classes of the module's tables (names start with "<id>_"). Listed
    # explicitly so the registry can validate them and include them in the migration metadata.
    models: tuple[type, ...] = ()
    routers: tuple[APIRouter, ...] = ()  # mounted at /api/v1/vaults/{vault_id}/m/<id>/
    slot_providers: tuple[SlotProvider, ...] = ()
    timeline_tables: tuple[TimelineTableSpec, ...] = ()
    search_contributors: tuple[SearchContributor, ...] = ()
    graph_contributors: tuple[GraphContributor, ...] = ()
    consistency_rules: tuple[RuleDef, ...] = ()  # ids start with "<id>."
    visibility_filters: tuple[VisibilityFilter, ...] = ()
    richtext_nodes: tuple[RichTextNodeHandler, ...] = ()
    backup_contributors: tuple[BackupContributor, ...] = ()
    publish_contributors: tuple[PublishContributor, ...] = ()
    kind_extensions: tuple[KindExtension, ...] = ()  # ``ext`` data of a kind (one per kind)
    purge_hooks: tuple[PurgeHook, ...] = ()  # run before any entity is purged
    settings_model: type[BaseModel] | None = None
    on_enable: Callable[[VaultContext], None] | None = None
    on_disable: Callable[[VaultContext], None] | None = None
