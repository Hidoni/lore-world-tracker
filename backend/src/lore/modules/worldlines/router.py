"""Routes of the worldlines module, mounted at ``/api/v1/vaults/{vault_id}/m/worldlines``
(``docs/modules/worldlines.md``)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.consistency.schemas import request_suppress
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.types import MomentStr
from lore.core.visibility import AUTHOR
from lore.modules.worldlines.schemas import (
    PersonalTimeline,
    Presence,
    SegmentsPut,
    TimeTravelIn,
    TimeTravelResult,
    Worldline,
    WorldlineWriteResult,
)
from lore.modules.worldlines.service import Worldlines
from lore.modules.worldlines.travel import TimeTravel

router = APIRouter(tags=["worldlines"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]
TimelineQuery = Annotated[
    str | None,
    Query(
        pattern=ID_PATTERN,
        description="The timeline of the home dimension an implicit worldline is read in "
        "(default: the prime).",
    ),
]
Include = Literal["participations", "existence", "jumps"]


@router.get("/entities/{entity_id}/segments", name="segments")
def get_segments(
    *,
    entity_id: IdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
) -> Worldline:
    """The entity's worldline (``time-model.md`` §11): its explicit segments in its own order,
    or the implicit worldline computed from its existence (`implicit: true`), each with its
    exact subjective start and end."""
    return Worldlines(VaultContext(vault, session, registry), policy).get(entity_id, timeline)


@router.put("/entities/{entity_id}/segments", name="replace_segments")
def replace_segments(
    *,
    entity_id: IdPath,
    body: SegmentsPut,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> WorldlineWriteResult:
    """Replace the entity's segments as a whole (an empty list: back to the implicit worldline).
    Its kind must have worldlines; each segment's timeline is one of its dimension, its time
    points resolve (they may be anchored to events of that dimension) with `start ≤ end`, and
    rates are positive (``422 validation_error``, paths `segments.<i>.…`)."""
    request_suppress(session, body.suppress)
    return Worldlines(VaultContext(vault, session, registry), AUTHOR).replace(entity_id, body)


@router.get("/entities/{entity_id}/presence", name="presence")
def presence(
    *,
    entity_id: IdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[str, Query(pattern=ID_PATTERN)],
    t: Annotated[MomentStr, Query(description="A moment of `dimension`.")],
    timeline: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="Default: the dimension's prime.")
    ] = None,
) -> Presence:
    """Every segment of the entity's worldline covering `t` in the timeline (§11.4): none
    (absent), one, or several (a time traveler present twice)."""
    service = Worldlines(VaultContext(vault, session, registry), policy)
    return service.presence(entity_id, dimension, timeline, int(t))


@router.get("/entities/{entity_id}/personal-timeline", name="personal_timeline")
def personal_timeline(
    *,
    entity_id: IdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    include: Annotated[list[Include] | None, Query(description="Default: all three.")] = None,
    timeline: TimelineQuery = None,
) -> PersonalTimeline:
    """The entity's experience in its own order (§11.5): participations, existence changes and
    jumps by exact subjective time, with ages in its personal clock dimension's default
    calendar."""
    service = Worldlines(VaultContext(vault, session, registry), policy)
    wanted = include or ["participations", "existence", "jumps"]
    return service.personal_timeline(entity_id, wanted, timeline)


@router.post("/entities/{entity_id}/time-travel", name="time_travel")
def time_travel(
    *,
    entity_id: IdPath,
    body: TimeTravelIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> TimeTravelResult:
    """The time-travel wizard in one transaction: the entity leaves at the departure (an event,
    or a moment, optionally creating a departure event) from the last segment covering it, and
    arrives in the destination (a timeline, the dimension's prime, or a new branch with the
    `branches` module on), optionally creating an arrival event; the entity takes part in the
    events it gets. An implicit worldline becomes explicit. Errors name the wizard's fields
    (`departure`, `destination.arrival`, `destination.until`, …)."""
    request_suppress(session, body.suppress)
    return TimeTravel(VaultContext(vault, session, registry)).run(entity_id, body)
