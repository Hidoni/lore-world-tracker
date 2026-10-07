"""History routes: recent changes, changeset detail, per-entity history, undo
(``docs/architecture/api.md`` §2). History is never shown to readers (a read-only server, or
``as_reader=true``): they get ``404``."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.history.schemas import ChangesetDetail, ChangesetPage, RevertResult
from lore.core.history.service import HistoryService
from lore.core.visibility import VisibilityPolicy

ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

router = APIRouter(prefix="/vaults/{vault_id}/changes", tags=["changes"])
entity_router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])

ChangesetIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Changeset id.")]
CursorQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]
LimitQuery = Annotated[int, Query(ge=1, le=500)]


def _author_only(policy: VisibilityPolicy) -> None:
    policy.require_author("History isn't available to readers.")


@router.get("", name="list")
def list_changes(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = 50,
) -> ChangesetPage:
    """Recent changesets, newest first."""
    _author_only(policy)
    return HistoryService(session, registry, vault).feed(cursor=cursor, limit=limit)


@router.get("/{changeset_id}", name="get")
def get_changeset(
    changeset_id: ChangesetIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> ChangesetDetail:
    """A changeset with its row-level changes."""
    _author_only(policy)
    return HistoryService(session, registry, vault).detail(changeset_id)


@router.post("/{changeset_id}/revert", name="revert")
def revert_changeset(
    changeset_id: ChangesetIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> RevertResult:
    """Undo a changeset (``409 revert_conflict`` when its rows changed since, or when the undo
    would break rules: ``context.problems``, and ``context.findings`` for error-severity
    consistency findings, which ``suppress`` can save anyway)."""
    request_suppress(session, suppress.suppress if suppress else None)
    return HistoryService(session, registry, vault).revert(changeset_id)


@entity_router.get("/{entity_id}/history", name="history")
def get_entity_history(
    *,
    entity_id: Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")],
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = 50,
) -> ChangesetPage:
    """Changesets touching the entity (its row, aliases, tags, links), newest first."""
    _author_only(policy)
    return HistoryService(session, registry, vault).entity_history(
        entity_id, cursor=cursor, limit=limit
    )
