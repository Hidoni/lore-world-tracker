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
  stable names that tests rely on. ``tiny`` is only the core.
- **The bulk** (``small`` and up): seeded random events, links, tags and aliases in the volumes
  of ``SIZES``, for realistic lists, search and performance.

**Extending it (every milestone).** When a milestone adds a feature that stores data, add it to
the core in ``_build_core`` (a new ``_core_<feature>`` step, a few entities with stable names)
and, where volume matters, to the bulk. Add what tests should check to ``SampleWorld`` (it is
written to ``expected.json`` for fixtures). Planned: real time specs, calendars and time points
on events (M3), recurring events with materialized occurrences (M3/M9), branches and worldlines
(M7, M9), facts and characters, places and other module kinds (M6, M7), correspondences (M9),
media (M10), custom fields and kinds (M11). Old fixtures are never regenerated: the next
milestone release commits a new one (``persistence-and-migrations.md`` §3.5).
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
from pathlib import Path
from typing import Any, Literal, get_args

from sqlalchemy.orm import Session

from lore import __version__
from lore.config import detect_spec_dir
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
from lore.core.time.calendars import CalendarSource, PresetChoice, source_definition
from lore.core.vaults import OpenVault, VaultManager
from lore.core.vaults.format import DATABASE_NAME, MANIFEST_NAME
from lore.modules import ALL_MODULES

type Size = Literal["tiny", "small", "medium", "large"]
type Doc = dict[str, Any]

DEFAULT_SEED = 1729
WORLD_NAME = "Aetheria"
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


def preset_definition(preset_id: str) -> dict[str, Any]:
    """A preset instantiated for a dimension in seconds, aligned at t = 0."""
    definition = source_definition(
        CalendarSource(preset=PresetChoice(id=preset_id)), detect_spec_dir()
    )
    return definition


def time_spec(duration: int) -> dict[str, Any]:
    """A dimension's ``ext``: seconds, lasting ``duration``."""
    unit = {"singular": "second", "plural": "seconds", "abbr": "s"}
    return {"base_unit": unit, "duration": str(duration)}


def point(t: int) -> dict[str, Any]:
    """A time point at an absolute moment."""
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base", "approximate": False}


def time_ref(t: int) -> Doc:
    """An inline reference to an absolute moment (calendars render it from M3 on)."""
    return {"type": "timeRef", "attrs": {"timePoint": point(t)}}


# --- writing through the services ---------------------------------------------------------------


@dataclass
class Services:
    """The services of one write transaction."""

    session: Session
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
        core.ids.update({WORLD_NAME: aetheria, "The Dreaming": dreaming, "The Hollow": hollow})
        # Every dimension comes with its prime timeline; two get their own names. Branches
        # ("The Unbroken Crown") arrive with the branches module (M9).
        for name, dimension in (
            ("Prime", aetheria),
            ("Dream-time", dreaming),
            ("Hollow Draft", hollow),
        ):
            core.ids[name] = s.prime_timeline(dimension, name)
        # Calendars from presets (the first becomes Aetheria's default); #56 adds richer ones.
        for name, dimension, preset in (
            ("Spire Reckoning", aetheria, "alternating-years"),
            ("Tide Count", aetheria, "simple-360"),
        ):
            core.ids[name] = s.entity(
                "calendar",
                name,
                dimension_id=dimension,
                ext={"definition": preset_definition(preset)},
            )
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
            **home,
        )
        core.ids["Age of Embers"] = age
        # Private first: the public text below mentions it inside a private block.
        core.ids["The Whispering Accord"] = s.entity(
            "event",
            "The Whispering Accord",
            summary="The secret pact that caused the Sundering. The big twist.",
            visibility="private",
            parent_id=age,
            **home,
        )
        core.ids["The Long Night"] = s.entity(
            "event",
            "The Long Night",
            summary="Forty days without a sunrise after the Sundering.",
            visibility="spoiler",
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
            **home,
        )
        core.ids["Dream of the Drowned King"] = s.entity(
            "event",
            "Dream of the Drowned King",
            summary="A vision shared by every sleeper in Varn on one night.",
            dimension_id=core["The Dreaming"],
        )
        core.ids["First Draft of the Fall"] = s.entity(
            "event",
            "First Draft of the Fall",
            summary="An abandoned idea.",
            dimension_id=core["The Hollow"],
        )
        core.ids["Burned Archive"] = s.entity(
            "event", "Burned Archive", summary="Cut from the canon.", **home
        )
    world.reader_hidden += ["The Whispering Accord", "First Draft of the Fall"]
    world.search = {"query": "ley lines", "name": "The Sundering"}


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


def _build_core(writer: Writer, world: SampleWorld) -> Core:
    core = Core()
    _core_dimensions(writer, core, world)
    _core_link_types(writer, world)
    _core_events(writer, core, world)
    _core_links(writer, core)
    _core_history(writer, core)
    world.backlinks = {
        "The Sundering": sorted(
            [
                "Dream of the Drowned King",
                "Founding of Varn",
                "The Long Night",
                "The Whispering Accord",
            ]
        ),
        "Founding of Varn": sorted(["Coronation of Ilsa", "Rite of Tides", "The Sundering"]),
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
IN_DREAMING = 0.15
PRIVATE_EVENT, SPOILER_EVENT = 0.04, 0.06
WITH_ALIAS = 0.2
IN_ERA = 0.6
MENTION_PER_PARAGRAPH = 0.6
PRIVATE_BLOCK, SPOILER_BLOCK = 0.05, 0.05
PRIVATE_LINK = 0.03
RELATED_WITH_ROLE = 0.3


class _Bulk:
    """Seeded random events and links. Events mention and link to earlier ones."""

    def __init__(self, writer: Writer, core: Core, rng: random.Random) -> None:
        self.writer = writer
        self.rng = rng
        self.dimensions = (core[WORLD_NAME], core["The Dreaming"])
        self.events: list[str] = []
        self.names: dict[str, str] = {}
        self.eras: dict[str, list[str]] = {dimension: [] for dimension in self.dimensions}

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

    def event(self, s: Services, index: int) -> None:
        rng = self.rng
        dimension = self.dimensions[1] if rng.random() < IN_DREAMING else self.dimensions[0]
        is_era = index % ERA_EVERY == 0
        adjective = rng.choice(_ADJECTIVES)
        name = (
            f"{adjective} Age {index // ERA_EVERY + 1}"
            if is_era
            else f"{adjective} {rng.choice(_NOUNS)} of {rng.choice(_PLACES)}"
        )
        body: dict[str, Any] = {
            "dimension_id": dimension,
            "summary": rng.choice(_SENTENCES),
            "tags": rng.sample(_TAGS, rng.randint(0, 3)),
            "body": self.body(),
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
