"""Consistency routes (``docs/architecture/api.md`` §2): author-only (readers get ``404``)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import (
    FindingOut,
    FindingPage,
    RuleInfo,
    RuleList,
    RuleUpdate,
    ScanResult,
    SuppressionIn,
)
from lore.core.consistency.service import ConsistencyService
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.visibility import VisibilityPolicy

router = APIRouter(prefix="/vaults/{vault_id}/consistency", tags=["consistency"])

RuleIdPath = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", max_length=200)]
FingerprintPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def _author_only(policy: VisibilityPolicy) -> None:
    policy.require_author("Consistency findings aren't available to readers.")


@router.get("/findings", name="findings")
def list_findings(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    status: Annotated[
        Literal["open", "suppressed", "all"], Query(description="Suppressed findings or not.")
    ] = "open",
    severity: Annotated[
        list[Literal["error", "warning", "info"]] | None,
        Query(description="Severities (repeatable; `info`: possible findings)."),
    ] = None,
    certainty: Literal["definite", "possible"] | None = None,
    rule: Annotated[list[str] | None, Query(description="Rule ids (repeatable).")] = None,
    owner: Annotated[str | None, Query(description="`core` or a module id.")] = None,
    entity: Annotated[str | None, Query(pattern=ID_PATTERN, description="A subject.")] = None,
    timeline: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> FindingPage:
    """Open findings of the rules this vault evaluates, most severe first, then newest."""
    _author_only(policy)
    return ConsistencyService(VaultContext(vault, session, registry)).findings(
        status=status,
        severities=severity or (),
        certainty=certainty,
        rules=rule or (),
        owner=owner,
        entity=entity,
        timeline=timeline,
        cursor=cursor,
        limit=limit,
    )


@router.post("/scan", name="scan")
def post_scan(
    vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> ScanResult:
    """Re-run every evaluated rule over the whole vault (its findings are replaced)."""
    return ConsistencyService(VaultContext(vault, session, registry)).scan()


@router.get("/rules", name="rules")
def list_rules(
    vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep, policy: PolicyDep
) -> RuleList:
    """The rules of core and the enabled modules with this vault's severities."""
    _author_only(policy)
    return ConsistencyService(VaultContext(vault, session, registry)).rules()


@router.patch("/rules/{rule_id}", name="update_rule")
def patch_rule(
    rule_id: RuleIdPath,
    body: RuleUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> RuleInfo:
    """Set a rule's severity (``off`` deletes its findings; leaving ``off`` scans it). Hard
    rules: ``422``."""
    return ConsistencyService(VaultContext(vault, session, registry)).set_severity(
        rule_id, body.severity
    )


@router.post("/suppressions", name="suppress", status_code=201)
def post_suppression(
    body: SuppressionIn, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> FindingOut:
    """Mark an open finding as intentional (``404`` unknown, ``409`` already suppressed, ``422``
    for hard rules)."""
    return ConsistencyService(VaultContext(vault, session, registry)).suppress(
        body.fingerprint, body.note
    )


@router.delete("/suppressions/{fingerprint}", name="unsuppress", status_code=204)
def delete_suppression(
    fingerprint: FingerprintPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> Response:
    """Take a suppression back."""
    ConsistencyService(VaultContext(vault, session, registry)).unsuppress(fingerprint)
    return Response(status_code=204)
