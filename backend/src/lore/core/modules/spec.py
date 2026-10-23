"""``ModuleSpec``: everything a module plugs into (``docs/architecture/modules.md`` §2.1).

Extension points whose machinery doesn't exist yet are accepted and stored as opaque objects;
the issue that builds each one replaces its alias with a real protocol:

- ``TimelineTableSpec``: time core (M3)
- ``GraphContributor``: graph module (M8)
- ``BackupContributor``: backups (#41)
- ``PublishContributor``: published snapshots (M12)
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lore.core.entities.extensions import KindExtension, PurgeHook
from lore.core.history.tables import HistoryTable
from lore.core.registry.types import (
    FieldContribution,
    FieldDef,
    FieldTypeDef,
    KindDef,
    LinkTypeDef,
    RuleDef,
)
from lore.core.richtext.handlers import RichTextNodeHandler
from lore.core.visibility.filters import VisibilityFilter

if TYPE_CHECKING:
    from lore.core.history.recorder import RecordedChange
    from lore.core.interchange.spec import InterchangeTable
    from lore.core.maintenance.checks import DerivedDataCheck
    from lore.core.markdown.export import MarkdownExport
    from lore.core.modules.registry import ModuleRegistry
    from lore.core.search.documents import SearchContributor
    from lore.core.time.slots import SlotProvider
    from lore.core.vaults import OpenVault
    from lore.core.vaults.publish import PublishContext
    from lore.core.visibility import VisibilityPolicy

type TimelineTableSpec = object
type GraphContributor = object
type BackupContributor = object
# Sanitizes a module's part of a published snapshot and copies its files (media), given the
# snapshot's session and the source and target vault folders (``lore.core.vaults.publish``).
type PublishContributor = Callable[["PublishContext"], None]
# Adds a module's part to a Markdown export (``lore.core.markdown.export``): files (media) and how
# its rich-text nodes, field types and covers render. Runs before any note is written.
type MarkdownContributor = Callable[["MarkdownExport"], None]
# What a static export's browser computes a module's views from, when recording each setting
# would multiply (ADR 0016, #386: family trees, the graph): given the snapshot (a reader's
# context and policy) and, per timeline, every moment its records can change at, JSON files by
# name, written to ``static/m/<module id>/<name>``.
type StaticData = Callable[
    ["VaultContext", "VisibilityPolicy", Mapping[str, Sequence[int]]], Mapping[str, Any]
]
# Rebuilds a module's derived rows from the changes a changeset is about to record (``media_refs``
# from bodies, fields and covers); runs before the consistency check, undo included. Raising a
# typed error refuses the write.
type DerivedHook = Callable[["VaultContext", Sequence["RecordedChange"]], None]
# Fields a vault keeps in its database (the custom_fields module's custom fields): given the
# vault's kind keys, the fields to add to each (by kind key). Read on every request that builds the
# vault's kinds (``ModuleRegistry.vault_kinds``), so it must be one cheap query.
type FieldProvider = Callable[[Session, Sequence[str]], Mapping[str, Sequence[FieldDef]]]
# Kinds a module keeps in the vault's database (the custom_fields module's custom kinds): the live
# (not archived) ones, read like ``FieldProvider``s on every request that builds the vault's kinds.
type KindProvider = Callable[[Session], Sequence[KindDef]]
# A daily job per open vault in author mode (the media module's garbage collection); ``now`` is
# the scheduler's clock.
type MaintenanceTask = Callable[["VaultContext", datetime], None]


type Params = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class StaticRead:
    """A read of the module that a static export records (``visibility-and-sharing.md`` §8, ADR
    0016), declared so the builder never imports modules: the route ``path`` under the
    module's routes (``m/<id>/``), once per id when it holds ``{id}``, for each query in
    ``variants`` (as the app sends them; ``{id}`` there is filled too).

    Ids are the listed entities of ``kind`` (``"*"``: any kind), or the ``id`` of each item of
    another recorded read (``ids_from``: its path, items under ``items``). ``dimension`` adds
    each dimension (``dimension=``); ``timeline`` each timeline the entity can be seen in
    (``timeline=``); ``as_of`` also each moment as-of answers can change there (``timeline`` and
    ``at``); ``event_moments``: it shows events only while they happen (a map's pins of
    events), so it changes around their starts and ends too. A ``paged`` read is recorded whole
    (every page at the largest ``limit``) for the browser to filter and page. A ``file`` read
    is a download (a media file, a CSV), copied as it is."""

    path: str
    kind: str | None = None
    ids_from: str | None = None
    variants: tuple[Params, ...] = ((),)
    dimension: bool = False
    timeline: bool = False
    as_of: bool = False
    paged: int | None = None
    file: bool = False
    event_moments: bool = False


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
    field_providers: tuple[FieldProvider, ...] = ()  # per-vault fields (custom fields)
    kind_providers: tuple[KindProvider, ...] = ()  # per-vault kinds (custom kinds)
    link_types: tuple[LinkTypeDef, ...] = ()  # keys start with "<id>."
    # SQLAlchemy model classes of the module's tables (names start with "<id>_"). Listed
    # explicitly so the registry can validate them and include them in the migration metadata.
    models: tuple[type, ...] = ()
    # How history treats each model's table (every one must be listed; derived=True: not recorded)
    history_tables: tuple[HistoryTable, ...] = ()
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
    markdown_contributors: tuple[MarkdownContributor, ...] = ()  # Markdown export (media files)
    # How its tables travel in interchange documents beyond their rows: keys, files (media)
    interchange_tables: tuple[InterchangeTable, ...] = ()
    static_reads: tuple[StaticRead, ...] = ()  # reads a static export records (ADR 0016)
    static_data: StaticData | None = None  # data a static export computes views from (#386)
    kind_extensions: tuple[KindExtension, ...] = ()  # ``ext`` data of a kind (one per kind)
    purge_hooks: tuple[PurgeHook, ...] = ()  # run before any entity is purged
    derived_hooks: tuple[DerivedHook, ...] = ()  # rebuild derived rows on every changeset
    maintenance_tasks: tuple[MaintenanceTask, ...] = ()  # daily, per open vault (authors)
    # Run by ``lore vault check`` / ``reindex`` after core's (``lore.core.maintenance``).
    derived_checks: tuple[DerivedDataCheck, ...] = ()
    settings_model: type[BaseModel] | None = None
    on_enable: Callable[[VaultContext], None] | None = None
    on_disable: Callable[[VaultContext], None] | None = None
