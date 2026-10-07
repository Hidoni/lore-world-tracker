"""Time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.chronology.schema import MOMENT_PATTERN
from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    SettingsDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.entities.schemas import ID_PATTERN
from lore.core.errors import NotFoundError
from lore.core.modules.spec import VaultContext
from lore.core.time.batch import convert_batch, resolve_batch
from lore.core.time.calendars import Preview, presets
from lore.core.time.dimensions import TIMELINE, timeline_tree
from lore.core.time.events import EVENT, EventTimes, event_tree
from lore.core.time.schemas import (
    CalendarPreviewIn,
    ConvertIn,
    ConvertOut,
    DimensionCreated,
    DimensionWizardIn,
    EventDisplay,
    EventTreeNode,
    EventTreePage,
    PresetList,
    PresetOut,
    ResolveIn,
    ResolveOut,
    TimelineTree,
    TimelineWindow,
    WindowBucket,
    WindowItemOut,
)
from lore.core.time.window import WindowQuery, timeline_window
from lore.core.time.wizard import create_dimension, preview_calendar

router = APIRouter(prefix="/vaults/{vault_id}/dimensions", tags=["dimensions"])
calendars_router = APIRouter(prefix="/vaults/{vault_id}/calendars", tags=["calendars"])
time_router = APIRouter(prefix="/vaults/{vault_id}/time", tags=["time"])
timelines_router = APIRouter(prefix="/vaults/{vault_id}/timelines", tags=["timelines"])

DimensionIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Dimension id.")]
TimelineIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Timeline id.")]


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
    include_series: Annotated[bool, Query(description="Recurring series (#52).")] = True,
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
    _ = include_series  # series bands arrive with recurring events (#52)
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
            )
            for item in window.items
        ],
        buckets=[
            WindowBucket(from_t=b.start, to_t=b.end, starts=b.starts, active=b.active)
            for b in window.buckets
        ],
        series_bands=[],
        total=window.total,
        culled=window.culled,
    )
