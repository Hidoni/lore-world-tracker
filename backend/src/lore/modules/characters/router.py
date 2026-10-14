"""Routes of the characters module, mounted at ``/api/v1/vaults/{vault_id}/m/characters``."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.entities.schemas import ID_PATTERN
from lore.core.links.service import link_cursor
from lore.core.modules.spec import VaultContext
from lore.modules.characters.schemas import Genealogy, Life, Relationships
from lore.modules.characters.service import Characters

router = APIRouter(tags=["characters"])

CharacterIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Character id.")]


@router.get("/{character_id}/relationships", name="relationships")
def get_relationships(
    *,
    character_id: CharacterIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> Relationships:
    """The character's relationships by category: family, social, and custom (the generic
    `characters.relationship` and user-defined link types to characters), at any time, or with
    ``at`` those valid then (as in entity links). ``404`` for a character the request may not
    see."""
    context = VaultContext(vault, session, registry)
    as_of = link_cursor(context, policy, character_id, timeline, at)
    return Characters(context, policy).relationships(character_id, as_of=as_of)


@router.get("/{character_id}/life", name="life")
def get_life(
    *,
    character_id: CharacterIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: Annotated[str, Query(pattern=ID_PATTERN, description="The timeline to read.")],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> Life:
    """The events on the timeline the character takes part in (`core.participant`), by start,
    with their roles. ``404`` for a character or timeline the request may not see."""
    characters = Characters(VaultContext(vault, session, registry), policy)
    return characters.life(character_id, timeline_id=timeline, limit=limit)


@router.get("/{character_id}/family-tree", name="family_tree")
def get_family_tree(
    *,
    character_id: CharacterIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    up: Annotated[int, Query(ge=0, le=10, description="Generations of ancestors.")] = 3,
    down: Annotated[int, Query(ge=0, le=10, description="Generations of descendants.")] = 3,
    include_spouses: bool = True,
    include_siblings: bool = True,
    timeline: Annotated[
        str | None,
        Query(
            pattern=ID_PATTERN,
            description="The timeline lifespans (and `at`) are read on (default: the prime "
            "timeline of the character's dimension).",
        ),
    ] = None,
    at: AtQuery = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="People at most.")] = 500,
) -> Genealogy:
    """The character's family for the genealogy layout: people (by generation, with their
    lifespans, and their existence at ``at``) and the parent, spouse and sibling links between
    them that the request sees. ``404`` for a character or timeline the request may not see."""
    characters = Characters(VaultContext(vault, session, registry), policy)
    return characters.family_tree(
        character_id,
        up=up,
        down=down,
        include_spouses=include_spouses,
        include_siblings=include_siblings,
        timeline_id=timeline,
        at=at,
        limit=limit,
    )
