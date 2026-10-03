"""The vault manager: registry scan, create/rename/trash, locks and per-vault engines.

Data directory layout (``docs/architecture/persistence-and-migrations.md`` §1)::

    <data dir>/vaults/<slug>-<first 8 chars of id>/{vault.json, lore.db, .lock, ...}
    <data dir>/trash/<folder>-<UTC timestamp>/       deleted vaults (never removed)

A read-only manager (``LORE_READ_ONLY=true``) never creates, writes or locks anything, opens
databases with ``mode=ro`` (published snapshots also ``immutable=1``) and only sees the vaults
listed in ``LORE_EXPOSED_VAULTS`` (ids or folder names; empty = all).
"""

import logging
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from lore import __version__
from lore.core.db import create_vault_engine, optimize
from lore.core.db.migrate import (
    Migrator,
    SchemaState,
    SchemaStatus,
    backup_database,
)
from lore.core.errors import InvalidInputError, ReadOnlyError
from lore.core.vaults.errors import (
    VaultMigrationFailedError,
    VaultNeedsMigrationError,
    VaultNewerThanAppError,
    VaultNotFoundError,
)
from lore.core.vaults.format import (
    DATABASE_NAME,
    FORMAT_VERSION,
    ID_PREFIX_LENGTHS,
    LOCK_NAME,
    MANIFEST_NAME,
    ManifestError,
    NewerFormatError,
    VaultManifest,
    VaultName,
    folder_candidates,
    is_valid_folder_name,
    is_valid_vault_id,
    read_manifest,
    write_manifest,
)
from lore.core.vaults.lock import VaultLock
from lore.core.vaults.meta import get_meta, set_meta

logger = logging.getLogger(__name__)

_vault_name: TypeAdapter[str] = TypeAdapter(VaultName)


@dataclass(frozen=True)
class VaultInfo:
    """A vault found by the registry scan."""

    manifest: VaultManifest
    folder: str
    path: Path
    needs_format_upgrade: bool = False

    @property
    def id(self) -> str:
        return self.manifest.vault_id

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def database_path(self) -> Path:
        return self.path / DATABASE_NAME

    @property
    def modified_at(self) -> datetime:
        """When the vault last changed, from file times: ``vault.json`` (renames), ``lore.db`` and
        a non-empty ``lore.db-wal`` (writes not yet checkpointed). An empty WAL file only means a
        connection is open, so it doesn't count."""
        times: list[int] = []
        for path in (self.path / MANIFEST_NAME, self.database_path):
            with suppress(OSError):
                times.append(path.stat().st_mtime_ns)
        with suppress(OSError):
            wal = self.path / f"{DATABASE_NAME}-wal"
            stat = wal.stat()
            if stat.st_size > 0:
                times.append(stat.st_mtime_ns)
        if not times:
            return self.manifest.created_at
        return datetime.fromtimestamp(max(times) / 1e9, UTC)


type VaultProblemCode = Literal[
    "folder_name_invalid", "manifest_invalid", "format_newer_than_app", "duplicate_id"
]


@dataclass(frozen=True)
class VaultProblem:
    """A folder in ``vaults/`` that can't be used as a vault, and why. Listed, never hidden, so
    a damaged or copied vault doesn't look deleted.

    ``code``: ``folder_name_invalid``, ``manifest_invalid`` (``vault.json`` missing, unreadable
    or invalid), ``format_newer_than_app`` or ``duplicate_id``.
    """

    folder: str
    code: VaultProblemCode
    detail: str
    vault_id: str | None = None
    name: str | None = None


@dataclass
class Registry:
    vaults: dict[str, VaultInfo] = field(default_factory=dict)
    problems: list[VaultProblem] = field(default_factory=list)

    def sorted_vaults(self) -> list[VaultInfo]:
        """Most recently modified first; ties by name (case-insensitive), then id."""
        keyed = [(info.modified_at, info) for info in self.vaults.values()]
        keyed.sort(key=lambda pair: (pair[1].name.casefold(), pair[1].id))
        keyed.sort(key=lambda pair: pair[0], reverse=True)  # stable: ties keep the name order
        return [info for _, info in keyed]


def _primary_first(info: VaultInfo) -> tuple[bool, str]:
    """Sort key among folders sharing an id: the folder ``create`` made (its name ends with an id
    prefix; renaming a vault never changes it) first, then by folder name."""
    made_by_create = any(info.folder.endswith(f"-{info.id[:n]}") for n in ID_PREFIX_LENGTHS)
    return (not made_by_create, info.folder)


@dataclass
class OpenVault:
    """An opened vault: its engine and session factory (``expire_on_commit=False``)."""

    info: VaultInfo
    engine: Engine
    read_only: bool
    sessions: sessionmaker[Session] = field(init=False)

    def __post_init__(self) -> None:
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @property
    def id(self) -> str:
        return self.info.id


type VaultSchemaState = Literal[
    "current", "needs_migration", "newer_than_app", "migration_failed", "database_unreadable"
]


@dataclass(frozen=True)
class VaultSchema:
    """Where a vault's database stands relative to this app's migrations."""

    state: VaultSchemaState
    revision: str | None
    head: str


@dataclass(frozen=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str
    backup: Path | None  # None when nothing had to be migrated


@dataclass(frozen=True)
class _Failure:
    detail: str
    backup: Path


class VaultManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        read_only: bool = False,
        exposed_vaults: Iterable[str] = (),
        auto_migrate: bool = True,
        migrator: Migrator | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.read_only = read_only
        self.exposed_vaults = frozenset(exposed_vaults)
        self.auto_migrate = auto_migrate
        self.migrator = migrator or Migrator()
        self._guard = threading.RLock()
        self._open: dict[str, OpenVault] = {}
        self._locks: dict[str, VaultLock] = {}
        # Vaults whose migration failed in this process: unusable until restart (§3.3).
        self._failed: dict[str, _Failure] = {}

    @property
    def vaults_dir(self) -> Path:
        return self.data_dir / "vaults"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    # --- registry -----------------------------------------------------------------------------

    def _is_exposed(self, vault_id: str, folder: str) -> bool:
        if not self.read_only or not self.exposed_vaults:
            return True
        return vault_id in self.exposed_vaults or folder in self.exposed_vaults

    def _scan(self) -> Registry:
        """Read ``vaults/*/vault.json``.

        Nothing is hidden: a folder that can't be used is reported as a :class:`VaultProblem`
        (and logged). If several folders carry the same vault id (a copied folder), the one whose
        name ends with the id's prefix wins (the folder ``create`` made), then the first by
        folder name; the others are ``duplicate_id`` problems.
        """
        registry = Registry()
        if not self.vaults_dir.is_dir():
            return registry
        by_id: dict[str, list[VaultInfo]] = {}
        for entry in sorted(self.vaults_dir.iterdir()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            if not is_valid_folder_name(entry.name):
                self._report(
                    registry,
                    VaultProblem(
                        entry.name,
                        "folder_name_invalid",
                        "Vault folder names may only contain a-z, 0-9 and '-'.",
                    ),
                )
                continue
            try:
                manifest, upgraded = read_manifest(entry)
            except NewerFormatError as exc:
                self._report(registry, VaultProblem(entry.name, "format_newer_than_app", str(exc)))
                continue
            except ManifestError as exc:
                self._report(registry, VaultProblem(entry.name, "manifest_invalid", str(exc)))
                continue
            if self._is_exposed(manifest.vault_id, entry.name):
                info = VaultInfo(manifest, entry.name, entry, upgraded)
                by_id.setdefault(manifest.vault_id, []).append(info)
        for vault_id, infos in by_id.items():
            primary, *copies = sorted(infos, key=_primary_first)
            registry.vaults[vault_id] = primary
            for copy in copies:
                self._report(
                    registry,
                    VaultProblem(
                        copy.folder,
                        "duplicate_id",
                        f"Vault id {vault_id} is also used by folder {primary.folder}"
                        " (a copied vault folder); only that one can be opened.",
                        vault_id=vault_id,
                        name=copy.name,
                    ),
                )
        registry.problems.sort(key=lambda problem: problem.folder)
        return registry

    def _report(self, registry: Registry, problem: VaultProblem) -> None:
        if self._is_exposed(problem.vault_id or "", problem.folder):
            logger.warning("vault folder %s: %s", problem.folder, problem.detail)
            registry.problems.append(problem)

    def list_vaults(self) -> list[VaultInfo]:
        """All usable vaults, most recently modified first (see ``Registry.sorted_vaults``)."""
        return self.registry().sorted_vaults()

    def registry(self) -> Registry:
        """The usable vaults and the folders that can't be used (``problems``)."""
        return self._scan()

    def get(self, vault_id: str) -> VaultInfo:
        if not is_valid_vault_id(vault_id):
            raise VaultNotFoundError(f"No vault with id {vault_id!r}.")
        with self._guard:
            if vault_id in self._open:
                return self._open[vault_id].info
        info = self._scan().vaults.get(vault_id)
        if info is None:
            raise VaultNotFoundError(f"No vault with id {vault_id!r}.")
        return info

    def resolve(self, reference: str) -> VaultInfo:
        """A vault by id or folder name (CLI arguments)."""
        if is_valid_vault_id(reference):
            return self.get(reference)
        for info in self._scan().vaults.values():
            if info.folder == reference:
                return info
        raise VaultNotFoundError(f"No vault with id or folder {reference!r}.")

    def schema_status(self, info: VaultInfo) -> VaultSchema:
        """The vault's schema state, read without opening (or writing) it."""
        head = self.migrator.head()
        failure = self._failed.get(info.id)
        if info.id in self._open:
            return VaultSchema("current", head, head)
        try:
            status = self.migrator.status_of(info.database_path)
        except Exception:
            logger.warning("cannot read the database of vault %s", info.id, exc_info=True)
            return VaultSchema("database_unreadable", None, head)
        if failure is not None:
            return VaultSchema("migration_failed", status.revision, head)
        return VaultSchema(status.state.value, status.revision, head)

    # --- writes -------------------------------------------------------------------------------

    def _require_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyError("Vaults can't be changed on a read-only server.")

    def create(self, name: str) -> VaultInfo:
        """Create ``vaults/<folder>/`` with ``vault.json`` and a database migrated to head.

        The folder is assembled under a hidden staging name and renamed into place, so a crash
        never leaves a half-created vault in the registry.
        """
        self._require_writable()
        manifest = VaultManifest(
            format_version=FORMAT_VERSION,
            vault_id=str(uuid.uuid7()),
            name=_vault_name.validate_python(name),
            created_at=datetime.now(UTC),
            created_by_app_version=__version__,
            published=False,
        )
        self.vaults_dir.mkdir(parents=True, exist_ok=True)
        staging = self.vaults_dir / f".creating-{manifest.vault_id}"
        staging.mkdir()
        try:
            write_manifest(staging, manifest)
            _create_database(staging / DATABASE_NAME)
            self.migrator.upgrade(
                staging / DATABASE_NAME, attributes={"vault": _vault_identity(manifest)}
            )
            with self._guard:
                folder = next(
                    candidate
                    for candidate in folder_candidates(manifest.name, manifest.vault_id)
                    if not (self.vaults_dir / candidate).exists()
                )
                staging.rename(self.vaults_dir / folder)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        logger.info("created vault %s (%s)", manifest.vault_id, folder)
        return VaultInfo(manifest, folder, self.vaults_dir / folder)

    def rename(self, vault_id: str, name: str) -> VaultInfo:
        """Change the display name. The folder name stays as it was created."""
        self._require_writable()
        new_name = _vault_name.validate_python(name)
        with self._guard:
            info = self.get(vault_id)
            self._lock(info)
            renamed = replace(
                info,
                manifest=info.manifest.model_copy(update={"name": new_name}),
                needs_format_upgrade=False,
            )
            write_manifest(info.path, renamed.manifest)
            if vault_id in self._open:
                self._open[vault_id].info = renamed
                _sync_meta_name(self._open[vault_id])
            return renamed

    def trash(self, vault_id: str) -> Path:
        """Move the vault folder to ``trash/<folder>-<UTC timestamp>`` (never deletes it).
        Returns the new location."""
        self._require_writable()
        with self._guard:
            info = self.get(vault_id)
            lock = self._lock(info)
            self._close_engine(vault_id)
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            target = self.trash_dir / f"{info.folder}-{stamp}"
            suffix = 1
            while target.exists():
                suffix += 1
                target = self.trash_dir / f"{info.folder}-{stamp}-{suffix}"
            info.path.rename(target)
            lock.moved_to(target / LOCK_NAME)
            lock.release()
            del self._locks[vault_id]
        logger.info("moved vault %s to %s", vault_id, target)
        return target

    # --- opening ------------------------------------------------------------------------------

    def _lock(self, info: VaultInfo) -> VaultLock:
        """This process's lock on the vault, acquired on first use and kept until close."""
        lock = self._locks.get(info.id)
        if lock is None:
            lock = VaultLock.acquire(info.path / LOCK_NAME)
            self._locks[info.id] = lock
        return lock

    def open(self, vault_id: str) -> OpenVault:
        """The opened vault (cached).

        Author mode takes the lock, runs vault-format upgraders, then compares the schema
        revision with head: newer → ``409 vault_newer_than_app``; older → migrate (with a
        pre-migration backup) or, with auto-migration off, ``409 vault_needs_migration``.
        Read-only mode only reads, and refuses vaults that aren't at head.
        """
        with self._guard:
            opened = self._open.get(vault_id)
            if opened is not None:
                return opened
            info = self.get(vault_id)
            self._raise_if_failed(vault_id)
            if self.read_only:
                self._require_current(self.migrator.status_of(info.database_path))
                engine = create_vault_engine(
                    info.database_path, read_only=True, immutable=info.manifest.published
                )
            else:
                self._lock(info)
                if info.needs_format_upgrade:
                    write_manifest(info.path, info.manifest)
                    info = replace(info, needs_format_upgrade=False)
                status = self.migrator.status_of(info.database_path)
                if status.state is SchemaState.NEEDS_MIGRATION and self.auto_migrate:
                    self._migrate(info, status, status.head)
                else:
                    self._require_current(status)
                engine = create_vault_engine(info.database_path)
            opened = OpenVault(info, engine, self.read_only)
            if not self.read_only:
                _sync_meta_name(opened)
            self._open[vault_id] = opened
            return opened

    def migrate(self, vault_id: str, target: str = "head") -> MigrationResult:
        """Upgrade the vault's database to ``target`` (a revision id or ``head``), after a
        pre-migration backup. A vault already at the target is left alone."""
        self._require_writable()
        with self._guard:
            info = self.get(vault_id)
            self._raise_if_failed(vault_id)
            self._lock(info)
            status = self.migrator.status_of(info.database_path)
            if status.state is SchemaState.NEWER_THAN_APP:
                self._require_current(status)
            to_revision = status.head if target == "head" else target
            if to_revision == status.revision:
                return MigrationResult(status.revision, to_revision, None)
            if not self.migrator.is_ahead(to_revision, status.revision):
                raise InvalidInputError(
                    f"{target!r} is not a revision after the vault's current revision "
                    f"({status.revision or 'none'}); downgrades are done by restoring a backup."
                )
            return self._migrate(info, status, to_revision)

    def _migrate(self, info: VaultInfo, status: SchemaStatus, target: str) -> MigrationResult:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = (
            info.path
            / "backups"
            / "auto"
            / f"pre-migrate-{status.revision or 'base'}-to-{target}-{stamp}.db"
        )
        self._close_engine(info.id)
        backup_database(info.database_path, backup)
        logger.info("migrating vault %s from %s to %s", info.id, status.revision, target)
        try:
            self.migrator.upgrade(
                info.database_path, target, attributes={"vault": _vault_identity(info.manifest)}
            )
        except Exception as exc:
            detail = (
                f"Migrating vault {info.name!r} from {status.revision or 'base'} to {target} "
                f"failed: {exc}. The database was left untouched; a backup is at {backup}."
            )
            logger.exception("migration of vault %s failed", info.id)
            self._failed[info.id] = _Failure(detail, backup)
            raise VaultMigrationFailedError(
                detail, context={"backup": str(backup), "error": str(exc)}
            ) from exc
        return MigrationResult(status.revision, target, backup)

    def _raise_if_failed(self, vault_id: str) -> None:
        failure = self._failed.get(vault_id)
        if failure is not None:
            raise VaultMigrationFailedError(
                failure.detail + " Restart the app to try again.",
                context={"backup": str(failure.backup)},
            )

    def _require_current(self, status: SchemaStatus) -> None:
        if status.state is SchemaState.NEWER_THAN_APP:
            raise VaultNewerThanAppError(
                f"The vault's schema revision {status.revision} is unknown to this app version "
                f"(head {status.head}): it was written by a newer version.",
                context={"revision": status.revision, "head": status.head},
            )
        if status.state is SchemaState.NEEDS_MIGRATION:
            raise VaultNeedsMigrationError(
                f"The vault's schema ({status.revision or 'empty'}) is older than this app's "
                f"({status.head}). Migrate it first.",
                context={"revision": status.revision, "head": status.head},
            )

    def _close_engine(self, vault_id: str) -> None:
        opened = self._open.pop(vault_id, None)
        if opened is None:
            return
        if not opened.read_only:
            try:
                optimize(opened.engine)
            except Exception:
                logger.warning("PRAGMA optimize failed for vault %s", vault_id, exc_info=True)
        opened.engine.dispose()

    def close(self) -> None:
        """Dispose every engine and release every lock (app shutdown)."""
        with self._guard:
            for vault_id in list(self._open):
                self._close_engine(vault_id)
            for lock in self._locks.values():
                lock.release()
            self._locks.clear()


def _vault_identity(manifest: VaultManifest) -> dict[str, str]:
    """What the first migration seeds into ``vault_meta``."""
    return {
        "vault_id": manifest.vault_id,
        "name": manifest.name,
        "created_at": manifest.created_at.isoformat(),
    }


def _sync_meta_name(opened: OpenVault) -> None:
    """``vault.json`` is authoritative for the name; ``vault_meta.name`` follows it."""
    with opened.sessions.begin() as session:
        if get_meta(session, "name") != opened.info.name:
            set_meta(session, "name", opened.info.name)


def _create_database(path: Path) -> None:
    """An empty SQLite database in WAL mode (the schema is added by migrations)."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    finally:
        connection.close()
