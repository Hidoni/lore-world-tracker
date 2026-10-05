"""Time routes (``docs/architecture/api.md`` §2, Time)."""

from typing import Annotated

from fastapi import APIRouter, Path

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    SettingsDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.time.calendars import Preview, presets
from lore.core.time.dimensions import timeline_tree
from lore.core.time.schemas import (
    CalendarPreviewIn,
    DimensionCreated,
    DimensionWizardIn,
    PresetList,
    PresetOut,
    TimelineTree,
)
from lore.core.time.wizard import create_dimension, preview_calendar

router = APIRouter(prefix="/vaults/{vault_id}/dimensions", tags=["dimensions"])
calendars_router = APIRouter(prefix="/vaults/{vault_id}/calendars", tags=["calendars"])

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
