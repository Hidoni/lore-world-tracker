"""Link and link-type routes (``docs/architecture/api.md`` §2, Links & link types)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.links.schemas import (
    ID_PATTERN,
    LINK_TYPE_KEY_PATTERN,
    Backlinks,
    EntityLinks,
    LinkCreate,
    LinkDeleteResult,
    LinkTypeCreate,
    LinkTypeDeleted,
    LinkTypeList,
    LinkTypeOut,
    LinkTypeUpdate,
    LinkUpdate,
    LinkWriteResult,
)
from lore.core.links.service import LinkService
from lore.core.links.types_service import LinkTypeService

router = APIRouter(prefix="/vaults/{vault_id}/links", tags=["links"])
types_router = APIRouter(prefix="/vaults/{vault_id}/link-types", tags=["link_types"])
entity_router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])

LinkIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Link id.")]
KeyPath = Annotated[str, Path(pattern=LINK_TYPE_KEY_PATTERN, description="Link type key.")]


@router.post("", name="create", status_code=201)
def create_link(
    body: LinkCreate, _vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> LinkWriteResult:
    """Create a link (``422 link_type_not_allowed`` when the type doesn't fit, ``409 conflict``
    when a uniqueness or cardinality limit is reached)."""
    return LinkService(session, registry).create(body)


@router.patch("/{link_id}", name="update")
def update_link(
    link_id: LinkIdPath,
    body: LinkUpdate,
    _vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> LinkWriteResult:
    """Change role, data, visibility, validity or manual order (revision required)."""
    return LinkService(session, registry).update(link_id, body)


@router.delete("/{link_id}", name="delete")
def delete_link(
    link_id: LinkIdPath, _vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> LinkDeleteResult:
    """Move the link to the trash."""
    return LinkService(session, registry).trash(link_id)


@types_router.get("", name="list")
def list_link_types(
    _vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> LinkTypeList:
    """Built-in and user-defined link types offered by this vault (archived ones flagged)."""
    return LinkTypeService(session, registry).list()


@types_router.post("", name="create", status_code=201)
def create_link_type(
    body: LinkTypeCreate,
    _vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> LinkTypeOut:
    """Define a link type (``custom.<slug>``)."""
    return LinkTypeService(session, registry).create(body)


@types_router.patch("/{key}", name="update")
def update_link_type(
    key: KeyPath,
    body: LinkTypeUpdate,
    _vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> LinkTypeOut:
    """Edit or archive a user-defined type. Built-in types: ``403 forbidden``."""
    return LinkTypeService(session, registry).update(key, body)


@types_router.delete("/{key}", name="delete")
def delete_link_type(
    key: KeyPath, _vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> LinkTypeDeleted:
    """Delete an unused user-defined type (``409 conflict`` while links use it: archive it)."""
    return LinkTypeService(session, registry).delete(key)


@entity_router.get("/{entity_id}/links", name="links")
def list_entity_links(
    *,
    entity_id: Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")],
    _vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    direction: Literal["out", "in", "both"] = "both",
    types: Annotated[
        list[str] | None, Query(alias="type", description="Link type keys (repeatable).")
    ] = None,
    include_trashed: Annotated[
        bool, Query(description="Also links whose other end is in the trash.")
    ] = False,
) -> EntityLinks:
    """The entity's links in both directions (symmetric ones as ``both``)."""
    return LinkService(session, registry, policy).entity_links(
        entity_id, direction=direction, types=types, include_trashed=include_trashed
    )


@entity_router.get("/{entity_id}/backlinks", name="backlinks")
def list_backlinks(
    *,
    entity_id: Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")],
    _vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    include_trashed: Annotated[bool, Query(description="Also entities in the trash.")] = False,
) -> Backlinks:
    """Entities pointing at this one: incoming (and symmetric) links and mentions with counts by
    block visibility, by name."""
    return LinkService(session, registry, policy).backlinks(
        entity_id, include_trashed=include_trashed
    )
