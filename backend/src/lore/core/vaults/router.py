"""Vault routes (``docs/architecture/api.md`` §2, Vaults & settings)."""

from datetime import datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from lore.core.api.deps import VaultIdPath, VaultManagerDep
from lore.core.vaults.format import VaultName
from lore.core.vaults.manager import VaultInfo, VaultProblemCode

router = APIRouter(prefix="/vaults", tags=["vaults"])


class Vault(BaseModel):
    """A vault. ``modified_at`` is derived from its files' modification times."""

    id: str
    name: str
    folder: str
    created_at: datetime
    created_by_app_version: str
    modified_at: datetime
    published: bool

    @classmethod
    def of(cls, info: VaultInfo) -> Vault:
        manifest = info.manifest
        return cls(
            id=info.id,
            name=info.name,
            folder=info.folder,
            created_at=manifest.created_at,
            created_by_app_version=manifest.created_by_app_version,
            modified_at=info.modified_at,
            published=manifest.published,
        )


class VaultProblem(BaseModel):
    """A folder in ``vaults/`` that can't be opened (listed so it doesn't look deleted)."""

    folder: str
    code: VaultProblemCode
    detail: str
    vault_id: str | None = None
    name: str | None = None


class VaultList(BaseModel):
    """``items``: most recently modified first, ties by name (case-insensitive)."""

    items: list[Vault]
    problems: list[VaultProblem]


class VaultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: VaultName


class VaultUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: VaultName


# Route names are the operation ids' action part (vaults_list, ...); they aren't function names
# because `list` would shadow the builtin.
@router.get("", name="list")
def list_vaults(manager: VaultManagerDep) -> VaultList:
    registry = manager.registry()
    return VaultList(
        items=[Vault.of(info) for info in registry.sorted_vaults()],
        problems=[
            VaultProblem.model_validate(problem, from_attributes=True)
            for problem in registry.problems
        ],
    )


@router.post("", name="create", status_code=status.HTTP_201_CREATED)
def create_vault(body: VaultCreate, manager: VaultManagerDep) -> Vault:
    return Vault.of(manager.create(body.name))


@router.get("/{vault_id}", name="get")
def get_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> Vault:
    return Vault.of(manager.get(vault_id))


@router.patch("/{vault_id}", name="update")
def update_vault(vault_id: VaultIdPath, body: VaultUpdate, manager: VaultManagerDep) -> Vault:
    """Rename the vault (display name only; the folder keeps its name)."""
    return Vault.of(manager.rename(vault_id, body.name))


@router.delete("/{vault_id}", name="delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> Response:
    """Move the vault folder to the data directory's trash (it is never deleted)."""
    manager.trash(vault_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
