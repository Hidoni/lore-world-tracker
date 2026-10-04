"""Backup, restore and vault settings routes (``docs/architecture/api.md`` §2, Vaults & settings).

Backups hold private data: listing and downloading them is author-only (readers, including
``?as_reader=true``, get ``404``)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from lore.core.api.deps import PolicyDep, SessionDep, VaultIdPath, VaultManagerDep, WritableVaultDep
from lore.core.vaults.backups import BACKUP_ID_PATTERN, BackupInfo
from lore.core.vaults.router import Vault
from lore.core.vaults.settings import (
    VaultSettings,
    VaultSettingsUpdate,
    read_settings,
    update_settings,
)

router = APIRouter(prefix="/vaults", tags=["backups"])
settings_router = APIRouter(prefix="/vaults/{vault_id}", tags=["settings"])

BackupIdPath = Annotated[str, Path(pattern=BACKUP_ID_PATTERN, description="Backup id.")]


class Backup(BaseModel):
    """A backup zip. ``kind``: ``manual``, ``scheduled`` or ``pre`` (taken before a destructive
    operation, with its ``reason``)."""

    id: str
    kind: str
    reason: str | None
    created_at: datetime
    size: int
    includes_media: bool
    app_version: str
    schema_revision: str | None

    @classmethod
    def of(cls, info: BackupInfo) -> Backup:
        return cls(
            id=info.id,
            kind=info.kind,
            reason=info.reason,
            created_at=info.created_at,
            size=info.size,
            includes_media=info.includes_media,
            app_version=info.app_version,
            schema_revision=info.schema_revision,
        )


class BackupList(BaseModel):
    """Newest first."""

    items: list[Backup]


class BackupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_media: bool = True


def _author_only(policy: PolicyDep) -> None:
    policy.require_author("Backups aren't available to readers.")


@router.post("/{vault_id}/backups", name="create", status_code=status.HTTP_201_CREATED)
def create_backup(vault_id: VaultIdPath, body: BackupCreate, manager: VaultManagerDep) -> Backup:
    """Back up the vault now (a zip with the database and, by default, its media). Backups contain
    private data."""
    return Backup.of(manager.backup(vault_id, include_media=body.include_media))


@router.get("/{vault_id}/backups", name="list")
def list_backups(vault_id: VaultIdPath, manager: VaultManagerDep, policy: PolicyDep) -> BackupList:
    """Manual, scheduled and pre-operation backups of the vault."""
    _author_only(policy)
    return BackupList(items=[Backup.of(info) for info in manager.backups(vault_id)])


@router.get(
    "/{vault_id}/backups/{backup_id}/download",
    name="download",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "The backup zip."}},
)
def download_backup(
    vault_id: VaultIdPath, backup_id: BackupIdPath, manager: VaultManagerDep, policy: PolicyDep
) -> FileResponse:
    _author_only(policy)
    path = manager.backup_file(vault_id, backup_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/restore", name="restore", status_code=status.HTTP_201_CREATED)
def restore_backup(file: UploadFile, manager: VaultManagerDep) -> Vault:
    """Restore a backup zip into a new vault ("<name> (restored <date>)"); existing vaults are
    never touched. ``422 invalid_backup`` for a damaged, unsafe or foreign zip."""
    return Vault.of(manager.restore(file.file), manager)


@settings_router.get("/settings", name="get")
def get_settings(session: SessionDep) -> VaultSettings:
    """Vault settings: defaults for new content and the backup schedule."""
    return read_settings(session)


@settings_router.patch("/settings", name="update")
def update_vault_settings(
    body: VaultSettingsUpdate, _vault: WritableVaultDep, session: SessionDep
) -> VaultSettings:
    """Merge the members sent into the settings (not recorded in history)."""
    return update_settings(session, body)
