"""Routes of the branches module, mounted at ``/api/v1/vaults/{vault_id}/m/branches``.
Deleting a branch is the generic entity delete on the timeline (``cascade=true`` confirms
taking its descendant branches and branch-only entities along)."""

from fastapi import APIRouter

from lore.core.api.deps import ModuleRegistryDep, SessionDep, WritableVaultDep
from lore.core.consistency.schemas import request_suppress
from lore.core.entities.schemas import EntityWriteResult
from lore.core.modules.spec import VaultContext
from lore.core.time.branches import create_branch
from lore.core.visibility import AUTHOR
from lore.modules.branches.schemas import BranchCreate

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
