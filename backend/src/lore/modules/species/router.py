"""Routes of the species module, mounted at ``/api/v1/vaults/{vault_id}/m/species``."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.entities.schemas import ID_PATTERN
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import link_cursor
from lore.core.modules.spec import VaultContext
from lore.modules.species.schemas import DescentTree
from lore.modules.species.service import Species

router = APIRouter(tags=["species"])


@router.get("/descent-tree", name="descent_tree")
def get_descent_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="Species of a dimension (and multiversal ones)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Species at most.")] = 500,
) -> DescentTree:
    """The descent graph: species the request sees with the `descended_from` links between
    them, and subspecies edges to their parent species."""
    return Species(VaultContext(vault, session, registry), policy).descent_tree(
        dimension=dimension, limit=limit
    )


@router.get("/{species_id}/members", name="members")
def get_members(
    *,
    species_id: Annotated[str, Path(pattern=ID_PATTERN, description="Species id.")],
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> EntityLinks:
    """Everyone and everything that `species.is_a` the species, at any time (with ``at``:
    then, as in entity links). ``404`` for a species the request may not see."""
    context = VaultContext(vault, session, registry)
    as_of = link_cursor(context, policy, species_id, timeline, at)
    return Species(context, policy).members(species_id, as_of=as_of)
