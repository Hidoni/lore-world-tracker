"""Test-only modules that exercise every ``ModuleSpec`` extension point.

``base`` ← ``sample`` ← ``addon`` form a dependency chain; ``optional`` is off by default.
Their models use their own declarative base so they never leak into the real migration metadata.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lore.chronology.schema import TimePoint
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec, VaultContext
from lore.core.registry import (
    FieldContribution,
    FieldDef,
    FieldOption,
    FieldTypeDef,
    GraphStyle,
    KindCapabilities,
    KindDef,
    LinkTypeDef,
    QuickFixDef,
    RuleDef,
    Trigger,
)
from lore.core.richtext.handlers import RichTextNodeHandler
from lore.core.search import SearchContributor
from lore.core.time import SlotDef, SlotProvider, moment_column, spec_column, status_column
from lore.core.visibility import VisibilityFilter


class SampleBase(DeclarativeBase):
    pass


class SampleNote(SampleBase):
    __tablename__ = "sample_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[str] = mapped_column(String)
    noted_spec: Mapped[TimePoint | None] = spec_column()
    noted_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()


class SampleSettings(BaseModel):
    greeting: str = "hello"


HOOK_CALLS: list[tuple[str, str]] = []


def _hook(event: str, module_id: str):  # type: ignore[no-untyped-def]
    def hook(context: VaultContext) -> None:
        assert context.session.in_transaction()
        HOOK_CALLS.append((event, module_id))

    return hook


def _stamp_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(attrs.get("seal"), str):
        raise ValueError("a stamp needs a seal")
    return {"seal": attrs["seal"]}


# An inline module node: its seal is text; readers only see public seals.
STAMP = RichTextNodeHandler(
    type="sampleStamp",
    group="inline",
    validate_attrs=_stamp_attrs,
    filter_for_reader=lambda node, _visible: None if node["attrs"]["seal"] == "secret" else node,
    extract_text=lambda node: node["attrs"]["seal"],
    ref_kind="stamp",
    extract_refs=lambda node: [node["attrs"]["seal"]],
)

sample_router = APIRouter(tags=["sample"])


@sample_router.get("/ping", name="ping")
def ping() -> dict[str, str]:
    return {"pong": "sample"}


addon_router = APIRouter(tags=["addon"])


@addon_router.get("/ping", name="ping")
def addon_ping() -> dict[str, str]:
    return {"pong": "addon"}


BASE = ModuleSpec(
    id="base",
    name="Base",
    description="The bottom of the chain.",
    kinds=(
        KindDef(
            "place",
            "Place",
            "Places",
            icon="map-pin",
            color="#16a34a",
            allowed_parents=("place", "misc"),
        ),
    ),
    on_enable=_hook("enable", "base"),
    on_disable=_hook("disable", "base"),
)

SAMPLE = ModuleSpec(
    id="sample",
    name="Sample",
    description="Every extension point.",
    depends_on=("base",),
    kinds=(
        KindDef(
            "creature",
            "Creature",
            "Creatures",
            icon="paw-print",
            color="#dc2626",
            description="A beast.",
            allowed_parents=("creature", "misc"),
            fields=(
                FieldDef(
                    "diet",
                    "Diet",
                    "enum",
                    options=(FieldOption("meat", "Meat"), FieldOption("plants", "Plants", "#0f0")),
                ),
                FieldDef("danger", "Danger", "sample_rating", temporal=True, sort=2),
                FieldDef(
                    "lore",
                    "Lore",
                    "rich_text",
                    default_visibility="spoiler",
                    section="Details",
                    help="What people tell.",
                    searchable=False,
                ),
            ),
            capabilities=KindCapabilities(can_have_worldline=True),
        ),
    ),
    field_contributions=(
        FieldContribution("event", (FieldDef("sample.mood", "Mood", "text"),)),
        FieldContribution("place", (FieldDef("sample.lair", "Lair", "boolean"),)),
    ),
    field_types=(FieldTypeDef("sample_rating", "Rating", "1 to 5 stars."),),
    link_types=(
        LinkTypeDef(
            "sample.hunts",
            "hunts",
            inverse_label="hunted by",
            source_kinds=("creature",),
            target_kinds="*",
            temporal="optional",
            unique="per_pair",
            max_targets_per_source=3,
            data_schema={"type": "object"},
            graph=GraphStyle("#f00", True, 2),
        ),
        LinkTypeDef(
            "sample.lives_in", "lives in", source_kinds=("creature",), target_kinds=("place",)
        ),
    ),
    models=(SampleNote,),
    history_tables=(HistoryTable.of(SampleNote),),
    routers=(sample_router,),
    slot_providers=(
        SlotProvider("sample.note", SampleNote, (SlotDef("noted", referenceable=True),)),
    ),
    timeline_tables=(object(),),
    search_contributors=(SearchContributor("sample.note", lambda _c, _ids: [], "Note", "note"),),
    graph_contributors=(object(),),
    consistency_rules=(
        RuleDef(
            id="sample.creature.too_dangerous",
            owner="sample",
            title="Too dangerous",
            description="Lower the danger.",
            category="module",
            default_severity="warning",
            triggers=(Trigger("field", "danger"),),
            quick_fixes=(QuickFixDef("sample.calm", "Calm it down"),),
        ),
    ),
    visibility_filters=(VisibilityFilter(SampleNote, visibility_column=None),),
    richtext_nodes=(STAMP,),
    backup_contributors=(object(),),
    publish_contributors=(object(),),
    settings_model=SampleSettings,
    on_enable=_hook("enable", "sample"),
    on_disable=_hook("disable", "sample"),
)

ADDON = ModuleSpec(
    id="addon",
    name="Add-on",
    description="Depends on sample.",
    depends_on=("sample",),
    link_types=(
        LinkTypeDef(
            "addon.befriends",
            "befriends",
            source_kinds=("creature",),
            target_kinds=("creature",),
            symmetric=True,
        ),
    ),
    routers=(addon_router,),
    on_disable=_hook("disable", "addon"),
)

OPTIONAL = ModuleSpec(
    id="optional",
    name="Optional",
    description="Off by default.",
    default_enabled=False,
    # A cross-module link type without a dependency: offered only while `sample` is enabled.
    link_types=(LinkTypeDef("optional.studies", "studies", target_kinds=("creature",)),),
)

SAMPLE_MODULES = (BASE, SAMPLE, ADDON, OPTIONAL)
