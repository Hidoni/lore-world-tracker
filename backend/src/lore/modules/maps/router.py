"""Routes of the maps module, mounted at ``/api/v1/vaults/{vault_id}/m/maps``
(``docs/modules/maps.md``, API)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.consistency.schemas import request_suppress
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.visibility import AUTHOR
from lore.modules.maps.schemas import (
    EntityPins,
    MapCreate,
    MapDetail,
    MapList,
    MapUpdate,
    MapWriteResult,
    PinCreate,
    PinUpdate,
    PinWriteResult,
    RegionCreate,
    RegionUpdate,
    RegionWriteResult,
)
from lore.modules.maps.service import Maps

router = APIRouter(tags=["maps"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]


@router.get("/maps", name="list")
def list_maps(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    location: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="The maps of this location.")
    ] = None,
) -> MapList:
    """The live maps (of a location), by location then ``sort_key``."""
    return Maps(VaultContext(vault, session, registry), policy).list_maps(location)


@router.post("/maps", name="create", status_code=201)
def create_map(
    body: MapCreate, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> MapWriteResult:
    """A map of a location: a raster image of the media library (its size is copied)."""
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).create(body)


@router.get("/maps/{map_id}", name="get")
def get_map(
    *,
    map_id: IdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> MapDetail:
    """The map with its pins (time-bound ones of `timeline`, default the prime timeline of the
    location's dimension): as of `at`, pins with a validity show while it covers the moment
    and the others while their target exists (an event: while it happens); `shown: possible`
    when an uncertain bound leaves it open. `breadcrumbs` lead out through the ancestors' maps."""
    service = Maps(VaultContext(vault, session, registry), policy)
    return service.detail(map_id, timeline_id=timeline, at=at)


@router.patch("/maps/{map_id}", name="update")
def update_map(
    map_id: IdPath, body: MapUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> MapWriteResult:  # fmt: skip
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).update(map_id, body)


@router.delete("/maps/{map_id}", name="trash")
def trash_map(
    map_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> MapWriteResult:
    """The map and its pins to the trash."""
    return Maps(VaultContext(vault, session, registry), AUTHOR).trash(map_id)


@router.post("/maps/{map_id}/pins", name="add_pin", status_code=201)
def add_pin(
    map_id: IdPath, body: PinCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> PinWriteResult:  # fmt: skip
    """A pin at image pixel coordinates, for an entity or a label; a validity needs a timeline
    of the location's dimension."""
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).add_pin(map_id, body)


@router.patch("/pins/{pin_id}", name="update_pin")
def update_pin(
    pin_id: IdPath, body: PinUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> PinWriteResult:  # fmt: skip
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).update_pin(pin_id, body)


@router.delete("/pins/{pin_id}", name="trash_pin")
def trash_pin(
    pin_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> PinWriteResult:
    return Maps(VaultContext(vault, session, registry), AUTHOR).trash_pin(pin_id)


@router.post("/maps/{map_id}/regions", name="add_region", status_code=201)
def add_region(
    map_id: IdPath, body: RegionCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> RegionWriteResult:  # fmt: skip
    """A region (#154): a polygon of image pixel coordinates, for an entity (a territory: its
    location) or a label; a validity needs a timeline of the location's dimension."""
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).add_region(map_id, body)


@router.patch("/regions/{region_id}", name="update_region")
def update_region(
    region_id: IdPath, body: RegionUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> RegionWriteResult:  # fmt: skip
    request_suppress(session, body.suppress)
    return Maps(VaultContext(vault, session, registry), AUTHOR).update_region(region_id, body)


@router.delete("/regions/{region_id}", name="trash_region")
def trash_region(
    region_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> RegionWriteResult:
    return Maps(VaultContext(vault, session, registry), AUTHOR).trash_region(region_id)


@router.get("/entities/{entity_id}/pins", name="entity_pins")
def entity_pins(
    entity_id: IdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> EntityPins:  # fmt: skip
    """Where the entity is pinned ("show on map")."""
    return Maps(VaultContext(vault, session, registry), policy).entity_pins(entity_id)
