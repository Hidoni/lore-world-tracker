"""Routes of the correspondences module, mounted at ``/api/v1/vaults/{vault_id}/m/correspondences``
(``docs/modules/correspondences.md``)."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.types import MomentStr
from lore.core.visibility import AUTHOR
from lore.modules.correspondences.schemas import (
    CorrespondenceCreate,
    CorrespondenceList,
    CorrespondenceOut,
    CorrespondenceUpdate,
    CorrespondenceWriteResult,
    MapBatchIn,
    MapBatchOut,
    MapOut,
)
from lore.modules.correspondences.service import Correspondences

router = APIRouter(tags=["correspondences"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]
IdQuery = Annotated[str, Query(pattern=ID_PATTERN)]


@router.get("", name="list")
def list_correspondences(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="Of this dimension (either side).")
    ] = None,
) -> CorrespondenceList:
    """The live correspondences (with their sync points), by name."""
    return Correspondences(VaultContext(vault, session, registry), policy).list_all(dimension)


@router.post("", name="create", status_code=201)
def create(
    body: CorrespondenceCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CorrespondenceWriteResult:  # fmt: skip
    """A correspondence between two dimensions (``time-model.md`` §12.1). The sync points
    resolve (they may be anchored to events of their dimension) and must increase strictly in
    both dimensions; rates must be positive, and a single point extrapolating needs both
    (``422 validation_error``, paths ``points.<i>``, ``rate_before``, ``rate_after``)."""
    request_suppress(session, body.suppress)
    return Correspondences(VaultContext(vault, session, registry), AUTHOR).create(body)


@router.get("/map", name="map")
def map_moment(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    from_dimension: IdQuery,
    to_dimension: IdQuery,
    t: Annotated[MomentStr, Query(description="A moment of `from_dimension`.")],
) -> MapOut:
    """The moment of `to_dimension` happening at `t` of `from_dimension`, mapped along the
    shortest path of correspondences (``time-model.md`` §12.3); `defined: false` outside the
    mappings, their extrapolation or the target dimension's time."""
    service = Correspondences(VaultContext(vault, session, registry), policy)
    return service.map(from_dimension, to_dimension, int(t))


@router.post("/map-batch", name="map_batch")
def map_batch(
    body: MapBatchIn, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> MapBatchOut:  # fmt: skip
    """Many moments mapped at once (timeline dimension lanes), like `GET /map`. A `POST` (the
    moments go in the body): read-only servers refuse it, like the other read helpers that
    post."""
    service = Correspondences(VaultContext(vault, session, registry), policy)
    return service.map_batch(body.from_dimension, body.to_dimension, [int(t) for t in body.t])


@router.get("/{correspondence_id}", name="get")
def get(
    *,
    correspondence_id: IdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> CorrespondenceOut:
    return Correspondences(VaultContext(vault, session, registry), policy).get(correspondence_id)


@router.patch("/{correspondence_id}", name="update")
def update(
    *,
    correspondence_id: IdPath,
    body: CorrespondenceUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> CorrespondenceWriteResult:
    """Change a correspondence (`revision` as read; `409 revision_conflict` otherwise). Its
    dimensions never change; `points` replaces every sync point."""
    request_suppress(session, body.suppress)
    service = Correspondences(VaultContext(vault, session, registry), AUTHOR)
    return service.update(correspondence_id, body)


@router.delete("/{correspondence_id}", name="delete")
def delete(
    *,
    correspondence_id: IdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> CorrespondenceWriteResult:
    """Move a correspondence to the trash: mapping stops using it."""
    request_suppress(session, suppress.suppress if suppress else None)
    service = Correspondences(VaultContext(vault, session, registry), AUTHOR)
    return service.delete(correspondence_id)
