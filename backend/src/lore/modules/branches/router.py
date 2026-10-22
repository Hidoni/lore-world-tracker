"""Routes of the branches module, mounted at ``/api/v1/vaults/{vault_id}/m/branches``.
Deleting a branch is the generic entity delete on the timeline (``cascade=true`` confirms
taking its descendant branches and branch-only entities along)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Path, Query

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.schemas import ID_PATTERN, EntityWriteResult
from lore.core.modules.spec import VaultContext
from lore.core.time import branch_ops
from lore.core.time.branch_reads import (
    BranchDiff,
    NoteIn,
    NoteOut,
    branch_diff,
    read_note,
    write_note,
)
from lore.core.time.branches import create_branch
from lore.core.time.models import Proposal
from lore.core.time.overrides import OverrideIn, OverrideResult, revert_override, save_override
from lore.core.visibility import AUTHOR
from lore.modules.branches.schemas import (
    RECORD_TYPE_PATTERN,
    BranchApplied,
    BranchCreate,
    BranchProposalApply,
    BranchProposalIn,
    BranchProposalOut,
    OverrideCreate,
    OverrideOut,
)

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
    record_type: Annotated[str, Path(pattern=RECORD_TYPE_PATTERN)],
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


EntityPath = Annotated[str, Path(pattern=ID_PATTERN)]


@router.get("/notes/{entity_id}/{timeline_id}", name="note_get")
def get_note(
    *,
    entity_id: EntityPath,
    timeline_id: EntityPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> NoteOut:
    """The branch's note on an entity (``time-model.md`` §4.6): revision 0 and a null body when
    there is none. ``404`` for an entity or timeline the reader can't see, or an entity the
    timeline doesn't show; ``422`` for a prime timeline."""
    return read_note(VaultContext(vault, session, registry), policy, entity_id, timeline_id)


@router.put("/notes/{entity_id}/{timeline_id}", name="note_put")
def put_note(
    *,
    entity_id: EntityPath,
    timeline_id: EntityPath,
    body: NoteIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> NoteOut:
    """Write the branch's note on an entity; an empty body deletes it. ``409
    revision_conflict`` when ``revision`` isn't the current one (0 for a new note)."""
    context = VaultContext(vault, session, registry)
    return write_note(context, AUTHOR, entity_id, timeline_id, body)


@router.get("/timelines/{timeline_id}/diff", name="timeline_diff")
def get_diff(
    *,
    timeline_id: EntityPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    against: Annotated[Literal["parent"], Query(description="Only `parent` for now.")] = "parent",
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> BranchDiff:
    """What a branch changed against its parent (``time-model.md`` §4.4): the records it
    created, those it overrode (before and after) and the inherited records spanning its branch
    point it didn't override. Each list holds at most ``limit`` records (``truncated``)."""
    del against
    context = VaultContext(vault, session, registry)
    return branch_diff(context, policy, timeline_id, limit=limit)


def _proposal_out(proposal: Proposal) -> BranchProposalOut:
    impact = {k: v for k, v in proposal.impact.items() if k != "plan"}
    return BranchProposalOut.model_validate(
        {
            "id": proposal.id,
            "timeline_id": proposal.target_id,
            "base_revision": proposal.base_revision,
            "created_at": proposal.created_at,
            "expires_at": proposal.expires_at,
            **impact,
        }
    )


@router.post("/timelines/{timeline_id}/proposals", name="timeline_propose", status_code=201)
def propose(
    *,
    timeline_id: EntityPath,
    body: BranchProposalIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> BranchProposalOut:
    """Preview moving a branch under another timeline (`reparent`) or merging it into its parent
    (`merge`, ``time-model.md`` §4.7): the records it moves or changes, the parent's records after
    the branch point (each kept or discarded on apply), the timelines and entities that move and
    the branch points pinned. Kept for an hour. ``404`` for a missing or trashed branch, ``422``
    for a prime or an invalid new parent, ``409 occurrence_key_conflict`` when a series has an
    occurrence materialized in both timelines."""
    if body.operation == branch_ops.REPARENT and body.parent_timeline_id is None:
        raise branch_ops.missing_parent()
    payload = body.model_dump(mode="json", exclude={"suppress"})
    context = VaultContext(vault, session, registry)
    return _proposal_out(branch_ops.preview(context, timeline_id, payload))


ProposalPath = Annotated[str, Path(pattern=ID_PATTERN, description="The proposal.")]


@router.post("/timelines/{timeline_id}/proposals/{proposal_id}/apply", name="timeline_apply")
def apply_proposal(
    *,
    timeline_id: EntityPath,
    proposal_id: ProposalPath,
    body: BranchProposalApply,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> BranchApplied:
    """Apply a branch proposal as one changeset (one undo). ``409 proposal_stale`` when the
    timelines or their records changed since the preview; ``404`` for an expired proposal."""
    request_suppress(session, body.suppress)
    context = VaultContext(vault, session, registry)
    applied = branch_ops.apply(
        context, timeline_id, proposal_id, body.strategies, body.default_strategy
    )
    return BranchApplied(
        operation=applied.operation,  # type: ignore[arg-type]
        moved=applied.moved,
        discarded=applied.discarded,
        timelines=applied.timelines,
        pinned=applied.pinned,
        affected=applied.affected,
    )
