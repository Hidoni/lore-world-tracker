"""Vault backups and restore (``persistence-and-migrations.md`` §5, ``security.md`` §3).

A backup is a zip::

    manifest.json   {format_version, app_version, schema_revision, vault: {...vault.json},
                     created_at, includes_media, kind, reason, files: {<path>: <sha256>}}
    lore.db         a consistent, compact copy made with ``VACUUM INTO``
    media/...       the vault's media folder, when included

Backups live in the vault folder: ``backups/manual/<id>.zip`` (asked for by the author) and
``backups/auto/<id>.zip`` (scheduled ones and those taken before destructive operations). The id
is the file name without ``.zip``: ``<kind>-<UTC yyyymmdd-hhmmss>`` (``-2``, ``-3``, … on a
clash), where kind is ``manual``, ``scheduled`` or ``pre-<reason>``. Pre-migration backups stay
plain ``.db`` files (``backups/auto/pre-migrate-*.db``) and aren't listed here.

Restoring never touches an existing vault: the zip is validated (manifest, entry names, sizes,
file count, checksums) while it is extracted into a staging folder, which becomes a new vault.
"""

import hashlib
import json
import logging
import re
import shutil
import stat
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lore import __version__
from lore.core.db.migrate import backup_database
from lore.core.errors import InvalidInputError
from lore.core.vaults.format import DATABASE_NAME

logger = logging.getLogger(__name__)

BACKUP_FORMAT_VERSION: Final = 1
MANIFEST = "manifest.json"
MEDIA_DIR = "media"
BACKUP_ID_PATTERN = r"^[a-z0-9-]{1,120}$"
_BACKUP_ID = re.compile(BACKUP_ID_PATTERN)
_REASON = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_STAMP = "%Y%m%d-%H%M%S"
_CHUNK = 1 << 20

type BackupKind = Literal["manual", "scheduled", "pre"]


class InvalidBackupError(InvalidInputError):
    """The zip isn't a usable backup (or is unsafe to extract)."""

    code = "invalid_backup"
    title = "Invalid backup"


@dataclass(frozen=True)
class RestoreLimits:
    """Caps applied while extracting (zip bombs, file-count exhaustion)."""

    max_files: int = 200_000
    max_bytes: int = 64 * 1024**3


DEFAULT_LIMITS = RestoreLimits()


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    format_version: Literal[1]
    app_version: str
    schema_revision: str | None
    vault: dict[str, Any]
    created_at: datetime
    includes_media: bool
    kind: str = "manual"
    reason: str | None = None
    files: dict[str, str] = Field(description="sha256 (hex) of every other file in the zip")


@dataclass(frozen=True)
class BackupInfo:
    id: str
    kind: str
    reason: str | None
    created_at: datetime
    size: int
    includes_media: bool
    app_version: str
    schema_revision: str | None
    path: Path


def is_valid_backup_id(value: str) -> bool:
    return _BACKUP_ID.fullmatch(value) is not None


def backup_dirs(vault_path: Path) -> dict[str, Path]:
    return {"manual": vault_path / "backups" / "manual", "auto": vault_path / "backups" / "auto"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _media_files(vault_path: Path) -> Iterator[tuple[str, Path]]:
    """(archive name, path) of every regular file under ``media/`` (symlinks are skipped)."""
    root = vault_path / MEDIA_DIR
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        yield PurePosixPath(MEDIA_DIR, *path.relative_to(root).parts).as_posix(), path


def _free_id(directory: Path, prefix: str, now: datetime) -> str:
    base = f"{prefix}-{now.strftime(_STAMP)}"
    candidate, suffix = base, 1
    while (directory / f"{candidate}.zip").exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def create_backup(
    vault_path: Path,
    vault_manifest: dict[str, Any],
    schema_revision: str | None,
    *,
    include_media: bool,
    kind: BackupKind = "manual",
    reason: str | None = None,
) -> Path:
    """Write a backup zip of the vault (database copy via ``VACUUM INTO``) and return its path.
    The zip is assembled under a hidden name and renamed into place when complete."""
    if (kind == "pre") != (reason is not None):
        raise ValueError("a reason is required for (and only for) pre-operation backups")
    if reason is not None and _REASON.fullmatch(reason) is None:
        raise ValueError(f"invalid backup reason {reason!r}: use lowercase words and hyphens")
    now = datetime.now(UTC)
    directory = backup_dirs(vault_path)["manual" if kind == "manual" else "auto"]
    directory.mkdir(parents=True, exist_ok=True)
    backup_id = _free_id(directory, f"pre-{reason}" if reason else kind, now)
    target = directory / f"{backup_id}.zip"
    staging = directory / f".{backup_id}.partial"
    staging.mkdir()
    try:
        database = staging / DATABASE_NAME
        backup_database(vault_path / DATABASE_NAME, database)
        files = {DATABASE_NAME: _sha256(database)}
        partial = staging / "backup.zip"
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.write(database, DATABASE_NAME)
            if include_media:
                for name, path in _media_files(vault_path):
                    digest = hashlib.sha256()
                    with (
                        path.open("rb") as source,
                        archive.open(name, "w", force_zip64=True) as out,
                    ):
                        while chunk := source.read(_CHUNK):
                            digest.update(chunk)
                            out.write(chunk)
                    files[name] = digest.hexdigest()
            manifest = BackupManifest(
                format_version=BACKUP_FORMAT_VERSION,
                app_version=__version__,
                schema_revision=schema_revision,
                vault=vault_manifest,
                created_at=now,
                includes_media=include_media,
                kind=kind,
                reason=reason,
                files=files,
            )
            archive.writestr(MANIFEST, manifest.model_dump_json(indent=2))
        partial.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info("wrote backup %s", target)
    return target


def read_manifest(archive: zipfile.ZipFile) -> BackupManifest:
    try:
        raw = archive.read(MANIFEST)
    except KeyError as exc:
        raise InvalidBackupError("The zip has no manifest.json: it isn't a vault backup.") from exc
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("format_version") not in (BACKUP_FORMAT_VERSION,):
            raise InvalidBackupError(
                f"Backup format {data.get('format_version')!r} isn't supported by this app."
            )
        return BackupManifest.model_validate(data)
    except (ValueError, ValidationError) as exc:
        if isinstance(exc, InvalidBackupError):
            raise
        raise InvalidBackupError(f"The backup manifest is invalid: {exc}") from exc


def _info(path: Path, manifest: BackupManifest) -> BackupInfo:
    return BackupInfo(
        id=path.stem,
        kind=manifest.kind,
        reason=manifest.reason,
        created_at=manifest.created_at,
        size=path.stat().st_size,
        includes_media=manifest.includes_media,
        app_version=manifest.app_version,
        schema_revision=manifest.schema_revision,
        path=path,
    )


def backup_info(path: Path) -> BackupInfo:
    """The listing entry of one backup zip."""
    with zipfile.ZipFile(path) as archive:
        return _info(path, read_manifest(archive))


def list_backups(vault_path: Path) -> list[BackupInfo]:
    """The vault's backup zips, newest first. Unreadable zips are skipped (and logged)."""
    found: list[BackupInfo] = []
    for directory in backup_dirs(vault_path).values():
        if not directory.is_dir():
            continue
        for path in directory.glob("*.zip"):
            backup_id = path.stem
            if not is_valid_backup_id(backup_id):
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    manifest = read_manifest(archive)
            except OSError, zipfile.BadZipFile, InvalidBackupError:
                logger.warning("skipping unreadable backup %s", path, exc_info=True)
                continue
            found.append(_info(path, manifest))
    found.sort(key=lambda info: (info.created_at, info.id), reverse=True)
    return found


def find_backup(vault_path: Path, backup_id: str) -> Path | None:
    if not is_valid_backup_id(backup_id):
        return None
    for directory in backup_dirs(vault_path).values():
        path = directory / f"{backup_id}.zip"
        if path.is_file():
            return path
    return None


def prune_scheduled(vault_path: Path, keep: int) -> list[Path]:
    """Delete the oldest scheduled backups beyond the newest ``keep``. Returns what was deleted.
    Manual and pre-operation backups are never pruned."""
    scheduled = [info for info in list_backups(vault_path) if info.kind == "scheduled"]
    removed = []
    for info in scheduled[keep:]:
        info.path.unlink(missing_ok=True)
        removed.append(info.path)
        logger.info("pruned scheduled backup %s", info.path)
    return removed


def last_scheduled(vault_path: Path) -> datetime | None:
    return next(
        (info.created_at for info in list_backups(vault_path) if info.kind == "scheduled"), None
    )


# --- restore -------------------------------------------------------------------------------------


def _safe_name(name: str) -> PurePosixPath:
    """Reject absolute paths, ``..``, backslashes, drive letters and empty parts."""
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
        or ":" in path.parts[0]
    ):
        raise InvalidBackupError(f"Unsafe path in the zip: {name!r}.")
    return path


def extract_backup(
    source: IO[bytes] | Path, staging: Path, limits: RestoreLimits = DEFAULT_LIMITS
) -> BackupManifest:
    """Validate the zip and extract ``lore.db`` (and ``media/``) into ``staging`` (which must
    exist and be empty), checking every file's sha256 against the manifest. Raises
    ``InvalidBackupError``; the caller removes ``staging`` on failure."""
    try:
        with zipfile.ZipFile(source) as archive:
            return _extract(archive, staging, limits)
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise InvalidBackupError("The file isn't a valid zip (or is damaged).") from exc


def _checked_entry(
    entry: zipfile.ZipInfo, expected: dict[str, str], seen: set[str]
) -> PurePosixPath | None:
    """The entry's path when it is a file to extract (None: a directory or the manifest)."""
    name = entry.filename
    if entry.is_dir():
        _safe_name(name.rstrip("/"))
        return None
    path = _safe_name(name)
    if name == MANIFEST:
        return None
    if stat.S_ISLNK(entry.external_attr >> 16):
        raise InvalidBackupError(f"Symbolic link in the zip: {name!r}.")
    if name in seen:
        raise InvalidBackupError(f"Duplicate entry in the zip: {name!r}.")
    seen.add(name)
    if name not in expected or (name != DATABASE_NAME and path.parts[0] != MEDIA_DIR):
        raise InvalidBackupError(f"Unexpected file in the zip: {name!r}.")
    return path


def _extract(archive: zipfile.ZipFile, staging: Path, limits: RestoreLimits) -> BackupManifest:
    entries = archive.infolist()
    if len(entries) > limits.max_files:
        raise InvalidBackupError(f"The zip holds more than {limits.max_files} files.")
    manifest = read_manifest(archive)
    expected = dict(manifest.files)
    if DATABASE_NAME not in expected:
        raise InvalidBackupError("The backup has no lore.db.")
    seen: set[str] = set()
    total = 0
    for entry in entries:
        path = _checked_entry(entry, expected, seen)
        if path is None:
            continue
        name = entry.filename
        target = staging.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        # Count the bytes actually written: declared sizes can lie.
        with archive.open(entry) as data, target.open("wb") as out:
            while chunk := data.read(_CHUNK):
                total += len(chunk)
                if total > limits.max_bytes:
                    raise InvalidBackupError(
                        f"The backup expands to more than {limits.max_bytes} bytes."
                    )
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != expected[name]:
            raise InvalidBackupError(f"Checksum mismatch for {name!r}: the backup is corrupt.")
    missing = sorted(set(expected) - seen)
    if missing:
        raise InvalidBackupError(f"Files listed in the manifest are missing: {missing}.")
    return manifest
