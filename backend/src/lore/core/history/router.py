"""History routes: recent changes, changeset detail, per-entity history, undo
(``docs/architecture/api.md`` §2). History is never shown to readers: a read-only server answers
``404``."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.errors import NotFoundError
from lore.core.history.schemas import ChangesetDetail, ChangesetPage, RevertResult
from lore.core.history.service import HistoryService
from lore.core.vaults import OpenVault

ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

router = APIRouter(prefix="/vaults/{vault_id}/changes", tags=["changes"])
entity_router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])

ChangesetIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Changeset id.")]
CursorQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]
LimitQuery = Annotated[int, Query(ge=1, le=500)]


def _author_only(vault: OpenVault) -> None:
    if vault.read_only:
        raise NotFoundError("History isn't available on a read-only server.")


@router.get("", name="list")
def list_changes(
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = 50,
) -> ChangesetPage:
    """Recent changesets, newest first."""
    _author_only(vault)
    return HistoryService(session, registry, vault).feed(cursor=cursor, limit=limit)


@router.get("/{changeset_id}", name="get")
def get_changeset(
    changeset_id: ChangesetIdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> ChangesetDetail:
    """A changeset with its row-level changes."""
    _author_only(vault)
    return HistoryService(session, registry, vault).detail(changeset_id)


@router.post("/{changeset_id}/revert", name="revert")
def revert_changeset(
    changeset_id: ChangesetIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> RevertResult:
    """Undo a changeset (``409 revert_conflict`` when its rows changed since)."""
    return HistoryService(session, registry, vault).revert(changeset_id)


@entity_router.get("/{entity_id}/history", name="history")
def get_entity_history(
    *,
    entity_id: Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")],
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = 50,
) -> ChangesetPage:
    """Changesets touching the entity (its row, aliases, tags, links), newest first."""
    _author_only(vault)
    return HistoryService(session, registry, vault).entity_history(
        entity_id, cursor=cursor, limit=limit
    )
