"""Routes of the branches module, mounted at ``/api/v1/vaults/{vault_id}/m/branches``.
Deleting a branch is the generic entity delete on the timeline (``cascade=true`` confirms
taking its descendant branches and branch-only entities along)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Path

from lore.core.api.deps import ModuleRegistryDep, SessionDep, WritableVaultDep
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.schemas import ID_PATTERN, EntityWriteResult
from lore.core.modules.spec import VaultContext
from lore.core.time.branches import create_branch
from lore.core.time.overrides import OverrideIn, OverrideResult, revert_override, save_override
from lore.core.visibility import AUTHOR
from lore.modules.branches.schemas import BranchCreate, OverrideCreate, OverrideOut

router = APIRouter(tags=["branches"])


@router.post("/timelines", name="timeline_create", status_code=201)
def create_timeline(
    body: BranchCreate, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> EntityWriteResult:
    """A branch of ``parent_timeline_id`` at ``branch_point``, in the parent's dimension
    (``time-model.md`` §4.1). The branch point must resolve within the dimension's time and may
    only be anchored to records of the parent timeline (``422 branch_point_invalid``)."""
    request_suppress(session, body.suppress)
    return create_branch(
        VaultContext(vault, session, registry),
        AUTHOR,
        parent_timeline_id=body.parent_timeline_id,
        branch_point=body.branch_point,
        name=body.name,
        summary=body.summary,
        visibility=body.visibility,
    )


def _out(result: OverrideResult) -> OverrideOut:
    return OverrideOut(
        record_type=result.record_type,
        id=result.id,
        root_id=result.root_id,
        timeline_id=result.timeline_id,
        affected=result.affected,
    )


@router.post("/overrides", name="override_save", status_code=201)
def save(
    body: OverrideCreate, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> OverrideOut:
    """Override (or override again) an inherited record spanning the branch point
    (``time-model.md`` §4.4): only what lies after the branch point may change (``422
    override_not_allowed`` otherwise; segments: ``not_supported`` until worldlines)."""
    request_suppress(session, body.suppress)
    data = OverrideIn(record_type=body.record_type, root_id=body.root_id,
                      timeline_id=body.timeline_id, changes=body.changes)  # fmt: skip
    return _out(save_override(VaultContext(vault, session, registry), AUTHOR, data))


@router.delete("/overrides/{record_type}/{override_id}", name="override_revert")
def revert(
    *,
    record_type: Annotated[Literal["event", "fact", "link"], Path()],
    override_id: Annotated[str, Path(pattern=ID_PATTERN, description="The override row.")],
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> OverrideOut:
    """Revert an override: the branch sees the inherited record again."""
    request_suppress(session, suppress.suppress if suppress else None)
    context = VaultContext(vault, session, registry)
    return _out(revert_override(context, AUTHOR, record_type, override_id))
