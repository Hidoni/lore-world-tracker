"""Fact routes (``api.md`` §2, Facts; ``time-model.md`` §10.2)."""

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
from lore.core.entities.schemas import ID_PATTERN
from lore.core.facts.schemas import (
    FACT_KEY_PATTERN,
    FactCreate,
    FactList,
    FactUpdate,
    FactWriteResult,
)
from lore.core.facts.service import Facts
from lore.core.modules.spec import VaultContext

router = APIRouter(prefix="/vaults/{vault_id}/facts", tags=["facts"])
entity_router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["facts"])

EntityIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")]
FactIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Fact id.")]


@entity_router.get("/{entity_id}/facts", name="list_facts")
def list_facts(
    *,
    entity_id: EntityIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    field: Annotated[
        str | None,
        Query(pattern=FACT_KEY_PATTERN, max_length=200, description="Only this field's facts."),
    ] = None,
    timeline: Annotated[
        str | None,
        Query(
            pattern=ID_PATTERN,
            description="Only facts visible in this timeline (its own and those it inherits).",
        ),
    ] = None,
) -> FactList:
    """The entity's facts (field values over time, existence, names), by field and start.
    ``404`` for an entity the request may not see."""
    facts = Facts(VaultContext(vault, session, registry), policy)
    return facts.of_entity(entity_id, field_key=field, timeline_id=timeline)


@entity_router.post("/{entity_id}/facts", name="create_fact", status_code=201)
def create_fact(
    *,
    entity_id: EntityIdPath,
    body: FactCreate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> FactWriteResult:
    """A fact: the field must be temporal (or ``core.exists``/``core.name``), the value fits its
    type, the timeline is of the entity's dimension (any for a multiversal entity) and
    ``source_event_id`` is an event."""
    request_suppress(session, body.suppress)
    return Facts(VaultContext(vault, session, registry)).create(entity_id, body)


@router.get("", name="list")
def list_caused_facts(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    source_event: Annotated[
        str, Query(pattern=ID_PATTERN, description="An event: the facts it caused.")
    ],
) -> FactList:
    """The facts whose source is the event (its "changes caused"), by entity, field and start.
    ``404`` for an event the request may not see."""
    return Facts(VaultContext(vault, session, registry), policy).caused_by(source_event)


@router.patch("/{fact_id}", name="update")
def update_fact(
    *,
    fact_id: FactIdPath,
    body: FactUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> FactWriteResult:
    """Change a fact's value, timeline, validity, visibility, source or note (revision
    required)."""
    request_suppress(session, body.suppress)
    return Facts(VaultContext(vault, session, registry)).update(fact_id, body)


@router.delete("/{fact_id}", name="delete")
def delete_fact(
    *,
    fact_id: FactIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> FactWriteResult:
    """Move the fact to the trash."""
    request_suppress(session, suppress.suppress if suppress else None)
    return Facts(VaultContext(vault, session, registry)).delete(fact_id)
