"""Routes of the locations module, mounted at ``/api/v1/vaults/{vault_id}/m/locations``."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.chronology.schema import MOMENT_PATTERN
from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.api.time_cursor import AtQuery, TimelineQuery
from lore.core.entities.schemas import ID_PATTERN
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import LinkService, link_cursor
from lore.core.modules.spec import VaultContext
from lore.modules.locations.links import RESIDES_IN
from lore.modules.locations.schemas import LocationEvents, LocationTree
from lore.modules.locations.service import Locations

router = APIRouter(tags=["locations"])

LocationIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Location id.")]
IdQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]


@router.get("/tree", name="tree")
def get_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: IdQuery = None,
    root: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="A location: list what it contains (default: top)."),
    ] = None,
    depth: Annotated[int, Query(ge=1, le=6, description="Levels to load.")] = 1,
    limit: Annotated[int, Query(ge=1, le=500, description="Nodes per level at most.")] = 200,
) -> LocationTree:
    """The containment tree of locations, ``depth`` levels from ``root`` (or the top-level
    locations, in ``dimension`` when given), with their types and child counts. Deeper levels
    load with ``root``. ``404`` for a root the request may not see."""
    locations = Locations(VaultContext(vault, session, registry), policy)
    return locations.tree(dimension=dimension, root=root, depth=depth, limit=limit)


@router.get("/{location_id}/events", name="events")
def get_events(
    *,
    location_id: LocationIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: Annotated[str, Query(pattern=ID_PATTERN, description="The timeline to read.")],
    include_descendants: bool = True,
    start: Annotated[
        str | None,
        Query(alias="from", pattern=MOMENT_PATTERN, max_length=1000, description="Window start."),
    ] = None,
    end: Annotated[
        str | None,
        Query(alias="to", pattern=MOMENT_PATTERN, max_length=1000, description="Window end."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> LocationEvents:
    """What happened here: events the timeline shows whose `locations.event_site` is this
    location (or, with ``include_descendants``, a location inside it), by start. ``from``/``to``
    keep those overlapping the half-open window. ``404`` for a location or timeline the request
    may not see."""
    locations = Locations(VaultContext(vault, session, registry), policy)
    return locations.events(
        location_id,
        timeline_id=timeline,
        descendants=include_descendants,
        start=None if start is None else int(start),
        end=None if end is None else int(end),
        limit=limit,
    )


@router.get("/{location_id}/residents", name="residents")
def get_residents(
    *,
    location_id: LocationIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> EntityLinks:
    """Everyone and everything that `locations.resides_in` the location, at any time (with each
    link's validity), or with ``at`` those residing there then. ``404`` for a location the
    request may not see."""
    context = VaultContext(vault, session, registry)
    Locations(context, policy).location(location_id)
    as_of = link_cursor(context, policy, location_id, timeline, at)
    return LinkService(session, registry, policy, vault).entity_links(
        location_id, direction="in", types=[RESIDES_IN], as_of=as_of
    )
