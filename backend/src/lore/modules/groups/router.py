"""Routes of the groups module, mounted at ``/api/v1/vaults/{vault_id}/m/groups``."""

from typing import Annotated

from fastapi import APIRouter, Path

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.entities.schemas import ID_PATTERN
from lore.core.links.schemas import EntityLinks
from lore.core.modules.spec import VaultContext
from lore.modules.groups.schemas import Leaders, Members
from lore.modules.groups.service import Groups

router = APIRouter(tags=["groups"])

GroupIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Group id.")]


@router.get("/{group_id}/members", name="members")
def get_members(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    include_subgroups: bool = False,
) -> Members:
    """Everyone and everything `groups.member_of` the group (and, with ``include_subgroups``,
    its sub-groups), at any time (as-of filtering comes with the time cursor). ``404`` for a
    group the request may not see."""
    return Groups(VaultContext(vault, session, registry), policy).members(
        group_id, include_subgroups=include_subgroups
    )


@router.get("/{group_id}/leaders", name="leaders")
def get_leaders(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> Leaders:
    """The leadership succession (`groups.led_by`): timeless leaders first, then by the start of
    their validity. ``404`` for a group the request may not see."""
    return Groups(VaultContext(vault, session, registry), policy).leaders(group_id)


@router.get("/{group_id}/territory", name="territory")
def get_territory(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> EntityLinks:
    """The locations the group controls (`groups.controls`), at any time. ``404`` for a group
    the request may not see."""
    return Groups(VaultContext(vault, session, registry), policy).territory(group_id)
