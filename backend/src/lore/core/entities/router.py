"""Generic entity routes (``docs/architecture/api.md`` §2, Entities)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from sqlalchemy.orm import Session

from lore.core.api.deps import ModuleRegistryDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.entities.queries import EntityQueries
from lore.core.entities.schemas import (
    ID_PATTERN,
    EntityCreate,
    EntityDeleteResult,
    EntityOut,
    EntityPage,
    EntityUpdate,
    EntityWriteResult,
    FieldValueList,
    ListSort,
    TrashPage,
    TreePage,
)
from lore.core.entities.service import EntityService
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults import OpenVault

router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])
tree_router = APIRouter(prefix="/vaults/{vault_id}", tags=["tree"])
trash_router = APIRouter(prefix="/vaults/{vault_id}", tags=["trash"])

EntityIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")]
IdQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]
KindsQuery = Annotated[
    list[str] | None, Query(alias="kind", description="Kind keys (repeat for several).")
]
CursorQuery = Annotated[str | None, Query(max_length=4096)]


def _service(vault: OpenVault, session: Session, registry: ModuleRegistry) -> EntityService:
    return EntityService(VaultContext(vault, session, registry))


def _queries(vault: OpenVault, session: Session, registry: ModuleRegistry) -> EntityQueries:
    return EntityQueries(_service(vault, session, registry))


# Static paths first: "/field-values" must not be taken for an entity id.


@router.get("", name="list")
def list_entities(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    kinds: KindsQuery = None,
    dimension: IdQuery = None,
    include_multiversal: bool = True,
    parent: IdQuery = None,
    tags: Annotated[
        list[str] | None, Query(alias="tag", description="Tag ids; entities need all of them.")
    ] = None,
    q: Annotated[
        str | None, Query(max_length=500, description="Name or alias prefix (until search).")
    ] = None,
    include_trashed: bool = False,
    sort: ListSort = "name",
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> EntityPage:
    """Entities of enabled kinds. ``dimension`` includes multiversal entities unless
    ``include_multiversal=false``. ``name`` sorts ignoring case and accents, numbers by value."""
    return _queries(vault, session, registry).list_entities(
        kinds=kinds,
        dimension=dimension,
        include_multiversal=include_multiversal,
        parent=parent,
        tags=tags,
        q=q,
        include_trashed=include_trashed,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/field-values", name="field_values")
def list_field_values(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    kind: Annotated[str, Query(max_length=100)],
    field: Annotated[str, Query(max_length=200)],
    q: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FieldValueList:
    """Distinct values of a text field for autocomplete, most used first."""
    return _queries(vault, session, registry).field_values(kind=kind, field=field, q=q, limit=limit)


@tree_router.get("/tree", name="get")
def get_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    dimension: IdQuery = None,
    parent: IdQuery = None,
    kinds: KindsQuery = None,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> TreePage:
    """One level of the navigation tree: the roots (entities without a shown parent), or the
    children of ``parent``. Manually ordered entities (``sort_key``) first, then by name."""
    return _queries(vault, session, registry).tree(
        dimension=dimension, parent=parent, kinds=kinds, cursor=cursor, limit=limit
    )


@trash_router.get("/trash", name="list")
def list_trash(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> TrashPage:
    """Trashed entities, most recently trashed first, with their orphaned children count."""
    return _queries(vault, session, registry).trash(cursor=cursor, limit=limit)


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


@router.get("/{entity_id}/children", name="children")
def list_children(
    *,
    entity_id: EntityIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    kinds: KindsQuery = None,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> TreePage:
    """Children of every kind and dimension (not in the trash), sorted like the tree."""
    return _queries(vault, session, registry).children(
        entity_id, kinds=kinds, cursor=cursor, limit=limit
    )


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
