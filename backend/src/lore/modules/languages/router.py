"""Routes of the languages module, mounted at ``/api/v1/vaults/{vault_id}/m/languages``."""

from typing import Annotated

from fastapi import APIRouter, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.modules.languages.schemas import FamilyTree
from lore.modules.languages.service import Languages

router = APIRouter(tags=["languages"])


@router.get("/family-tree", name="family_tree")
def get_family_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="Languages of a dimension (and multiversal ones)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Languages at most.")] = 500,
) -> FamilyTree:
    """The language family graph: languages the request sees with the `descended_from` and
    `borrowed_from` links between them, and dialect edges to their parent languages."""
    return Languages(VaultContext(vault, session, registry), policy).family_tree(
        dimension=dimension, limit=limit
    )
