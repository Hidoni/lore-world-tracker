"""Vault routes (``docs/architecture/api.md`` §2, Vaults & settings)."""

from datetime import datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from lore.core.api.deps import VaultIdPath, VaultManagerDep
from lore.core.vaults.format import VaultName
from lore.core.vaults.manager import VaultInfo, VaultManager, VaultProblemCode, VaultSchemaState

router = APIRouter(prefix="/vaults", tags=["vaults"])


class VaultSchemaStatus(BaseModel):
    """The vault database's migration state. ``needs_migration``: ``POST /vaults/{v}/migrate``
    upgrades it (shown when ``LORE_AUTO_MIGRATE=false``)."""

    state: VaultSchemaState
    revision: str | None
    head: str


class Vault(BaseModel):
    """A vault. ``modified_at`` is derived from its files' modification times."""

    id: str
    name: str
    folder: str
    created_at: datetime
    created_by_app_version: str
    modified_at: datetime
    published: bool
    schema_status: VaultSchemaStatus

    @classmethod
    def of(cls, info: VaultInfo, manager: VaultManager) -> Vault:
        manifest = info.manifest
        schema = manager.schema_status(info)
        return cls(
            id=info.id,
            name=info.name,
            folder=info.folder,
            created_at=manifest.created_at,
            created_by_app_version=manifest.created_by_app_version,
            modified_at=info.modified_at,
            published=manifest.published,
            schema_status=VaultSchemaStatus(
                state=schema.state, revision=schema.revision, head=schema.head
            ),
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
        items=[Vault.of(info, manager) for info in registry.sorted_vaults()],
        problems=[
            VaultProblem.model_validate(problem, from_attributes=True)
            for problem in registry.problems
        ],
    )


@router.post("", name="create", status_code=status.HTTP_201_CREATED)
def create_vault(body: VaultCreate, manager: VaultManagerDep) -> Vault:
    return Vault.of(manager.create(body.name), manager)


@router.get("/{vault_id}", name="get")
def get_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> Vault:
    return Vault.of(manager.get(vault_id), manager)


@router.patch("/{vault_id}", name="update")
def update_vault(vault_id: VaultIdPath, body: VaultUpdate, manager: VaultManagerDep) -> Vault:
    """Rename the vault (display name only; the folder keeps its name)."""
    return Vault.of(manager.rename(vault_id, body.name), manager)


@router.delete("/{vault_id}", name="delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> Response:
    """Move the vault folder to the data directory's trash (it is never deleted)."""
    manager.trash(vault_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class MigrationResponse(BaseModel):
    vault: Vault
    from_revision: str | None
    to_revision: str
    backup: str | None = Field(description="The pre-migration backup; null if nothing changed.")


@router.post("/{vault_id}/migrate", name="migrate")
def migrate_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> MigrationResponse:
    """Run pending migrations (after a pre-migration backup); a no-op for a current vault."""
    result = manager.migrate(vault_id)
    return MigrationResponse(
        vault=Vault.of(manager.get(vault_id), manager),
        from_revision=result.from_revision,
        to_revision=result.to_revision,
        backup=str(result.backup) if result.backup else None,
    )
