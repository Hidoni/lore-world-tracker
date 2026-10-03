"""Generic entity routes (``docs/architecture/api.md`` §2, Entities)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from sqlalchemy.orm import Session

from lore.core.api.deps import ModuleRegistryDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.entities.schemas import (
    ID_PATTERN,
    EntityCreate,
    EntityDeleteResult,
    EntityOut,
    EntityUpdate,
    EntityWriteResult,
)
from lore.core.entities.service import EntityService
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults import OpenVault

router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])

EntityIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")]


def _service(vault: OpenVault, session: Session, registry: ModuleRegistry) -> EntityService:
    return EntityService(VaultContext(vault, session, registry))


@router.post("", name="create", status_code=201)
def create_entity(
    body: EntityCreate, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> EntityWriteResult:
    """Create an entity of any kind, with its aliases, tags and kind extension data."""
    return _service(vault, session, registry).create(body)


@router.get("/{entity_id}", name="get")
def get_entity(
    entity_id: EntityIdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> EntityOut:
    """The full entity (also when it is in the trash; ``deleted_at`` is then set)."""
    return _service(vault, session, registry).get(entity_id)


@router.patch("/{entity_id}", name="update")
def update_entity(
    entity_id: EntityIdPath,
    body: EntityUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> EntityWriteResult:
    """Change the members sent. ``409 revision_conflict`` (with ``context.current``) when
    ``revision`` isn't the current one; ``409 conflict`` while the entity is in the trash."""
    return _service(vault, session, registry).update(entity_id, body)


@router.delete("/{entity_id}", name="delete")
def delete_entity(
    entity_id: EntityIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    purge: Annotated[
        bool, Query(description="Delete permanently (only entities already in the trash).")
    ] = False,
) -> EntityDeleteResult:
    """Move to the trash, or purge from it (``409 conflict`` while the entity isn't trashed, has
    children or is still referenced)."""
    service = _service(vault, session, registry)
    return service.purge(entity_id) if purge else service.trash(entity_id)


@router.post("/{entity_id}/restore", name="restore")
def restore_entity(
    entity_id: EntityIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> EntityWriteResult:
    """Take the entity out of the trash."""
    return _service(vault, session, registry).restore(entity_id)
