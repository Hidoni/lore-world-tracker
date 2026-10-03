"""The vault folder format: ``vault.json`` and its upgraders.

``format_version`` covers the folder layout, not the database schema
(``docs/architecture/persistence-and-migrations.md`` §1). An upgrader ``UPGRADERS[n]`` turns a
version ``n`` manifest into version ``n + 1``; upgraders are frozen once released.
"""

import json
import os
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, ValidationError

FORMAT_VERSION: Final = 1
MANIFEST_NAME = "vault.json"
DATABASE_NAME = "lore.db"
LOCK_NAME = ".lock"

# Folder names are checked against this before any path is built from them (security.md §3).
FOLDER_PATTERN = r"^[a-z0-9-]+$"
VAULT_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_FOLDER_RE = re.compile(FOLDER_PATTERN)
_VAULT_ID_RE = re.compile(VAULT_ID_PATTERN)
_SLUG_MAX = 40
# Folder suffix lengths, shortest first: the first 8 characters of the id, then longer prefixes
# (ending at the UUID's hyphens) on collision, up to the whole id.
ID_PREFIX_LENGTHS = (8, 13, 18, 23, 36)

UPGRADERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _no_control_characters(value: str) -> str:
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("must not contain control characters")
    return value


type VaultName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(_no_control_characters),
]
"""A vault's display name. Renaming changes only this, never the folder."""

type VaultId = Annotated[str, StringConstraints(pattern=VAULT_ID_PATTERN)]


class VaultManifest(BaseModel):
    """``vault.json``. Unknown keys are kept, so rewriting the file never drops data."""

    model_config = ConfigDict(extra="allow", frozen=True)

    format_version: Literal[1]
    vault_id: VaultId
    name: VaultName
    created_at: datetime
    created_by_app_version: str
    published: bool = False


class ManifestError(ValueError):
    """``vault.json`` is missing, unreadable, invalid or from a newer app."""


class NewerFormatError(ManifestError):
    """``vault.json`` was written by a newer app (its ``format_version`` is unknown here)."""


def is_valid_folder_name(name: str) -> bool:
    return _FOLDER_RE.fullmatch(name) is not None


def is_valid_vault_id(value: str) -> bool:
    return _VAULT_ID_RE.fullmatch(value) is not None


def slugify(name: str) -> str:
    """The folder slug for a vault name: lowercase ASCII letters, digits and single hyphens."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:_SLUG_MAX].rstrip("-") or "vault"


def folder_candidates(name: str, vault_id: str) -> list[str]:
    """Folder names to try, in order: ``<slug>-<first 8 chars of id>``, then longer id prefixes.

    UUIDv7 ids created within about a minute share their first 8 characters, so a second vault
    with the same name could collide. The last candidate holds the whole (unique) id.
    """
    slug = slugify(name)
    return [f"{slug}-{vault_id[:length]}" for length in ID_PREFIX_LENGTHS]


def upgrade_manifest(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Run the upgraders up to ``FORMAT_VERSION``. Returns the data and whether it changed."""
    version = data.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ManifestError("format_version must be an integer")
    if version > FORMAT_VERSION:
        raise NewerFormatError(
            f"vault format {version} is newer than this app supports ({FORMAT_VERSION})"
        )
    changed = False
    while version < FORMAT_VERSION:
        upgrader = UPGRADERS.get(version)
        if upgrader is None:
            raise ManifestError(f"unknown vault format {version}")
        data = upgrader(data)
        version = data["format_version"]
        changed = True
    return data, changed


def read_manifest(folder: Path) -> tuple[VaultManifest, bool]:
    """Read and upgrade ``<folder>/vault.json``. Returns the manifest and whether it was upgraded
    (the caller decides whether to write it back: read-only servers never do)."""
    path = folder / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{path} is not a JSON object")
    data, upgraded = upgrade_manifest(data)
    try:
        return VaultManifest.model_validate(data), upgraded
    except ValidationError as exc:
        raise ManifestError(f"invalid {path}: {exc}") from exc


def write_manifest(folder: Path, manifest: VaultManifest) -> None:
    """Replace ``<folder>/vault.json`` atomically (write a temp file, fsync, rename)."""
    text = json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    target = folder / MANIFEST_NAME
    temporary = folder / f".{MANIFEST_NAME}.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
