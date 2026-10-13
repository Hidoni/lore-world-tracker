"""Routes of the groups module, mounted at ``/api/v1/vaults/{vault_id}/m/groups``."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.chronology.schema import MOMENT_PATTERN
from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.entities.schemas import ID_PATTERN
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import link_cursor
from lore.core.modules.spec import VaultContext
from lore.modules.groups.schemas import Leaders, Members, OrgChart
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
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> Members:
    """Everyone and everything `groups.member_of` the group (and, with ``include_subgroups``,
    its sub-groups), at any time, or with ``at`` those members then (as in entity links).
    ``404`` for a group the request may not see."""
    context = VaultContext(vault, session, registry)
    as_of = link_cursor(context, policy, group_id, timeline, at)
    return Groups(context, policy).members(
        group_id, include_subgroups=include_subgroups, as_of=as_of
    )


@router.get("/{group_id}/leaders", name="leaders")
def get_leaders(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> Leaders:
    """The leadership succession (`groups.led_by`): timeless leaders first, then by the start of
    their validity (with ``at``: the leaders then). ``404`` for a group the request may not
    see."""
    context = VaultContext(vault, session, registry)
    as_of = link_cursor(context, policy, group_id, timeline, at)
    return Groups(context, policy).leaders(group_id, as_of=as_of)


@router.get("/{group_id}/territory", name="territory")
def get_territory(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> EntityLinks:
    """The locations the group controls (`groups.controls`), at any time (with ``at``: then).
    ``404`` for a group the request may not see."""
    context = VaultContext(vault, session, registry)
    as_of = link_cursor(context, policy, group_id, timeline, at)
    return Groups(context, policy).territory(group_id, as_of=as_of)


@router.get("/{group_id}/org-chart", name="org_chart")
def get_org_chart(
    *,
    group_id: GroupIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    depth: Annotated[int, Query(ge=1, le=10, description="Levels below the group.")] = 3,
    timeline: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="The timeline `at` is read on.")
    ] = None,
    at: Annotated[
        str | None,
        Query(
            pattern=MOMENT_PATTERN,
            max_length=1000,
            description="Only links valid at this moment (`part_of`, leaders, members).",
        ),
    ] = None,
) -> OrgChart:
    """The group's org chart: sub-groups and parts ``depth`` levels down, each with its leaders
    and member count, as of ``at`` (all links without it). ``404`` for a group or timeline the
    request may not see."""
    return Groups(VaultContext(vault, session, registry), policy).org_chart(
        group_id, depth=depth, at=None if at is None else int(at), timeline_id=timeline
    )
