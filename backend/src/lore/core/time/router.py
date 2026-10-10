"""Time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Response

from lore.chronology.schema import MOMENT_PATTERN
from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    SettingsDep,
    VaultDep,
    VaultManagerDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.models import Entity
from lore.core.entities.schemas import (
    ID_PATTERN,
    EntityCreate,
    EntityDeleteResult,
    EntityWriteResult,
)
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.modules.spec import VaultContext
from lore.core.time.batch import convert_batch, resolve_batch
from lore.core.time.calendars import CALENDAR, Preview, presets
from lore.core.time.changes import report as report_time
from lore.core.time.dimensions import TIMELINE, timeline_tree
from lore.core.time.events import EVENT, EventTimes, event_tree, home_row, live_sub_events
from lore.core.time.models import Event, Proposal
from lore.core.time.proposals import BACKUP_REASON, apply_calendar_proposal, preview_calendar_edit
from lore.core.time.reconcile import apply_rule_change, preview_rule_change
from lore.core.time.resolve import Resolver
from lore.core.time.schemas import (
    CalendarApplyIn,
    CalendarApplyOut,
    CalendarPreviewIn,
    CalendarProposalIn,
    CalendarProposalOut,
    ConvertIn,
    ConvertOut,
    DimensionCreated,
    DimensionWizardIn,
    EventDisplay,
    EventTreeNode,
    EventTreePage,
    OccurrenceOut,
    OccurrencePage,
    PresetList,
    PresetOut,
    RecurrenceApplyIn,
    RecurrenceApplyOut,
    RecurrenceProposalIn,
    RecurrenceProposalOut,
    ResolveIn,
    ResolveOut,
    SeriesBandOut,
    TimelineTree,
    TimelineWindow,
    WindowBucket,
    WindowItemOut,
)
from lore.core.time.series import (
    NotASeriesError,
    RuleProblem,
    compute_occurrence,
    materialized_row,
    occurrences,
)
from lore.core.time.window import WindowQuery, timeline_window
from lore.core.time.wizard import create_dimension, preview_calendar
from lore.core.types import Affected
from lore.core.visibility import AUTHOR

router = APIRouter(prefix="/vaults/{vault_id}/dimensions", tags=["dimensions"])
events_router = APIRouter(prefix="/vaults/{vault_id}/events", tags=["events"])
calendars_router = APIRouter(prefix="/vaults/{vault_id}/calendars", tags=["calendars"])
time_router = APIRouter(prefix="/vaults/{vault_id}/time", tags=["time"])
timelines_router = APIRouter(prefix="/vaults/{vault_id}/timelines", tags=["timelines"])

DimensionIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Dimension id.")]
TimelineIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Timeline id.")]
EventIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Event id.")]
CalendarIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Calendar id.")]
ProposalIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Proposal id.")]


class OccurrenceNotFoundError(NotFoundError):
    code = "occurrence_not_found"
    title = "No such occurrence"


class OccurrenceInTrashError(ConflictError):
    code = "occurrence_in_trash"
    title = "Occurrence in the trash"


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


@router.post("", name="create", status_code=201)
def create(
    body: DimensionWizardIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    settings: SettingsDep,
) -> DimensionCreated:
    """The dimension wizard: a dimension (with its time spec), its prime timeline and its first
    calendar (from a preset or a full definition, which becomes the default), in one
    transaction."""
    return create_dimension(VaultContext(vault, session, registry), body, settings.spec_dir)


@calendars_router.get("/presets", name="presets")
def get_presets(_vault: VaultDep, settings: SettingsDep) -> PresetList:
    """The preset calendar catalog (written in seconds; instantiate one with a base unit through
    `preview` or the wizard)."""
    return PresetList(
        items=[
            PresetOut(
                id=preset.id,
                name=preset.name,
                description=preset.description,
                origin=preset.origin,
                duration_seconds=preset.requires.duration_seconds,
                definition=preset.definition.model_dump(
                    mode="json", by_alias=True, exclude_unset=True
                ),
            )
            for preset in presets(settings.spec_dir)
        ]
    )


@calendars_router.post("/preview", name="preview")
def post_preview(
    *,
    body: CalendarPreviewIn,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    settings: SettingsDep,
) -> Preview:
    """Compile an unsaved definition (or a preset instantiation) in a dimension's context: its
    errors (`ok: false`) or a few sample dates. Nothing is stored."""
    context = VaultContext(vault, session, registry)
    return preview_calendar(context, policy, body, settings.spec_dir)


def _calendar(context: VaultContext, calendar_id: str) -> Entity:
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    entity = EntityService(context).load(calendar_id)
    if entity.kind != CALENDAR:
        raise NotFoundError(f"No calendar {calendar_id}.")
    return entity


def calendar_proposal_out(proposal: Proposal) -> CalendarProposalOut:
    impact = proposal.impact
    return CalendarProposalOut.model_validate(
        {
            "id": proposal.id,
            "calendar_id": proposal.target_id,
            "base_revision": proposal.base_revision,
            "created_at": proposal.created_at,
            "expires_at": proposal.expires_at,
            **{key: impact[key] for key in
               ("display_calendar_id", "definition", "items", "series", "summary")},
        }
    )  # fmt: skip


@calendars_router.post("/{calendar_id}/proposals", name="propose", status_code=201)
def post_calendar_proposal(
    calendar_id: CalendarIdPath,
    body: CalendarProposalIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> CalendarProposalOut:
    """Preview a calendar edit (``time-model.md`` §7.4, D1): every record whose moment or status
    the new definition changes, with old/new moments and displays, its status and the strategies
    it takes. Invalid definitions fail fast (``422 calendar_invalid``). The proposal is kept for an
    hour; apply it to save the definition."""
    context = VaultContext(vault, session, registry)
    proposal = preview_calendar_edit(context, _calendar(context, calendar_id), body.definition)
    return calendar_proposal_out(proposal)


@calendars_router.post("/{calendar_id}/proposals/{proposal_id}/apply", name="apply_proposal")
def post_calendar_apply(
    *,
    calendar_id: CalendarIdPath,
    proposal_id: ProposalIdPath,
    body: CalendarApplyIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    manager: VaultManagerDep,
) -> CalendarApplyOut:
    """Apply a calendar proposal: save the definition, apply each record's strategy
    (``keep_date``, ``pin_moment``, ``constrain``) and propagate, as one changeset (one undo).
    ``409 proposal_stale`` when anything it was computed from changed; ``422
    proposal_unresolved`` for records left broken without an explicit strategy. More than 100
    items take a backup first."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    request_suppress(session, body.suppress)
    entity = _calendar(context, calendar_id)
    applied = apply_calendar_proposal(
        context,
        entity,
        proposal_id,
        strategies=body.strategies,
        default_strategy=body.default_strategy,
        backup=lambda: manager.backup_before(vault.id, BACKUP_REASON).id,
    )
    return CalendarApplyOut(
        calendar=EntityService(context).to_out(entity),
        kept=applied.kept,
        pinned=applied.pinned,
        constrained=applied.constrained,
        accepted=applied.accepted,
        backup=applied.backup,
        affected=report_time(
            session,
            registry,
            Affected(
                entities=applied.entity_ids,
                dimensions=[str(entity.dimension_id)],
                time_changed=True,
                search_changed=False,
            ),
        ),
    )


@time_router.post("/resolve", name="resolve")
def post_resolve(
    body: ResolveIn,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> ResolveOut:
    """Resolve time points (and end specs) of a dimension: moment, uncertainty extent,
    precision, status and display in the default (or given) calendar. Problems are reported per
    item. Stores nothing."""
    return resolve_batch(VaultContext(vault, session, registry), policy, body)


@time_router.post("/convert", name="convert")
def post_convert(
    body: ConvertIn,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> ConvertOut:
    """Moments of a dimension as fields and displays in the given calendars (`absolute` for raw
    base units). Stores nothing."""
    return convert_batch(VaultContext(vault, session, registry), policy, body)


@timelines_router.get("/{timeline_id}/event-tree", name="event_tree")
def get_event_tree(
    *,
    timeline_id: TimelineIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    parent: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="An event: list its sub-events (default: roots)."),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> EventTreePage:
    """One level of the timeline's event outline: the sub-events of ``parent``, or the root
    events (those whose parent the tree doesn't show). Ordered by start, longer first on equal
    starts, then by name. ``404`` for a timeline or parent the request may not see."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    entities = EntityService(context, policy)
    timeline = entities.load_visible(timeline_id)
    if timeline.kind != TIMELINE or timeline.deleted_at is not None:
        raise NotFoundError(f"No timeline {timeline_id}.")
    if parent is not None and entities.load_visible(parent).kind != EVENT:
        raise NotFoundError(f"No event {parent}.")
    rows, next_cursor = event_tree(
        context, policy, timeline_id, parent_id=parent, cursor=cursor, limit=limit
    )
    times = EventTimes(context, policy)
    return EventTreePage(
        items=[
            EventTreeNode(
                id=item.entity.id,
                name=item.entity.name,
                visibility=item.entity.visibility,
                parent_id=entities.visible_parent(item.entity),
                start_t=item.row.start_t,
                end_t=item.row.end_t,
                time_status=item.row.time_status,
                importance=item.row.importance,
                category=item.row.category,
                display=EventDisplay.model_validate(
                    times.displays(str(item.entity.dimension_id), item.row)
                ),
                has_children=item.has_children,
            )
            for item in rows
        ],
        next_cursor=next_cursor,
    )


@timelines_router.get("/{timeline_id}/window", name="window")
def get_window(
    *,
    timeline_id: TimelineIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    start: Annotated[
        str,
        Query(
            alias="from",
            pattern=MOMENT_PATTERN,
            max_length=1000,
            description="The window's first moment.",
        ),
    ],
    end: Annotated[
        str,
        Query(
            alias="to",
            pattern=MOMENT_PATTERN,
            max_length=1000,
            description="The moment after the window (half-open).",
        ),
    ],
    px: Annotated[int, Query(ge=1, le=20_000, description="The window's width in pixels.")],
    min_importance: Annotated[int | None, Query(ge=1, le=5)] = None,
    categories: Annotated[
        list[str] | None, Query(alias="category", description="Categories (any; repeatable).")
    ] = None,
    tags: Annotated[
        list[str] | None, Query(alias="tag", description="Tag ids (all required; repeatable).")
    ] = None,
    participants: Annotated[
        list[str] | None,
        Query(alias="participant", description="Entity ids (any of them takes part; repeatable)."),
    ] = None,
    parent: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="An event: only its sub-events (any depth)."),
    ] = None,
    include_series: Annotated[
        bool,
        Query(description="Expand recurring series into occurrences (or bands when too many)."),
    ] = True,
    include_cancelled: Annotated[
        bool, Query(description="Show cancelled occurrences (materialized, with their state).")
    ] = False,
) -> TimelineWindow:
    """The events of the timeline overlapping ``[from, to)``: at most ``min(px, 2000)`` of them,
    by importance, then duration, then start; the rest are counted in density buckets
    (``px / 4`` of them). ``404`` for a timeline or parent the request may not see."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    entities = EntityService(context, policy)
    timeline = entities.load_visible(timeline_id)
    if timeline.kind != TIMELINE or timeline.deleted_at is not None:
        raise NotFoundError(f"No timeline {timeline_id}.")
    if parent is not None and entities.load_visible(parent).kind != EVENT:
        raise NotFoundError(f"No event {parent}.")
    window = timeline_window(
        context,
        policy,
        timeline_id,
        WindowQuery(
            start=int(start),
            end=int(end),
            px=px,
            min_importance=min_importance,
            categories=tuple(categories or ()),
            tags=tuple(tags or ()),
            participants=tuple(participants or ()),
            parent=parent,
            include_series=include_series,
            include_cancelled=include_cancelled,
        ),
    )
    return TimelineWindow(
        items=[
            WindowItemOut(
                entity_id=item.entity_id,
                row_id=item.row_id,
                name=item.name,
                visibility=item.visibility,  # type: ignore[arg-type]
                parent_id=item.parent_id,
                has_children=item.has_children,
                start_t=item.start_t,
                end_t=item.end_t,
                start_precision=item.start_precision,
                start_approximate=item.start_approximate,
                end_kind=item.end_kind,
                end_precision=item.end_precision,
                end_approximate=item.end_approximate,
                importance=item.importance,
                category=item.category,
                time_status=item.time_status,
                occurrence_key=item.occurrence_key,
                series_id=item.series_id,
                occurrence_state=item.occurrence_state,
            )
            for item in window.items
        ],
        buckets=[
            WindowBucket(from_t=b.start, to_t=b.end, starts=b.starts, active=b.active)
            for b in window.buckets
        ],
        series_bands=[
            SeriesBandOut(
                entity_id=band.entity_id,
                row_id=band.row_id,
                name=band.name,
                visibility=band.visibility,  # type: ignore[arg-type]
                importance=band.importance,
                category=band.category,
                from_t=band.start,
                to_t=band.end,
                estimated_count=band.estimated_count,
            )
            for band in window.series_bands
        ],
        total=window.total,
        culled=window.culled,
    )


@events_router.get("/{event_id}/occurrences", name="occurrences")
def get_occurrences(
    *,
    event_id: EventIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    start: Annotated[
        str,
        Query(
            alias="from",
            pattern=MOMENT_PATTERN,
            max_length=1000,
            description="The window's first moment.",
        ),
    ],
    end: Annotated[
        str,
        Query(
            alias="to",
            pattern=MOMENT_PATTERN,
            max_length=1000,
            description="The moment after the window (half-open).",
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    include_cancelled: Annotated[
        bool, Query(description="List cancelled occurrences too (with their state).")
    ] = False,
) -> OccurrencePage:
    """The occurrences of a recurring event overlapping ``[from, to)``: computed from its rule
    (``recurrence.md`` §4 ``expand``) and replaced by their materialized occurrences (§7). More
    than ``limit`` of them give ``truncated`` with a count and no items. ``404`` for an event the
    request may not see, ``409 not_a_series`` for an event that doesn't recur."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    entity = EntityService(context, policy).load_visible(event_id)
    row = home_row(session, entity.id) if entity.kind == EVENT else None
    if row is None:
        raise NotFoundError(f"No event {event_id}.")
    if int(start) >= int(end):
        raise InvalidInputError(
            "The window must end after it starts.",
            errors=[ErrorItem(path="to", code="invalid_value",
                              message="The window must end after it starts.")],
        )  # fmt: skip
    listed = occurrences(
        context, policy, row, (int(start), int(end)), limit, include_cancelled=include_cancelled
    )
    return OccurrencePage(
        items=[
            OccurrenceOut(
                key=o.key,
                start_t=o.start,
                end_t=o.end,
                number=o.number,
                entity_id=o.entity_id,
                state=o.state,
            )
            for o in listed.items
        ],
        truncated=listed.truncated,
        estimated_count=listed.estimated_count,
    )


OccurrenceKeyPath = Annotated[
    str,
    Path(pattern=r"^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$", max_length=1100,
         description="Occurrence key: `k`, or `k.j`."),
]  # fmt: skip


def _series_row(context: VaultContext, event_id: str) -> tuple[Entity, Event]:
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    entity = EntityService(context).load(event_id)
    row = home_row(context.session, entity.id) if entity.kind == EVENT else None
    if row is None:
        raise NotFoundError(f"No event {event_id}.")
    if row.recurrence is None:
        raise NotASeriesError("The event doesn't recur.")
    return entity, row


@events_router.post("/{event_id}/occurrences/{key}", name="materialize_occurrence")
def post_occurrence(
    *,
    event_id: EventIdPath,
    key: OccurrenceKeyPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    response: Response,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> EntityWriteResult:
    """Materialize an occurrence (``recurrence.md`` §7), get-or-create: ``201`` with a new event
    entity anchored to the occurrence (``occurrence_state = referenced``, named "<series>
    (<date>)"), or ``200`` with the existing one. ``404 occurrence_not_found`` for a key without
    an occurrence, ``409 not_a_series``, ``409 occurrence_in_trash`` when its materialized
    occurrence is in the trash (restore or purge it)."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    request_suppress(session, suppress.suppress if suppress else None)
    service = EntityService(context)
    series_entity, row = _series_row(context, event_id)
    existing = materialized_row(session, series_entity.id, key, row.timeline_id)
    if existing is not None:
        found = service.load(existing.entity_id)
        if found.deleted_at is not None:
            raise OccurrenceInTrashError(
                "The occurrence's materialized event is in the trash: restore or purge it.",
                context={"entity_id": found.id},
            )
        response.status_code = 200
        return EntityWriteResult(
            entity=service.to_out(found),
            affected=Affected(entities=[], dimensions=[], time_changed=False,
                              search_changed=False),
        )  # fmt: skip
    assert series_entity.dimension_id is not None
    resolver = Resolver(context, series_entity.dimension_id, row.timeline_id)
    computed = compute_occurrence(resolver, row, key)
    if isinstance(computed, RuleProblem):
        raise OccurrenceNotFoundError(f"The series has no occurrence {key!r}.")
    shown = EventTimes(context, AUTHOR).occurrence_display(
        series_entity.dimension_id, row, computed.start
    )
    name = f"{series_entity.name} ({shown})" if shown else series_entity.name
    response.status_code = 201
    return service.create(
        EntityCreate(
            kind=EVENT,
            name=name[:200],
            dimension_id=series_entity.dimension_id,
            visibility=series_entity.visibility,
            ext={"series_id": series_entity.id, "occurrence_key": key},
        )
    )


@events_router.delete("/{event_id}/occurrences/{key}", name="delete_occurrence")
def delete_occurrence(
    *,
    event_id: EventIdPath,
    key: OccurrenceKeyPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    trash_sub_events: Annotated[
        bool, Query(description="Confirm moving the occurrence's sub-events to the trash too.")
    ] = False,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> EntityDeleteResult:
    """Revert an occurrence to the computed one by moving its materialized event to the trash
    (``recurrence.md`` §7). One with sub-events needs ``trash_sub_events=true`` (else ``409
    occurrence_has_sub_events``), which trashes them too. ``404`` without a materialized
    occurrence."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    request_suppress(session, suppress.suppress if suppress else None)
    service = EntityService(context)
    series_entity, row = _series_row(context, event_id)
    existing = materialized_row(session, series_entity.id, key, row.timeline_id)
    if existing is None or service.load(existing.entity_id).deleted_at is not None:
        raise NotFoundError(f"Occurrence {key!r} isn't materialized.")
    if trash_sub_events:
        for child in live_sub_events(session, existing.entity_id):
            service.trash(child)
    return service.trash(existing.entity_id)


def _event(context: VaultContext, event_id: str) -> Entity:
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    entity = EntityService(context).load(event_id)
    if entity.kind != EVENT:
        raise NotFoundError(f"No event {event_id}.")
    return entity


@events_router.post("/{event_id}/recurrence/proposals", name="propose_recurrence", status_code=201)
def post_recurrence_proposal(
    event_id: EventIdPath,
    body: RecurrenceProposalIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> RecurrenceProposalOut:
    """Preview a change of an event's recurrence rule (and optionally its start and end):
    every materialized occurrence with its status (``unchanged``, ``moved``, ``orphaned``,
    ``recurrence.md`` §8) and the strategies it takes. The change is checked like a PATCH (``422``
    on ``rule…``, ``start``, ``end``). The proposal is kept for an hour."""
    context = VaultContext(vault, session, registry)
    payload = body.model_dump(mode="json", by_alias=True, exclude_unset=True)
    proposal = preview_rule_change(context, _event(context, event_id), payload)
    return RecurrenceProposalOut.model_validate(
        {
            "id": proposal.id,
            "event_id": proposal.target_id,
            "base_revision": proposal.base_revision,
            "created_at": proposal.created_at,
            "expires_at": proposal.expires_at,
            **proposal.impact,
        }
    )


@events_router.post(
    "/{event_id}/recurrence/proposals/{proposal_id}/apply", name="apply_recurrence_proposal"
)
def post_recurrence_apply(
    *,
    event_id: EventIdPath,
    proposal_id: ProposalIdPath,
    body: RecurrenceApplyIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> RecurrenceApplyOut:
    """Apply a recurrence proposal: reconcile each materialized occurrence (``keep_key``,
    ``rekey``, ``detach``, ``trash``; others take their default) and save the series' rule, start
    and end, as one changeset. ``409 proposal_stale`` when the series or its occurrences changed,
    ``409 rekey_conflict`` when two occurrences would share a key."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    context = VaultContext(vault, session, registry)
    request_suppress(session, body.suppress)
    entity = _event(context, event_id)
    applied = apply_rule_change(context, entity, proposal_id, body.strategies)
    return RecurrenceApplyOut(
        event=EntityService(context).to_out(entity),
        kept=applied.kept,
        rekeyed=applied.rekeyed,
        detached=applied.detached,
        trashed=applied.trashed,
        affected=report_time(
            session,
            registry,
            Affected(
                entities=applied.entity_ids,
                dimensions=[str(entity.dimension_id)],
                time_changed=True,
                search_changed=applied.trashed > 0,
            ),
        ),
    )
