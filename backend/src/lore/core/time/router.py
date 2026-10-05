"""Time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Annotated

from fastapi import APIRouter, Path

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.time.dimensions import timeline_tree
from lore.core.time.schemas import TimelineTree

router = APIRouter(prefix="/vaults/{vault_id}/dimensions", tags=["dimensions"])

DimensionIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Dimension id.")]


@router.get("/{dimension_id}/timelines", name="timelines")
def get_timelines(
    dimension_id: DimensionIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> TimelineTree:
    """The dimension's timeline tree: the prime timeline and its branches (``404`` for a
    dimension the request may not see)."""
    return timeline_tree(VaultContext(vault, session, registry), policy, dimension_id)
