"""The sample world generator (``docs/architecture/testing.md`` §2): builds the demo world
"Aetheria" in a new vault, for manual testing, e2e, performance work and the golden fixture
vaults (``persistence-and-migrations.md`` §3.5).

    uv run scripts/make_sample_vault.py --size small --out ../data
    uv run scripts/make_sample_vault.py --size tiny --fixture tests/fixtures/vaults/v0.1.0

Every write goes through the services (one transaction = one changeset, so history, search,
mentions and every other invariant hold), never raw SQL. The world is deterministic for a seed:
the same entities, texts, tags and links in the same order (ids and real-world timestamps
differ, they are generated).

The world has two parts:

- **The core** (every size): a fixed, hand-written set covering every feature the app has, with
  stable names that tests rely on. ``tiny`` is only the core. Time (M3): four dimensions (Aetheria
  lasts 10^110 seconds); a calendar from every preset plus the custom Imperial Reckoning, which
  uses every calendar feature and is anchored to events; events typed in every calendar, at every
  precision, with every end kind; a chain of relative anchors; recurring events of every rule
  type, with referenced, modified and cancelled occurrences, a sub-event of an occurrence and an
  anchor to an occurrence; sub-events and causes.
- **The bulk** (``small`` and up): seeded random events, links, tags and aliases in the volumes
  of ``SIZES``, for realistic lists, search and performance. Their starts are absolute moments,
  dates in three calendars at random precisions, or relative to a recent event; their ends every
  kind; every 100th event recurs, some with a materialized occurrence.

**Extending it (every milestone).** When a milestone adds a feature that stores data, add it to
the core in ``_build_core`` (a new ``_core_<feature>`` step, a few entities with stable names)
and, where volume matters, to the bulk. Add what tests should check to ``SampleWorld`` (it is
written to ``expected.json`` for fixtures). Planned: branches and worldlines (M7, M9), facts and
characters, places and other module kinds (M6, M7), correspondences (M9), media (M10), custom
fields and kinds (M11). Old fixtures are never regenerated: the next milestone release commits a
new one (``persistence-and-migrations.md`` §3.5).
"""

import argparse
import json
import random
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, get_args

from sqlalchemy.orm import Session

from lore import __version__
from lore.chronology.calendar import CompiledCalendar, to_fields
from lore.config import detect_spec_dir
from lore.core.entities.models import Entity
from lore.core.entities.schemas import EntityCreate, EntityUpdate
from lore.core.entities.service import EntityService
from lore.core.history.recorder import context as history_context
from lore.core.history.service import HistoryService
from lore.core.links.schemas import GraphStyleIn, LinkCreate, LinkTypeCreate, LinkTypeUpdate
from lore.core.links.service import LinkService
from lore.core.links.types_service import LinkTypeService
from lore.core.models import load_metadata as load_core_metadata
from lore.core.modules import ModuleRegistry, ModuleSpec
from lore.core.modules.spec import VaultContext
from lore.core.time.calendars import (
    CalendarSource,
    PresetChoice,
    compiled_calendar,
    source_definition,
)
from lore.core.time.events import home_row
from lore.core.time.resolve import Resolver
from lore.core.time.series import RuleProblem, compute_occurrence
from lore.core.vaults import OpenVault, VaultManager
from lore.core.vaults.format import DATABASE_NAME, MANIFEST_NAME
from lore.modules import ALL_MODULES

type Size = Literal["tiny", "small", "medium", "large"]
type Doc = dict[str, Any]

DEFAULT_SEED = 1729
WORLD_NAME = "Aetheria"
MIRROR_EARTH = "Mirror Earth"
ORIGIN = "cli"


@dataclass(frozen=True)
class Scale:
    events: int  # bulk events (on top of the core)
    links: int  # bulk links between them


SIZES: dict[Size, Scale] = {
    "tiny": Scale(events=0, links=0),
    "small": Scale(events=1_000, links=3_000),
    "medium": Scale(events=10_000, links=40_000),
    "large": Scale(events=100_000, links=500_000),
}
ENTITIES_PER_TRANSACTION = 500
LINKS_PER_TRANSACTION = 2_000


@dataclass
class SampleWorld:
    """What was built: the vault and the facts tests check (``expected.json`` of a fixture)."""

    vault_id: str
    folder: str
    size: Size
    seed: int
    app_version: str = __version__
    # Entities not in the trash, by kind; trashed entities; links not in the trash.
    entities: dict[str, int] = field(default_factory=dict)
    trashed_entities: int = 0
    links: int = 0
    custom_link_types: list[str] = field(default_factory=list)
    # Calendar name -> its preset id, or "custom".
    calendars: dict[str, str] = field(default_factory=dict)
    # Core event name -> [start_t, end_t] (resolved moments, decimal strings).
    moments: dict[str, list[str]] = field(default_factory=dict)
    # Core series name -> {occurrence key: state} of its materialized occurrences.
    occurrences: dict[str, dict[str, str]] = field(default_factory=dict)
    # Names of entities readers must never see (private, or effectively private).
    reader_hidden: list[str] = field(default_factory=list)
    # A word in an entity's text and the entity the search finds.
    search: dict[str, str] = field(default_factory=dict)
    # Entity name -> the names of the entities mentioning or linking to it.
    backlinks: dict[str, list[str]] = field(default_factory=dict)


# --- rich text -----------------------------------------------------------------------------------


def doc(*blocks: Doc) -> Doc:
    return {"type": "doc", "content": list(blocks)}


def p(*content: Doc | str) -> Doc:
    return {"type": "paragraph", "content": [text(c) if isinstance(c, str) else c for c in content]}


def heading(value: str, level: int = 2) -> Doc:
    return {"type": "heading", "attrs": {"level": level}, "content": [text(value)]}


def text(value: str, *marks: Doc) -> Doc:
    node: Doc = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def mention(label: str, entity_id: str) -> Doc:
    return text(label, {"type": "entityLink", "attrs": {"entityId": entity_id}})


def bold(value: str) -> Doc:
    return text(value, {"type": "bold"})


def hidden(level: Literal["spoiler", "private"], *blocks: Doc) -> Doc:
    return {"type": "visibilityBlock", "attrs": {"level": level}, "content": list(blocks)}


def callout(tone: str, *blocks: Doc) -> Doc:
    return {"type": "callout", "attrs": {"tone": tone}, "content": list(blocks)}


def bullets(*items: Doc) -> Doc:
    return {"type": "bulletList", "content": [{"type": "listItem", "content": [i]} for i in items]}


# --- time ----------------------------------------------------------------------------------------


def preset_definition(preset_id: str, origin: int = 0) -> dict[str, Any]:
    """A preset instantiated for a dimension in seconds, its alignment unit starting at
    ``origin``."""
    choice = PresetChoice(id=preset_id, origin=str(origin))
    return source_definition(CalendarSource(preset=choice), detect_spec_dir())


def time_spec(duration: int) -> dict[str, Any]:
    """A dimension's ``ext``: seconds, lasting ``duration``."""
    unit = {"singular": "second", "plural": "seconds", "abbr": "s"}
    return {"base_unit": unit, "duration": str(duration)}


def point(t: int, precision: str = "base", *, approximate: bool = False) -> Doc:
    """A time point at an absolute moment."""
    anchor = {"kind": "absolute", "t": str(t)}
    return {"anchor": anchor, "precision": precision, "approximate": approximate}


def date(
    calendar_id: str,
    fields: dict[str, str],
    precision: str,
    *,
    era: str | None = None,
    regime: str | None = None,
    approximate: bool = False,
) -> Doc:
    """A time point typed as a date of a calendar (``fields`` from the top level down to
    ``precision``; named units by slot id)."""
    anchor: Doc = {"kind": "calendar", "calendar_id": calendar_id, "fields": fields}
    if era is not None:
        anchor["era"] = era
    if regime is not None:
        anchor["regime"] = regime
    return {"anchor": anchor, "precision": precision, "approximate": approximate}


def local(fields: dict[str, str], precision: str, regime: str | None = None) -> Doc:
    """A date of the calendar being defined (definitions only, ``chronology-engine.md`` §3.10)."""
    anchor: Doc = {"kind": "local", "fields": fields}
    if regime is not None:
        anchor["regime"] = regime
    return {"anchor": anchor, "precision": precision}


def base(units: int) -> Doc:
    """A duration in base units (signed)."""
    return {"kind": "base", "units": str(units)}


def calendar_span(calendar_id: str, sign: int = 1, **amounts: int) -> Doc:
    """A duration in units of a calendar, e.g. ``calendar_span(c, month=3, day=2)``."""
    counts = {level: str(amount) for level, amount in amounts.items()}
    return {"kind": "calendar", "calendar_id": calendar_id, "amounts": counts, "sign": sign}


def after(
    event_id: str,
    offset: Doc | None = None,
    *,
    slot: Literal["start", "end"] = "start",
    occurrence: str | None = None,
    precision: str = "base",
    approximate: bool = False,
) -> Doc:
    """A time point relative to a slot of an event (or of one of its occurrences)."""
    ref: Doc = {"type": "event", "id": event_id, "slot": slot}
    if occurrence is not None:
        ref["occurrence"] = occurrence
    anchor = {"kind": "relative", "ref": ref, "offset": offset or base(0)}
    return {"anchor": anchor, "precision": precision, "approximate": approximate}


def at(t: int, **ext: Any) -> Doc:
    """An event's ``ext`` starting at an absolute moment."""
    return {"start": point(t), **ext}


def lasting(units: int) -> Doc:
    """An end spec: a base duration."""
    return {"kind": "duration", "duration": base(units)}


def lasting_for(duration: Doc) -> Doc:
    """An end spec: any duration."""
    return {"kind": "duration", "duration": duration}


def ending(time_point: Doc) -> Doc:
    """An end spec: an explicit end."""
    return {"kind": "time_point", "time_point": time_point}


INSTANT: Doc = {"kind": "instant"}
END_OF_TIME: Doc = {"kind": "end_of_time"}
UNKNOWN_END: Doc = {"kind": "unknown"}
NEVER: Doc = {"kind": "never"}


def count(n: int) -> Doc:
    """A recurrence limit: ``n`` generated occurrences."""
    return {"kind": "count", "count": str(n)}


def until(time_point: Doc) -> Doc:
    """A recurrence limit: occurrences starting at or before ``time_point``."""
    return {"kind": "until", "until": time_point}


def date_fields(calendar: CompiledCalendar, t: int, precision: str) -> dict[str, str]:
    """The fields of the ``precision`` unit containing ``t`` (astronomical year; named units by
    slot id), as a calendar anchor types them."""
    fields: dict[str, str] = {}
    for level, value in to_fields(calendar, t).levels.items():
        fields[level] = value.slot_id or str(value.n)
        if level == precision:
            break
    return fields


DAY = 86_400
YEAR = 365 * DAY
MIRROR_AD_1 = 4_000 * YEAR  # 1 January AD 1 on Mirror Earth: BC dates down to about 4000 BC


def time_ref(t: int) -> Doc:
    """An inline reference to an absolute moment (calendars render it from M3 on)."""
    return {"type": "timeRef", "attrs": {"timePoint": point(t)}}


def _quarter(i: int) -> Doc:
    """``i / 4`` as a normalized rational."""
    share = Fraction(i, 4)
    return {"num": str(share.numerator), "den": str(share.denominator)}


def _level(
    id_: str, label: str, plural: str, abbr: str, *, start: int | None, template: str | None
) -> Doc:
    level: Doc = {"id": id_, "label": label, "plural": plural, "abbr": abbr}
    if start is not None:
        level["numbering_start"] = start
    if template is not None:
        level["default_template"] = template
    return level


def _uniform(level: str, n: int) -> Doc:
    return {"level": level, "uniform": {"count": str(n)}}


def _month(id_: str, name: str, template: str = "m30", **more: Any) -> Doc:
    return {"id": id_, "template": template, "name": name, "abbr": name[:3], **more}


_WEEK = {
    "id": "week", "level": "day", "length": 7,
    "names": ["Moonday", "Tideday", "Emberday", "Stoneday", "Windday", "Starday", "Restday"],
    "abbrs": ["Mo", "Ti", "Em", "St", "Wi", "Sa", "Re"],
    "ids": ["moonday", "tideday", "emberday", "stoneday", "windday", "starday", "restday"],
}  # fmt: skip


def imperial_reckoning(tide_count: str, founding: str, reform: str) -> Doc:
    """The custom calendar using every calendar feature (``chronology-engine.md`` §3): levels
    with numbering starts and default templates; two regimes (the Old Reckoning and the Imperial
    reform, which starts at an event); uniform and sequence templates with named, run and
    intercalary children excluded from the week; cycle and rules top patterns with an exception
    year; alignments to another calendar's date and to an event; a continuous week continued
    across the reform and a ten-day count reset every month; backward, forward and prefix eras
    (one starting at an event, one at a local date); two overlays; formats with an intercalary
    override; display options."""
    shared = {
        "second": _uniform("second", 1),
        "minute": _uniform("minute", 60),
        "hour": _uniform("hour", 60),
        "day": _uniform("day", 24),
        "m30": _uniform("month", 30),
        "m31": _uniform("month", 31),
        "d1": _uniform("month", 1),
        "d2": _uniform("month", 2),
    }
    midwinter = {"intercalary": True, "cycle_excluded": ["week"]}
    old = {
        "id": "old",
        "name": "Old Reckoning",
        "templates": {
            **shared,
            "year_odd": {
                "level": "year",
                "sequence": [
                    _month("frostfall", "Frostfall"),
                    _month("thawing", "Thawing", "m31"),
                    _month("midwinter", "Midwinter Night", "d1", **midwinter),
                    _month("bloom", "Bloom"),
                ],
            },
            "year_even": {
                "level": "year",
                "sequence": [
                    _month("ember", "Ember", "m31"),
                    _month("ash", "Ash"),
                    _month("cinder", "Cinder", "m31"),
                ],
            },
        },
        "top": {"pattern": {"kind": "cycle", "templates": ["year_odd", "year_even"], "start": "1"}},
        "alignment": {
            "fields": {"year": "1", "month": "frostfall", "day": "1"},
            "at": date(tide_count, {"year": "1", "month": "1", "day": "1"}, "day"),
        },
        "cycles": [
            {
                **_WEEK,
                "anchor": {"fields": {"year": "1", "month": "frostfall", "day": "1"}, "index": 0},
            }
        ],
    }
    year = [
        _month("frostfall", "Frostfall"),
        {"run": {"count": "2"}},
        _month("midyear", "Midyear's Day", "d1", intercalary=True, cycle_excluded=["week"]),
        {"run": {"count": "2", "template": "m31"}},
        _month("bloom", "Bloom"),
    ]
    imperial = {
        "id": "imperial",
        "name": "Imperial Reckoning",
        "starts_at": after(reform),
        "templates": {
            **shared,
            "year_common": {"level": "year", "sequence": year},
            "year_leap": {
                "level": "year",
                "sequence": [
                    *year[:3],
                    _month("leapday", "Leap Day", "d1", intercalary=True),
                    *year[3:],
                ],
            },
            "year_jubilee": {
                "level": "year",
                "sequence": [
                    _month("frostfall", "Frostfall"),
                    _month("jubilee", "Jubilee Days", "d2", intercalary=True),
                    _month("bloom", "Bloom"),
                ],
            },
        },
        "top": {
            "pattern": {
                "kind": "rules",
                "default": "year_common",
                "rules": [
                    {
                        "when": {
                            "all": [{"mod": "4", "eq": "0"}, {"not": {"mod": "100", "eq": "0"}}]
                        },
                        "template": "year_leap",
                    }
                ],
            },
            "exceptions": [{"year": "1000", "template": "year_jubilee"}],
        },
        "alignment": {
            "fields": {"year": "400", "month": "frostfall", "day": "1"},
            "at": after(reform),
        },
        "cycles": [
            {**_WEEK, "continue_from_previous_regime": True},
            {"id": "tenday", "level": "day", "length": 10, "mode": {"reset": "month"}},
        ],
    }
    phases = ["New", "Waxing", "Full", "Waning"]
    seasons = ["Thaw", "Bloom", "Ember", "Frost"]
    return {
        "schema_version": 1,
        "levels": [
            _level("second", "second", "seconds", "s", start=0, template="second"),
            _level("minute", "minute", "minutes", "min", start=0, template="minute"),
            _level("hour", "hour", "hours", "h", start=0, template="hour"),
            _level("day", "day", "days", "d", start=1, template="day"),
            _level("month", "month", "months", "mo", start=1, template="m30"),
            _level("year", "year", "years", "y", start=None, template=None),
        ],
        "regimes": [old, imperial],
        "eras": [
            {
                "id": "bf",
                "name": "Before the Founding",
                "abbr": "BF",
                "numbering": {"direction": "backward", "first": "1"},
            },
            {
                "id": "af",
                "name": "After the Founding",
                "abbr": "AF",
                "start": after(founding),
                "numbering": {"direction": "forward", "first": "1"},
            },
            {
                "id": "ir",
                "name": "Imperial Restoration",
                "abbr": "IR",
                "start": local({"year": "800", "month": "frostfall", "day": "1"}, "day"),
                "numbering": {"direction": "forward", "first": "1"},
                "abbr_position": "prefix",
            },
        ],
        "overlays": [
            {
                "id": "moon",
                "name": "The Pale Moon",
                "period": {"num": "2551443", "den": "1"},
                "epoch": point(0),
                "phases": [
                    {"name": f"{name} Moon", "from": _quarter(i)} for i, name in enumerate(phases)
                ],
            },
            {
                "id": "seasons",
                "name": "Seasons",
                "period": {"num": "7889400", "den": "1"},
                "epoch": local({"year": "1", "month": "thawing", "day": "1"}, "day", regime="old"),
                "phases": [{"name": name, "from": _quarter(i)} for i, name in enumerate(seasons)],
            },
        ],
        "formats": {
            "year": "{era_year} {era}",
            "month": "{month.name} {era_year} {era}",
            "day": "{cycle.week}, {day:ordinal} of {month.name} {era_year} {era}",
            "minute": "{day} {month.abbr} {era_year} {era}, {hour:pad2}:{minute:pad2}",
            "intercalary": {"day": "{month.name} {era_year} {era} ({overlay.moon})"},
        },
        "display": {
            "circa": "c. ",
            "digit_group": " ",
            "scientific_threshold": 20,
            "significant_digits": 5,
            "range_separator": " to ",
        },
    }


# --- writing through the services ---------------------------------------------------------------


@dataclass
class Services:
    """The services of one write transaction."""

    session: Session
    context: VaultContext
    entities: EntityService
    links: LinkService
    link_types: LinkTypeService
    history: HistoryService

    def entity(self, kind: str, name: str, **body: Any) -> str:
        created = self.entities.create(
            EntityCreate.model_validate({"kind": kind, "name": name, **body})
        )
        return created.entity.id

    def prime_timeline(self, dimension_id: str, name: str) -> str:
        """The id of the dimension's prime timeline, renamed to ``name``."""
        ext = self.entities.get(dimension_id).ext or {}
        prime = self.entities.get(str(ext["prime_timeline_id"]))
        if prime.name != name:
            self.entities.update(prime.id, EntityUpdate(revision=prime.revision, name=name))
        return prime.id

    def calendar(self, calendar_id: str) -> CompiledCalendar:
        return compiled_calendar(self.context, calendar_id)

    def update(self, entity_id: str, **changes: Any) -> None:
        entity = self.entities.get(entity_id)
        data = {"revision": entity.revision, **changes}
        self.entities.update(entity_id, EntityUpdate.model_validate(data))

    def link(self, link_type: str, source: str, target: str, **body: Any) -> str:
        data = {"link_type": link_type, "source_id": source, "target_id": target, **body}
        return self.links.create(LinkCreate.model_validate(data)).link.id


class Writer:
    def __init__(self, vault: OpenVault, registry: ModuleRegistry) -> None:
        self.vault = vault
        self.registry = registry
        self.last_changeset: str | None = None

    @contextmanager
    def transaction(self, summary: str) -> Iterator[Services]:
        """One write transaction, recorded as one changeset with this summary."""
        with self.vault.write_sessions.begin() as session:
            history = history_context(session)
            history.origin = ORIGIN
            history.summary = summary
            context = VaultContext(self.vault, session, self.registry)
            yield Services(
                session,
                context,
                EntityService(context),
                LinkService(session, self.registry),
                LinkTypeService(session, self.registry),
                HistoryService(session, self.registry, self.vault),
            )
        self.last_changeset = history.changeset_id


# --- the core ------------------------------------------------------------------------------------


@dataclass
class Core:
    ids: dict[str, str] = field(default_factory=dict)  # name -> entity id

    def __getitem__(self, name: str) -> str:
        return self.ids[name]


def _core_dimensions(writer: Writer, core: Core, world: SampleWorld) -> None:
    with writer.transaction("Sample world: dimensions, timelines and calendars") as s:
        aetheria = s.entity(
            "dimension",
            WORLD_NAME,
            ext=time_spec(10**110),  # the worked example of time-model.md §13
            summary="A world of floating isles, broken from a single continent in the Sundering.",
            aliases=[
                {"alias": "The Shattered Realm", "alias_kind": "title"},
                {"alias": "Aithéria", "alias_kind": "translation"},
            ],
            tags=["Realm", "Canon"],
        )
        dreaming = s.entity(
            "dimension",
            "The Dreaming",
            ext=time_spec(10**100),
            summary="Where the drowned and the unborn walk. Its nature is a late reveal.",
            visibility="spoiler",
            tags=["Realm"],
        )
        hollow = s.entity(
            "dimension",
            "The Hollow",
            ext=time_spec(10**100),
            summary="The author's scratch realm: never shown to readers.",
            visibility="private",
        )
        mirror = s.entity(
            "dimension",
            MIRROR_EARTH,
            ext=time_spec(10**12),  # about 31,700 years
            summary="A world much like ours, glimpsed in the Spire's mirrors.",
            tags=["Realm"],
        )
        core.ids.update({WORLD_NAME: aetheria, "The Dreaming": dreaming, "The Hollow": hollow,
                         MIRROR_EARTH: mirror})  # fmt: skip
        # Every dimension comes with its prime timeline; they get their own names. Branches
        # ("The Unbroken Crown") arrive with the branches module (M9).
        for name, dimension in (
            ("Prime", aetheria),
            ("Dream-time", dreaming),
            ("Hollow Draft", hollow),
            ("Mirror Line", mirror),
        ):
            core.ids[name] = s.prime_timeline(dimension, name)
        # A calendar from every preset (the first of a dimension becomes its default). The
        # custom Imperial Reckoning, using every calendar feature, is anchored to events
        # (``_core_imperial_reckoning``).
        for name, dimension, preset, origin in (
            ("Spire Reckoning", aetheria, "alternating-years", 0),
            ("Tide Count", aetheria, "simple-360", 0),
            ("Moon Count", aetheria, "lunisolar-metonic", 50 * YEAR),
            ("Dream Count", dreaming, "simple-360", 0),  # events need a calendar (R-DIM-5)
            ("Deep Count", dreaming, "mayan", 0),
            ("Hearth Reckoning", dreaming, "shire-reckoning", 1000 * YEAR),
            ("Draft Calendar", hollow, "simple-360", 0),
            ("Common Era", mirror, "gregorian", MIRROR_AD_1),
            ("Old Style", mirror, "julian-gregorian", MIRROR_AD_1),
            ("Julian Count", mirror, "julian", MIRROR_AD_1),
        ):
            core.ids[name] = s.entity(
                "calendar",
                name,
                dimension_id=dimension,
                ext={"definition": preset_definition(preset, origin)},
            )
            world.calendars[name] = preset
    world.reader_hidden += ["The Hollow", "Hollow Draft"]


def _core_link_types(writer: Writer, world: SampleWorld) -> None:
    with writer.transaction("Sample world: custom link types") as s:
        foreshadows = s.link_types.create(
            LinkTypeCreate(
                label="foreshadows",
                inverse_label="foreshadowed by",
                description="An omen and the event it points to.",
                source_kinds=["event"],
                target_kinds=["event"],
                temporal="never",
                unique="per_pair",
                graph=GraphStyleIn(color="#a855f7", dashed=True, weight=2),
            )
        )
        allied = s.link_types.create(
            LinkTypeCreate(
                label="allied with",
                symmetric=True,
                description="An alliance between two parties, optionally under a treaty.",
                data_schema={
                    "type": "object",
                    "properties": {"treaty": {"type": "string", "maxLength": 200}},
                    "additionalProperties": False,
                },
            )
        )
        mirrors = s.link_types.create(LinkTypeCreate(label="mirrors", inverse_label="mirrored by"))
        assert mirrors.revision is not None
        s.link_types.update(mirrors.key, LinkTypeUpdate(revision=mirrors.revision, archived=True))
    world.custom_link_types = sorted([foreshadows.key, allied.key, mirrors.key])


def _core_events(writer: Writer, core: Core, world: SampleWorld) -> None:
    home = {"dimension_id": core[WORLD_NAME]}
    with writer.transaction("Sample world: the Age of Embers") as s:
        age = s.entity(
            "event",
            "Age of Embers",
            summary="The first age, from the lighting of the Spire to the Sundering.",
            tags=["Era", "Canon"],
            ext=at(0, end={"kind": "time_point", "time_point": point(1_000_000)}, importance=5),
            **home,
        )
        core.ids["Age of Embers"] = age
        # Private first: the public text below mentions it inside a private block.
        core.ids["The Whispering Accord"] = s.entity(
            "event",
            "The Whispering Accord",
            summary="The secret pact that caused the Sundering. The big twist.",
            visibility="private",
            ext=at(900_000),
            parent_id=age,
            **home,
        )
        core.ids["The Long Night"] = s.entity(
            "event",
            "The Long Night",
            summary="Forty days without a sunrise after the Sundering.",
            visibility="spoiler",
            ext=at(1_000_000, end=lasting(40 * DAY)),
            parent_id=age,
            **home,
        )
        core.ids["The Sundering"] = s.entity(
            "event",
            "The Sundering",
            summary="The continent breaks into the floating isles.",
            aliases=[
                {"alias": "The Breaking"},
                {"alias": "Shatterfall", "alias_kind": "nickname"},
                {"alias": "The Accord's Price", "visibility": "private"},
            ],
            tags=["Cataclysm", "Canon"],
            parent_id=age,
            ext=at(1_000_000, importance=5, category="cataclysm"),
            body=doc(
                heading("What happened"),
                p(
                    "At ",
                    time_ref(1_000_000),
                    " the bedrock of ",
                    mention(WORLD_NAME, home["dimension_id"]),
                    " split along the old ley lines.",
                ),
                bullets(p("Seven isles rose."), p("The Spire stood.")),
                hidden(
                    "spoiler",
                    p("It ushered in ", mention("the Long Night", core["The Long Night"]), "."),
                ),
                hidden(
                    "private",
                    p("Caused by ", mention("the Accord", core["The Whispering Accord"]), "."),
                ),
                callout("note", p(bold("Note: "), "dates follow the Spire Reckoning.")),
            ),
            **home,
        )
        core.ids["Founding of Varn"] = s.entity(
            "event",
            "Founding of Varn",
            summary="The first city on the largest isle.",
            tags=["Canon"],
            ext=at(500_000),
            parent_id=age,
            body=doc(
                p("Founded by survivors of ", mention("the Sundering", core["The Sundering"]), ".")
            ),
            **home,
        )
    with writer.transaction("Sample world: later events") as s:
        core.ids["Coronation of Ilsa"] = s.entity(
            "event",
            "Coronation of Ilsa",
            summary="Ilsa is crowned in Varn.",
            ext={
                "start": {
                    "anchor": {
                        "kind": "relative",
                        "ref": {"type": "event", "id": core["The Sundering"], "slot": "start"},
                        "offset": {"kind": "base", "units": str(100 * DAY)},
                    },
                    "precision": "base",
                },
                "end": lasting(DAY),
            },
            body=doc(
                p(
                    "Held in ",
                    mention("Varn", core["Founding of Varn"]),
                    " on the anniversary of its founding.",
                )
            ),
            **home,
        )
        core.ids["Rite of Tides"] = s.entity(
            "event",
            "Rite of Tides",
            summary="A festival held every spring tide (recurring from M3 on).",
            tags=["Festival"],
            ext=at(2_000_000, category="festival"),
            **home,
        )
        core.ids["Dream of the Drowned King"] = s.entity(
            "event",
            "Dream of the Drowned King",
            summary="A vision shared by every sleeper in Varn on one night.",
            ext=at(1_200_000),
            dimension_id=core["The Dreaming"],
        )
        core.ids["First Draft of the Fall"] = s.entity(
            "event",
            "First Draft of the Fall",
            summary="An abandoned idea.",
            ext=at(0),
            dimension_id=core["The Hollow"],
        )
        core.ids["Burned Archive"] = s.entity(
            "event", "Burned Archive", summary="Cut from the canon.", ext=at(3_000_000), **home
        )
    world.reader_hidden += ["The Whispering Accord", "First Draft of the Fall"]
    world.search = {"query": "ley lines", "name": "The Sundering"}


def _core_imperial_reckoning(writer: Writer, core: Core, world: SampleWorld) -> None:
    """The custom calendar, anchored to two events typed in the Spire Reckoning."""
    spire, home = core["Spire Reckoning"], {"dimension_id": core[WORLD_NAME]}
    with writer.transaction("Sample world: the Founding and the Reform") as s:
        core.ids["Founding of the Empire"] = s.entity(
            "event",
            "Founding of the Empire",
            summary="The isles swear fealty to one crown. The Imperial years count from it.",
            tags=["Canon"],
            ext={
                "start": date(
                    spire, {"year": "121", "month": "thawing", "day": "12", "hour": "14"}, "hour"
                ),
                "importance": 5,
            },
            **home,
        )
        core.ids["The Imperial Reform"] = s.entity(
            "event",
            "The Imperial Reform",
            summary="The Old Reckoning gives way to the Imperial Reckoning's long years.",
            ext={"start": date(spire, {"year": "401", "month": "frostfall", "day": "1"}, "day")},
            **home,
        )
    with writer.transaction("Sample world: the Imperial Reckoning") as s:
        definition = imperial_reckoning(
            core["Tide Count"], core["Founding of the Empire"], core["The Imperial Reform"]
        )
        core.ids["Imperial Reckoning"] = s.entity(
            "calendar", "Imperial Reckoning", ext={"definition": definition}, **home
        )
    world.calendars["Imperial Reckoning"] = "custom"


def _core_dates(writer: Writer, core: Core) -> None:
    """Events typed in every calendar, at every precision, with every end kind."""
    imperial, home = core["Imperial Reckoning"], {"dimension_id": core[WORLD_NAME]}

    def entity(s: Services, name: str, summary: str, **body: Any) -> None:
        body.setdefault("dimension_id", home["dimension_id"])
        core.ids[name] = s.entity("event", name, summary=summary, **body)

    with writer.transaction("Sample world: dates in every calendar") as s:
        entity(s, "Coronation of Aurel", "Aurel the Younger takes the Spire Throne.", ext={
            "start": date(imperial, {"year": "412", "month": "frostfall", "day": "3",
                                     "hour": "10", "minute": "30"}, "minute"),
            "end": lasting_for(calendar_span(imperial, hour=3)), "importance": 4,
        })  # fmt: skip
        entity(s, "The Midyear Fire", "Varn burns on the one day outside the months.", ext={
            "start": date(imperial, {"year": "430", "month": "midyear", "day": "1"}, "day"),
            "end": ending(date(imperial, {"year": "430", "month": "4"}, "month")),
            "category": "cataclysm",
        })  # fmt: skip
        entity(s, "Raising of the Seawall", "Nobody agrees on the year.", ext={
            "start": date(imperial, {"year": "45"}, "year", era="af", approximate=True),
            "end": UNKNOWN_END,
        })  # fmt: skip
        entity(s, "Last Frost of the Old Reckoning", "Dated in the old regime on purpose.", ext={
            "start": date(imperial, {"year": "389", "month": "midwinter", "day": "1"}, "day",
                          regime="old"),
        })  # fmt: skip
        entity(s, "Embassy of the Restoration", "Envoys from the far isles.", ext={
            "start": date(imperial, {"year": "3", "month": "bloom"}, "month", era="ir"),
            "end": lasting_for(calendar_span(imperial, month=1)),
        })  # fmt: skip
        entity(s, "The Endless Vigil", "The watch on the Spire that never ends.", ext={
            "start": date(imperial, {"year": "500", "month": "2", "day": "7", "hour": "6",
                                     "minute": "0", "second": "15"}, "second"),
            "end": END_OF_TIME,
        })  # fmt: skip
        entity(s, "Jubilee of the Thousandth Year", "Two days that belong to no month.", ext={
            "start": date(imperial, {"year": "1000", "month": "jubilee", "day": "2"}, "day"),
        })  # fmt: skip
        entity(s, "Feast of the First Moon", "Counted in moons, not months.", ext={
            "start": date(core["Moon Count"], {"year": "3", "month": "m1", "day": "5"}, "day"),
        })  # fmt: skip
        entity(s, "The Long Count Turns", "A great cycle of the Deep Count ends.",
               dimension_id=core["The Dreaming"], ext={
            "start": date(core["Deep Count"], {"baktun": "13", "katun": "0", "tun": "0",
                                               "winal": "0", "kin": "0"}, "kin"),
        })  # fmt: skip
        entity(s, "Midsummer in the Hearth", "The dreamers' Midyear feast.",
               dimension_id=core["The Dreaming"], ext={
            "start": date(core["Hearth Reckoning"], {"year": "12", "month": "midyear"}, "month"),
        })  # fmt: skip
        mirror = {"dimension_id": core[MIRROR_EARTH]}
        entity(s, "Mirror Moon Landing", "Seen in the Spire's mirrors.", **mirror, ext={
            "start": date(core["Common Era"], {"year": "1969", "month": "jul", "day": "20",
                                               "hour": "20", "minute": "17"}, "minute", era="ad"),
        })  # fmt: skip
        entity(s, "Mirror Battle of Actium", "A sea battle before the mirror's year one.",
               **mirror, ext={
            "start": date(core["Julian Count"], {"year": "31", "month": "sep", "day": "2"},
                          "day", era="bc"),
        })  # fmt: skip
        entity(s, "Mirror Calendar Reform", "Ten days vanish from the mirror's calendar.",
               **mirror, ext={
            "start": date(core["Old Style"], {"year": "1582", "month": "oct", "day": "15"},
                          "day", era="ad", regime="gregorian"),
        })  # fmt: skip
        entity(s, "Mirror Fall of Rome", "The last western emperor is deposed.", **mirror, ext={
            "start": date(core["Old Style"], {"year": "476", "month": "sep", "day": "4"}, "day",
                          era="ad", regime="julian"),
        })  # fmt: skip


def _core_chain(writer: Writer, core: Core) -> None:
    """A chain of relative anchors (``time-model.md`` §7): moving the Assassination moves
    everything after it. Causes, an omen before it and sub-events."""
    imperial, home = core["Imperial Reckoning"], {"dimension_id": core[WORLD_NAME]}
    with writer.transaction("Sample world: the Succession War") as s:

        def entity(name: str, summary: str, **ext: Any) -> str:
            core.ids[name] = s.entity("event", name, summary=summary, ext=ext, **home)
            return core.ids[name]

        killed = entity(
            "Assassination of Aurel", "Aurel dies at a feast.",
            start=date(imperial, {"year": "431", "month": "2", "day": "14", "hour": "22"},
                       "hour"),
            end=lasting(2 * 3600), importance=5,
        )  # fmt: skip
        funeral = entity(
            "Funeral of Aurel", "Three days after the Assassination.",
            start=after(killed, calendar_span(imperial, day=3), slot="end", precision="day"),
            end=lasting_for(calendar_span(imperial, day=1)),
        )  # fmt: skip
        mourning = entity(
            "The Mourning Ends", "Forty days after the funeral.",
            start=after(funeral, base(40 * DAY)),
        )  # fmt: skip
        war = entity(
            "War of the Succession", "Three claimants, seven years.",
            start=after(mourning, slot="end"),
            end=lasting_for(calendar_span(imperial, year=7, month=2)), importance=4,
            category="war",
        )  # fmt: skip
        entity(
            "Peace of Varn", "The war ends with a treaty signed in Varn.",
            start=after(war, slot="end"),
            end=ending(after(war, calendar_span(imperial, year=1), slot="end")),
        )  # fmt: skip
        omen = entity(
            "Omen of Ash", "Ash fell on Varn the day before.",
            start=after(killed, base(-DAY), approximate=True),
        )  # fmt: skip
        core.ids["Siege of Thornwall"] = s.entity(
            "event", "Siege of Thornwall", summary="The war's longest siege.", parent_id=war,
            ext={"start": after(war, calendar_span(imperial, year=2)),
                 "end": lasting_for(calendar_span(imperial, month=3))}, **home,
        )  # fmt: skip
        s.link("core.causes", killed, war, data={"description": "No heir was named."})
        s.link("core.causes", war, core["Peace of Varn"])
        s.link("custom.foreshadows", omen, killed)
        s.link("core.participant", war, core["Founding of Varn"], role="battleground")


def _rule(calendar_id: str, freq: Doc, limit: Doc = NEVER, **more: Any) -> Doc:
    return {"kind": "calendar", "calendar_id": calendar_id, "freq": freq, "limit": limit, **more}


def _core_series(writer: Writer, core: Core, world: SampleWorld) -> None:
    """Recurring events of every rule type (``recurrence.md`` §2), and materialized
    occurrences: referenced (with a sub-event), modified and cancelled."""
    spire, imperial = core["Spire Reckoning"], core["Imperial Reckoning"]
    home = {"dimension_id": core[WORLD_NAME]}
    year, month, day = {"level": "year"}, {"level": "month"}, {"level": "day"}
    with writer.transaction("Sample world: recurring events") as s:

        def series(
            name: str, summary: str, start: Doc, rule: Doc, dimension: str = WORLD_NAME, **more: Any
        ) -> str:
            ext = {"start": start, "recurrence": rule, "category": "festival", **more}
            core.ids[name] = s.entity("event", name, summary=summary, ext=ext, tags=["Festival"],
                                      dimension_id=core[dimension])  # fmt: skip
            return core.ids[name]

        s.update(core["Rite of Tides"], ext={
            "recurrence": _rule(spire, year, missing="constrain"), "end": lasting(DAY),
        })  # fmt: skip
        series(
            "Council of the Seventh Year", "The isles' lords meet every seventh year.",
            date(imperial, {"year": "401", "month": "frostfall", "day": "1", "hour": "9"},
                 "hour"),
            _rule(imperial, year, count(50), interval="7", time={"fields": {"hour": "9",
                  "minute": "0"}}, select={"path": [{"level": "month", "values": ["frostfall"]},
                                                     {"level": "day", "values": ["1"]}]}),
            end=lasting_for(calendar_span(imperial, day=3)),
        )  # fmt: skip
        series(
            "Moonday Market", "Twice a week until the war ends; closed in mourning.",
            date(imperial, {"year": "402", "month": "frostfall", "day": "1"}, "day"),
            _rule(imperial, {"cycle": "week"},
                  until(after(core["War of the Succession"], slot="end")),
                  select={"path": [{"level": "day", "values": ["moonday", "starday"]}]},
                  exclusions=[{"from": after(core["Assassination of Aurel"]),
                               "to": after(core["The Mourning Ends"]),
                               "note": "Markets closed in mourning"}]),
            end=lasting(8 * 3600),
        )  # fmt: skip
        series(
            "Lantern Night", "The last night of every odd year, but not in the Dark Years.",
            date(spire, {"year": "3", "month": "bloom", "day": "30"}, "day"),
            _rule(spire, year, filters=[{"mod": "2", "eq": "1"}, {"not": {"in": ["999"]}}],
                  select={"path": [{"level": "month", "values": ["-1"]},
                                   {"level": "day", "values": ["-1"]}]},
                  exclusions=[{"from": date(spire, {"year": "101"}, "year"),
                               "to": date(spire, {"year": "111"}, "year"),
                               "note": "The Ten Dark Years"}]),
        )  # fmt: skip
        series(
            "Moonday Drill", "First and last Moonday of some months.",
            date(imperial, {"year": "405", "month": "frostfall", "day": "1"}, "day"),
            _rule(imperial, month, count(200),
                  filters=[{"any": [{"in": ["frostfall", "bloom"]},
                                    {"mod": "3", "eq": "0", "of": "ordinal"}]}],
                  select={"path": [{"level": "day", "cycle": {"id": "week",
                                    "values": ["moonday"], "nth": ["1", "-1"]}}]}),
        )  # fmt: skip
        series(
            "Tenth-Day Muster", "Every tenth day of the ten-day count.",
            date(imperial, {"year": "406", "month": "2", "day": "10"}, "day"),
            _rule(imperial, day, count(100), filters=[{"cycle": "tenday", "in": ["10"]}]),
        )  # fmt: skip
        series(
            "Founders' Day", "The 31st of every month, or its last day.",
            date(imperial, {"year": "407", "month": "4", "day": "31"}, "day"),
            _rule(imperial, month, count(24), missing="constrain"),
        )  # fmt: skip
        series(
            "Bloom Week", "Every day of Bloom, every tenth year.",
            date(imperial, {"year": "410", "month": "bloom", "day": "1"}, "day"),
            _rule(imperial, year, count(30), filters=[{"mod": "10", "eq": "0"}],
                  select={"path": [{"level": "month", "values": ["bloom"]},
                                   {"level": "day", "all": True}]}),
        )  # fmt: skip
        series(
            "Hundredth-Day Feast", "The hundredth day of every year.",
            date(imperial, {"year": "408", "month": "4", "day": "8"}, "day"),
            _rule(imperial, year, select={"path": [{"level": "day", "values": ["100"]}]}),
        )  # fmt: skip
        comet = series(
            "Comet Vael", "Returns every 76 years, give or take nothing.",
            after(core["Founding of the Empire"], base(10 * YEAR)),
            {"kind": "interval", "every": "2397422120", "limit": NEVER},
            category="omen",
        )  # fmt: skip
        series(
            "Mirror New Year", "New Year's Day in the mirror world, 1900 to 2100.",
            date(core["Common Era"], {"year": "1900", "month": "jan", "day": "1"}, "day",
                 era="ad"),
            _rule(core["Common Era"], year,
                  until(date(core["Common Era"], {"year": "2100"}, "year", era="ad")),
                  select={"path": [{"level": "month", "values": ["jan"]},
                                   {"level": "day", "values": ["1"]}]}),
            dimension=MIRROR_EARTH,
        )  # fmt: skip
    rite = core["Rite of Tides"]
    with writer.transaction("Sample world: single occurrences") as s:
        # Referenced (a sub-event hangs off it), modified (two days late), cancelled.
        third = s.entity("event", "Rite of Tides (the third)", ext={
            "series_id": rite, "occurrence_key": "2"}, **home)  # fmt: skip
        core.ids["Rite of Tides (the third)"] = third
        core.ids["Drowning of the Tide-Priest"] = s.entity(
            "event", "Drowning of the Tide-Priest", summary="The rite went wrong.",
            parent_id=third, visibility="spoiler",
            ext={"start": after(rite, base(3600), occurrence="2"), "end": lasting(600)}, **home,
        )  # fmt: skip
        # Typed as a date: an anchor to its own occurrence would resolve against itself.
        row = home_row(s.session, rite)
        assert row is not None
        fifth = compute_occurrence(Resolver(s.context, home["dimension_id"]), row, "4")
        assert not isinstance(fifth, RuleProblem), fifth
        late = date(spire, date_fields(s.calendar(spire), fifth.start + 2 * DAY, "hour"), "hour")
        core.ids["Rite of Tides (the late one)"] = s.entity(
            "event", "Rite of Tides (the late one)", summary="Held two days late after a storm.",
            ext={"series_id": rite, "occurrence_key": "4", "start": late, "end": lasting(DAY)},
            **home,
        )  # fmt: skip
        core.ids["Rite of Tides (cancelled)"] = s.entity(
            "event", "Rite of Tides (cancelled)", summary="No rite in the plague year.",
            ext={"series_id": rite, "occurrence_key": "6", "cancelled": True}, **home,
        )  # fmt: skip
        # Anchored to an occurrence without materializing it.
        core.ids["Vael Seen from Varn"] = s.entity(
            "event", "Vael Seen from Varn", summary="The comet's fourth return.",
            ext={"start": after(comet, occurrence="3"), "end": lasting(3 * DAY)}, **home,
        )  # fmt: skip
    world.occurrences = {"Rite of Tides": {"2": "referenced", "4": "modified", "6": "cancelled"}}


def _core_links(writer: Writer, core: Core) -> None:
    with writer.transaction("Sample world: links") as s:
        s.link(
            "core.causes",
            core["The Sundering"],
            core["Founding of Varn"],
            data={"description": "Refugees needed a home."},
        )
        s.link("core.causes", core["The Whispering Accord"], core["The Sundering"])
        s.link("core.related", core["The Sundering"], core["The Long Night"], visibility="private")
        s.link("core.related", core["Rite of Tides"], core["Founding of Varn"])
        s.link("custom.foreshadows", core["Dream of the Drowned King"], core["The Sundering"])
        s.link(
            "custom.allied_with",
            core["Founding of Varn"],
            core["Coronation of Ilsa"],
            role="crown and city",
            data={"treaty": "The Varn Compact"},
            timeline_id=core["Prime"],
            valid_from=point(1_200_000),
            valid_to=point(1_900_000),
        )
        core.ids["trashed link"] = s.link(
            "core.related", core["Burned Archive"], core["Founding of Varn"]
        )


def _core_history(writer: Writer, core: Core) -> None:
    """Edits, trash and an undo, so the fixture has revisions, trashed rows and reverts."""
    with writer.transaction("Sample world: edits") as s:
        coronation = s.entities.get(core["Coronation of Ilsa"])
        s.entities.update(
            coronation.id,
            EntityUpdate(revision=coronation.revision, summary="Ilsa the Tidebound is crowned."),
        )
    with writer.transaction("Sample world: a mistaken edit") as s:
        founding = s.entities.get(core["Founding of Varn"])
        s.entities.update(founding.id, EntityUpdate(revision=founding.revision, summary="Oops."))
    mistake = writer.last_changeset
    assert mistake is not None
    with writer.transaction("Sample world: undo") as s:
        s.history.revert(mistake)
    with writer.transaction("Sample world: trash") as s:
        s.links.trash(core["trashed link"])
        s.entities.trash(core["Burned Archive"])


def _core_moments(writer: Writer, core: Core, world: SampleWorld) -> None:
    """The resolved moments of the core's live events, for tests (and future migrations) to
    check."""
    with writer.vault.sessions() as session:
        entities = EntityService(VaultContext(writer.vault, session, writer.registry))
        for name, entity_id in sorted(core.ids.items()):
            if session.get(Entity, entity_id) is None:
                continue  # a link
            entity = entities.get(entity_id)
            if entity.kind == "event" and entity.deleted_at is None:
                ext = entity.ext or {}
                world.moments[name] = [str(ext["start_t"]), str(ext["end_t"])]


def _build_core(writer: Writer, world: SampleWorld) -> Core:
    core = Core()
    _core_dimensions(writer, core, world)
    _core_link_types(writer, world)
    _core_events(writer, core, world)
    _core_imperial_reckoning(writer, core, world)
    _core_dates(writer, core)
    _core_chain(writer, core)
    _core_series(writer, core, world)
    _core_links(writer, core)
    _core_history(writer, core)
    _core_moments(writer, core, world)
    world.backlinks = {
        "The Sundering": sorted(
            [
                "Dream of the Drowned King",
                "Founding of Varn",
                "The Long Night",
                "The Whispering Accord",
            ]
        ),
        "Founding of Varn": sorted(
            ["Coronation of Ilsa", "Rite of Tides", "The Sundering", "War of the Succession"]
        ),
    }
    return core


# --- the bulk ------------------------------------------------------------------------------------

_ADJECTIVES = (
    "Amber", "Ashen", "Broken", "Crimson", "Drowned", "Emerald", "Fallen", "Gilded", "Hollow",
    "Iron", "Jade", "Last", "Moonlit", "Northern", "Obsidian", "Pale", "Quiet", "Red", "Silver",
    "Sunken", "Thorned", "Umber", "Veiled", "Wandering", "Yellow", "Zealous",
)  # fmt: skip
_NOUNS = (
    "Accord", "Banner", "Council", "Crossing", "Duel", "Eclipse", "Exodus", "Feast", "Flood",
    "Harvest", "Heresy", "March", "Massacre", "Oath", "Plague", "Pact", "Rebellion", "Schism",
    "Siege", "Storm", "Summit", "Treaty", "Uprising", "Vigil", "Voyage", "War", "Wedding",
)  # fmt: skip
_PLACES = (
    "Varn", "Elsmere", "the Spire", "Thornwall", "Caerbridge", "the Shoals", "Mirelock",
    "Highfold", "Saltmarch", "the Drift", "Kestrel Isle", "Duskhaven", "Ostrow", "the Deeps",
)  # fmt: skip
_TAGS = (
    "Politics", "War", "Religion", "Trade", "Magic", "Exploration", "Disaster", "Royalty",
    "Guilds", "Piracy", "Science", "Art", "Prophecy", "Rebellion", "Diplomacy", "Plague",
    "Folklore", "Navy", "Smuggling", "Succession",
)  # fmt: skip
_SENTENCES = (
    "Chroniclers disagree on how it began.",
    "Few who were there wrote anything down.",
    "The isles still keep a day of silence for it.",
    "Songs about it are sung in every harbor.",
    "Its consequences shaped the next century.",
    "The guilds profited, the crown did not.",
    "Several accounts were later burned.",
)
_ROLES = ("echo", "rival", "sequel", "parallel")
_LINK_TYPES = ("core.causes", "core.related", "custom.foreshadows", "custom.allied_with")
# Shares of the bulk (probabilities per event or link).
ERA_EVERY = 50  # every 50th event is an era, the parent of later events
SERIES_EVERY = 100  # every 100th event recurs (index 25, 125, …: never an era)
IN_DREAMING = 0.15
PRIVATE_EVENT, SPOILER_EVENT = 0.04, 0.06
WITH_ALIAS = 0.2
IN_ERA = 0.6
MENTION_PER_PARAGRAPH = 0.6
PRIVATE_BLOCK, SPOILER_BLOCK = 0.05, 0.05
PRIVATE_LINK = 0.03
RELATED_WITH_ROLE = 0.3
# Starts in Aetheria (the rest are relative to a recent event); in the Dreaming, absolute or a
# Dream Count date. Imperial dates (and what is relative to them) are the 10k+ dependents of the
# calendar proposal perf test in ``large``.
SPIRE_DATE, TIDE_DATE, IMPERIAL_DATE, ABSOLUTE = 0.18, 0.15, 0.12, 0.4
RELATIVE_TO_END, CALENDAR_OFFSET, APPROXIMATE = 0.3, 0.3, 0.05
RECENT = 200  # relative anchors point at one of the last 200 events of the dimension
PRECISIONS = ("year", "month", "day", "day", "day", "hour", "minute")
# Ends (the rest are instants).
BASE_END, CALENDAR_END, TIME_POINT_END, UNKNOWN, FOREVER = 0.25, 0.15, 0.1, 0.05, 0.001
MATERIALIZED = 0.3  # of the series: one occurrence referenced, modified or cancelled


@dataclass(frozen=True)
class _Dated:
    """A bulk event's id and roughly where it starts and ends (calendar dates resolve to the
    start of their unit, a little earlier: offsets from these moments never overshoot)."""

    id: str
    start: int
    end: int


class _Bulk:
    """Seeded random events and links. Events mention and link to earlier ones, and are typed
    in every way the time model allows."""

    def __init__(self, writer: Writer, core: Core, rng: random.Random) -> None:
        self.writer = writer
        self.core = core
        self.rng = rng
        self.dimensions = (core[WORLD_NAME], core["The Dreaming"])
        self.events: list[str] = []
        self.names: dict[str, str] = {}
        self.eras: dict[str, list[str]] = {dimension: [] for dimension in self.dimensions}
        self.recent: dict[str, list[_Dated]] = {dimension: [] for dimension in self.dimensions}

    def body(self) -> Doc:
        rng = self.rng
        blocks: list[Doc] = []
        for _ in range(rng.randint(1, 3)):
            content: list[Doc | str] = [rng.choice(_SENTENCES)]
            if self.events and rng.random() < MENTION_PER_PARAGRAPH:
                target = rng.choice(self.events)
                content += [" See ", mention(self.names[target], target), "."]
            blocks.append(p(*content))
        roll = rng.random()
        if roll < PRIVATE_BLOCK:
            blocks.append(hidden("private", p("Author's note: ", rng.choice(_SENTENCES))))
        elif roll < PRIVATE_BLOCK + SPOILER_BLOCK:
            blocks.append(hidden("spoiler", p("Later revealed: ", rng.choice(_SENTENCES))))
        return doc(*blocks)

    def _date(self, s: Services, calendar: str, t: int) -> Doc:
        precision = self.rng.choice(PRECISIONS)
        fields = date_fields(s.calendar(self.core[calendar]), t, precision)
        approximate = self.rng.random() < APPROXIMATE
        return date(self.core[calendar], fields, precision, approximate=approximate)

    def start(self, s: Services, dimension: str, t: int) -> Doc:
        """A start near ``t``: an absolute moment, a date or an anchor to a recent event."""
        rng, roll = self.rng, self.rng.random()
        if dimension != self.core[WORLD_NAME]:
            return point(t) if roll < 0.5 else self._date(s, "Dream Count", t)  # noqa: PLR2004
        for share, calendar in ((SPIRE_DATE, "Spire Reckoning"), (TIDE_DATE, "Tide Count"),
                                (IMPERIAL_DATE, "Imperial Reckoning")):  # fmt: skip
            if roll < share:
                return self._date(s, calendar, t)
            roll -= share
        recent = self.recent[dimension]
        if roll < ABSOLUTE or not recent:
            return point(t)
        ref = rng.choice(recent)
        slot: Literal["start", "end"] = "end" if rng.random() < RELATIVE_TO_END else "start"
        if slot == "end" and ref.end > t:
            slot = "start"
        gap = t - (ref.end if slot == "end" else ref.start)
        if rng.random() < CALENDAR_OFFSET:
            offset = calendar_span(self.core["Spire Reckoning"], day=gap // DAY)
            return after(ref.id, offset, slot=slot, precision="day")
        return after(ref.id, base(gap), slot=slot)

    def end(self, dimension: str, t: int) -> tuple[Doc, int]:
        """An end spec and roughly where it ends."""
        rng, roll = self.rng, self.rng.random()
        if roll < FOREVER:
            return END_OF_TIME, 10**1000  # later than any start: never an anchor's target
        roll -= FOREVER
        length = rng.randrange(3600, 20 * DAY)
        if roll < BASE_END:
            return lasting(length), t + length
        roll -= BASE_END
        if roll < CALENDAR_END and dimension == self.core[WORLD_NAME]:
            days = rng.randint(1, 10)
            return lasting_for(calendar_span(self.core["Tide Count"], day=days)), t + days * DAY
        roll -= CALENDAR_END
        if roll < TIME_POINT_END:
            return ending(point(t + length)), t + length
        roll -= TIME_POINT_END
        if roll < UNKNOWN:
            return UNKNOWN_END, t
        return INSTANT, t

    def rule(self, dimension: str) -> Doc:
        """A random recurrence rule with a count limit."""
        rng, roll = self.rng, self.rng.random()
        limit = count(rng.randint(5, 200))
        if roll < 0.4 or dimension != self.core[WORLD_NAME]:  # noqa: PLR2004
            return {"kind": "interval", "every": str(rng.randrange(7 * DAY, 400 * DAY)),
                    "limit": limit}  # fmt: skip
        if roll < 0.7:  # noqa: PLR2004
            return _rule(self.core["Spire Reckoning"], {"level": "year"}, limit,
                         missing="constrain")  # fmt: skip
        return _rule(self.core["Tide Count"], {"level": "month"}, limit,
                     interval=str(rng.randint(1, 3)))  # fmt: skip

    def occurrence(self, s: Services, series: str, name: str, body: Doc) -> None:
        """Materialize the series' first or second occurrence: referenced, modified (it lasts
        longer) or cancelled."""
        ext: Doc = {"series_id": series, "occurrence_key": str(self.rng.randint(0, 1))}
        state = self.rng.choice(("referenced", "modified", "cancelled"))
        if state == "modified":
            ext["end"] = lasting(2 * DAY)
        elif state == "cancelled":
            ext["cancelled"] = True
        visibility = body.get("visibility", "public")
        s.entity("event", f"{name} ({state})", dimension_id=body["dimension_id"], ext=ext,
                 visibility=visibility)  # fmt: skip

    def event(self, s: Services, index: int) -> None:
        rng = self.rng
        dimension = self.dimensions[1] if rng.random() < IN_DREAMING else self.dimensions[0]
        is_era = index % ERA_EVERY == 0
        is_series = index % SERIES_EVERY == SERIES_EVERY // 4
        adjective = rng.choice(_ADJECTIVES)
        name = (
            f"{adjective} Age {index // ERA_EVERY + 1}"
            if is_era
            else f"{adjective} {rng.choice(_NOUNS)} of {rng.choice(_PLACES)}"
        )
        # In order, a few days to a month apart.
        t = 3_000_000 + index * 30 * DAY + rng.randrange(25 * DAY)
        ext: Doc = {"start": self.start(s, dimension, t)}
        if is_era:
            length = ERA_EVERY * 30 * DAY
            ext["end"], end = lasting(length), t + length
            ext["importance"] = 5
        elif is_series:
            ext["end"], end = lasting(rng.randrange(3600, 3 * DAY)), t
            ext["recurrence"] = self.rule(dimension)
        else:
            ext["end"], end = self.end(dimension, t)
            ext["importance"] = rng.choices([1, 2, 3, 4, 5], [30, 30, 25, 10, 5])[0]
        body: dict[str, Any] = {
            "dimension_id": dimension,
            "summary": rng.choice(_SENTENCES),
            "tags": rng.sample(_TAGS, rng.randint(0, 3)),
            "body": self.body(),
            "ext": ext,
        }
        roll = rng.random()
        if roll < PRIVATE_EVENT:
            body["visibility"] = "private"
        elif roll < PRIVATE_EVENT + SPOILER_EVENT:
            body["visibility"] = "spoiler"
        if rng.random() < WITH_ALIAS:
            body["aliases"] = [{"alias": f"The {rng.choice(_NOUNS)} of {index}"}]
        eras = self.eras[dimension]
        if not is_era and eras and rng.random() < IN_ERA:
            body["parent_id"] = rng.choice(eras[-5:])
        entity_id = s.entity("event", name, **body)
        if is_era:
            eras.append(entity_id)
        if is_series and rng.random() < MATERIALIZED:
            self.occurrence(s, entity_id, name, body)
        recent = self.recent[dimension]
        recent.append(_Dated(entity_id, t, end))
        del recent[:-RECENT]
        self.events.append(entity_id)
        self.names[entity_id] = name

    def link(self, s: Services, seen: set[tuple[str, str, str]]) -> bool:
        """A random link between two events (earlier → later); False for a duplicate."""
        rng = self.rng
        link_type = rng.choice(_LINK_TYPES)
        a, b = sorted(rng.sample(range(len(self.events)), 2))
        key = (link_type, self.events[a], self.events[b])
        if key in seen:
            return False
        seen.add(key)
        extra: dict[str, Any] = {}
        if rng.random() < PRIVATE_LINK:
            extra["visibility"] = "private"
        if link_type == "core.related" and rng.random() < RELATED_WITH_ROLE:
            extra["role"] = rng.choice(_ROLES)
        s.link(*key, **extra)
        return True


def _build_bulk(
    writer: Writer,
    core: Core,
    scale: Scale,
    rng: random.Random,
    progress: Callable[[str], None],
) -> None:
    bulk = _Bulk(writer, core, rng)
    for start in range(0, scale.events, ENTITIES_PER_TRANSACTION):
        end = min(start + ENTITIES_PER_TRANSACTION, scale.events)
        with writer.transaction(f"Sample world: events {start + 1} to {end}") as s:
            for index in range(start, end):
                bulk.event(s, index)
        progress(f"events: {end}/{scale.events}")
    if len(bulk.events) < 2:  # noqa: PLR2004 (a link needs two events)
        return
    seen: set[tuple[str, str, str]] = set()
    for start in range(0, scale.links, LINKS_PER_TRANSACTION):
        end = min(start + LINKS_PER_TRANSACTION, scale.links)
        with writer.transaction(f"Sample world: links {start + 1} to {end}") as s:
            made = start
            while made < end:
                made += bulk.link(s, seen)
        progress(f"links: {end}/{scale.links}")


# --- counts --------------------------------------------------------------------------------------


def _count(vault: OpenVault, world: SampleWorld) -> None:
    with closing(sqlite3.connect(vault.info.database_path)) as connection:
        rows = connection.execute(
            "SELECT kind, count(*) FROM entities WHERE deleted_at IS NULL GROUP BY kind"
        ).fetchall()
        world.entities = dict(sorted(rows))
        (world.trashed_entities,) = connection.execute(
            "SELECT count(*) FROM entities WHERE deleted_at IS NOT NULL"
        ).fetchone()
        (world.links,) = connection.execute(
            "SELECT count(*) FROM links WHERE deleted_at IS NULL"
        ).fetchone()


# --- entry points --------------------------------------------------------------------------------


def _quiet(_message: str) -> None:
    pass


def generate(
    data_dir: Path,
    size: Size = "small",
    *,
    seed: int = DEFAULT_SEED,
    name: str = WORLD_NAME,
    modules: Sequence[ModuleSpec] = ALL_MODULES,
    progress: Callable[[str], None] = _quiet,
) -> SampleWorld:
    """Create a new vault in ``data_dir`` and build the sample world in it."""
    registry = ModuleRegistry(modules, core_metadata=load_core_metadata())
    manager = VaultManager(data_dir, module_registry=registry)
    try:
        info = manager.create(name)
        vault = manager.open(info.id)
        world = SampleWorld(vault_id=info.id, folder=info.folder, size=size, seed=seed)
        writer = Writer(vault, registry)
        core = _build_core(writer, world)
        progress("core: done")
        _build_bulk(writer, core, SIZES[size], random.Random(seed), progress)
        _count(vault, world)
    finally:
        manager.close()
    return world


def write_fixture(target: Path, size: Size = "tiny", *, seed: int = DEFAULT_SEED) -> SampleWorld:
    """A golden fixture: ``target/vault/`` (``vault.json`` and a compacted ``lore.db``, nothing
    else) and ``target/expected.json`` (the ``SampleWorld``)."""
    if target.exists():
        raise FileExistsError(f"{target} exists: fixtures are never regenerated")
    with tempfile.TemporaryDirectory(prefix="lore-sample-") as scratch:
        world = generate(Path(scratch), size, seed=seed)
        source = Path(scratch) / "vaults" / world.folder
        (target / "vault").mkdir(parents=True)
        shutil.copyfile(source / MANIFEST_NAME, target / "vault" / MANIFEST_NAME)
        with closing(sqlite3.connect(source / DATABASE_NAME)) as connection:
            connection.execute("VACUUM INTO ?", (str(target / "vault" / DATABASE_NAME),))
    expected = json.dumps(asdict(world), indent=2, ensure_ascii=False) + "\n"
    (target / "expected.json").write_text(expected, encoding="utf-8")
    return world


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--size", choices=get_args(Size.__value__), default="small")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="data directory to add the vault to")
    target.add_argument(
        "--fixture", type=Path, help="write a golden fixture (vault folder + expected.json) here"
    )
    args = parser.parse_args(argv)

    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    if args.fixture is not None:
        world = write_fixture(args.fixture, args.size, seed=args.seed)
        print(f"fixture written to {args.fixture} (vault {world.vault_id})")
    else:
        world = generate(args.out, args.size, seed=args.seed, progress=progress)
        print(
            f"vault {world.vault_id} ({world.folder}) in {args.out}: "
            f"{sum(world.entities.values())} entities, {world.links} links"
        )


if __name__ == "__main__":
    main()
