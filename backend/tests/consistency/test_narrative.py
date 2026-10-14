"""The narrative rules about existence and temporal facts (``consistency.md`` §6, the modules'
"Consistency rules"): each with a definite, a possible (circa) and no finding, checked
incrementally and by a scan, and not evaluated once its module is disabled."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.consistency.existence import OPEN_END, OPEN_START, Bound, Span, merge
from lore.core.history import recorder
from tests.consistency.test_consistency import at, findings, made, of_rule, scan, severity
from tests.entity_api import LinkApi, make_client
from tests.entity_modules import with_real_modules


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class World:
    """Aetheria and its prime timeline; times are plain moments (``~`` marks circa ones)."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        api.calendar(self.dimension["id"])  # events need one
        self.prime = self.dimension["ext"]["prime_timeline_id"]

    def make(self, kind: str, name: str, **body: Any) -> dict[str, Any]:
        return self.api.make(kind, name, dimension_id=self.dimension["id"], **body)

    def fact(self, entity: dict[str, Any], start: Any = None, end: Any = None,
             field: str = "core.exists", **body: Any) -> dict[str, Any]:  # fmt: skip
        response = self.api.client.post(
            f"{self.api.base}/entities/{entity['id']}/facts",
            json={"field_key": field, "timeline_id": self.prime, "valid_from": point(start),
                  "valid_to": point(end), **body},
        )  # fmt: skip
        assert response.status_code == 201, response.json()
        fact: dict[str, Any] = response.json()["fact"]
        return fact

    def patch_fact(self, fact: dict[str, Any], **body: Any) -> None:
        body = {k: point(v) if k.startswith("valid_") else v for k, v in body.items()}
        response = self.api.client.patch(
            f"{self.api.base}/facts/{fact['id']}", json={"revision": fact["revision"], **body}
        )
        assert response.status_code == 200, response.json()

    def link(self, link_type: str, source: dict[str, Any], target: dict[str, Any],
             start: Any = None, end: Any = None) -> dict[str, Any]:  # fmt: skip
        bounds = {} if start is None and end is None else {
            "valid_from": point(start), "valid_to": point(end)}  # fmt: skip
        return self.api.made_link(link_type, source, target, **bounds)

    def event(self, name: str, start: Any, *participants: dict[str, Any]) -> dict[str, Any]:
        event = made(self.api.create("event", name, dimension_id=self.dimension["id"],
                                     ext={"start": point(start)}))  # fmt: skip
        for participant in participants:
            self.link("core.participant", event, participant)
        return event


def point(value: Any) -> Any:
    """A moment (``"250~"``: circa) as a time point."""
    if value is None:
        return None
    text = str(value)
    return at(int(text.rstrip("~")), approximate=text.endswith("~"))


@pytest.fixture
def world(api: LinkApi) -> World:
    return World(api)


def found(api: LinkApi, rule: str) -> list[tuple[str, list[str]]]:
    """The rule's findings: certainty and subject names."""
    return sorted((f["certainty"], [s["name"] for s in f["subjects"]]) for f in of_rule(api, rule))


def rescanned(api: LinkApi) -> None:
    """A full scan finds what the incremental checks did."""
    before = sorted((f["fingerprint"], f["certainty"]) for f in findings(api))
    scan(api)
    assert sorted((f["fingerprint"], f["certainty"]) for f in findings(api)) == before


# --- helpers -------------------------------------------------------------------------------------


def test_merged_periods() -> None:
    def b(t: int) -> Bound:
        return Bound("fact", str(t), "valid_from", t)

    merged = merge([Span(b(30), b(40)), Span(b(10), b(20)), Span(b(20), b(25)),
                    Span(b(50), OPEN_END), Span(b(60), b(70))])  # fmt: skip
    assert merged == [Span(b(10), b(25)), Span(b(30), b(40)), Span(b(50), OPEN_END)]
    assert merge([Span(b(5), b(9)), Span(OPEN_START, b(6))]) == [Span(OPEN_START, b(9))]


# --- core ----------------------------------------------------------------------------------------


def test_participant_not_existing(api: LinkApi, world: World) -> None:
    rule = "core.event.participant_not_existing"
    aria = world.make("character", "Aria")
    world.event("Feast", 50, aria)
    assert found(api, rule) == []  # no existence: she always exists
    life = world.fact(aria, 100, 200)
    assert found(api, rule) == [("definite", ["Aria", "Feast"])]
    world.event("Wedding", 150, aria)
    world.event("Funeral", "250~", aria)
    assert found(api, rule) == [
        ("definite", ["Aria", "Feast"]), ("possible", ["Aria", "Funeral"])
    ]  # fmt: skip
    [feast] = [f for f in of_rule(api, rule) if f["certainty"] == "definite"]
    assert (feast["severity"], feast["owner"], feast["message"]) == (
        "warning", "core", "“Aria” takes part in “Feast” while not existing."
    )  # fmt: skip
    rescanned(api)
    # Her existence changes: the event is covered now.
    world.patch_fact(life, valid_from=10, valid_to=300)
    assert found(api, rule) == []


def test_fact_rules(api: LinkApi, world: World) -> None:
    outside, overlap = "core.fact.outside_existence", "core.fact.overlap"
    engine = world.make("gadget", "Engine")
    world.fact(engine, 100, 200)
    world.fact(engine, 120, 180, "rank", value=1)
    world.fact(engine, None, 150, "rank", value=2)  # open start: not checked
    assert found(api, outside) == []
    assert found(api, overlap) == [("definite", ["Engine"])]  # 1 and 2 overlap in [120, 150)
    world.fact(engine, 190, 250, "rank", value=3)
    world.fact(engine, 150, "210~", "core.name", value="Great Engine")
    assert found(api, outside) == [("definite", ["Engine"]), ("possible", ["Engine"])]
    messages = sorted(f["message"] for f in of_rule(api, outside))
    assert messages == [
        "A name of “Engine” is valid while it doesn't exist.",
        "A value of “Rank” of “Engine” is valid while it doesn't exist.",
    ]
    # Touching values don't overlap; a multiple field's values may; circa ends possibly do.
    world.fact(engine, 180, 190, "rank", value=4)
    world.fact(engine, 120, 180, "titles", value=["Old"])
    world.fact(engine, 130, 150, "titles", value=["New"])
    assert found(api, overlap) == [("definite", ["Engine"])]
    clock = world.make("gadget", "Clock")
    world.fact(clock, 10, "60~", "rank", value=1)
    world.fact(clock, 50, None, "rank", value=2)
    assert found(api, overlap) == [("definite", ["Engine"]), ("possible", ["Clock"])]
    assert of_rule(api, overlap)[0]["message"] == (
        "Two values of “Rank” of “Engine” overlap in time: the later one wins."
    )
    rescanned(api)


def test_link_outside_existence(api: LinkApi, world: World) -> None:
    rule = "core.link.outside_existence"
    aria, bram = world.make("character", "Aria"), world.make("character", "Bram")
    world.fact(aria, 100, 200)
    world.link("core.related", aria, bram)  # timeless: not checked
    world.link("core.related", aria, bram, 120, 180)
    assert found(api, rule) == []
    late = world.link("core.related", bram, aria, 150, 250)
    world.link("core.related", aria, bram, "90~", 150)
    assert found(api, rule) == [("definite", ["Aria", "Bram"]), ("possible", ["Aria", "Bram"])]
    rescanned(api)
    assert api.delete_link(late["id"]).status_code == 200
    assert found(api, rule) == [("possible", ["Aria", "Bram"])]


# --- modules -------------------------------------------------------------------------------------


def test_characters_rules(api: LinkApi, world: World) -> None:
    born, spouses = "characters.parent_born_after_child", "characters.concurrent_spouses"
    aria, bram, cora = (world.make("character", n) for n in ("Aria", "Bram", "Cora"))
    world.fact(aria, 100)
    world.fact(bram, 50)
    world.fact(cora, "40~")
    world.link("characters.parent_of", aria, bram)
    world.link("characters.parent_of", bram, cora)
    assert found(api, born) == [("definite", ["Aria", "Bram"]), ("possible", ["Bram", "Cora"])]
    rescanned(api)

    # Off by default: evaluated once enabled.
    world.link("characters.spouse_of", aria, bram, 0, 100)
    world.link("characters.spouse_of", cora, aria, 50, 200)
    world.link("characters.spouse_of", aria, bram, 300)  # the same spouse again
    assert found(api, spouses) == []
    assert severity(api, spouses, "warning").status_code == 200
    assert found(api, spouses) == [("definite", ["Aria", "Bram", "Cora"])]
    world.link("characters.spouse_of", cora, bram, "120~", 250)
    assert found(api, spouses) == [
        ("definite", ["Aria", "Bram", "Cora"]), ("possible", ["Cora", "Aria", "Bram"])
    ]  # fmt: skip
    rescanned(api)


def test_groups_rules(api: LinkApi, world: World) -> None:
    outside, leader = "groups.member_outside_group_existence", "groups.leader_not_member"
    guild, aria = world.make("group", "Guild"), world.make("character", "Aria")
    world.fact(guild, 100, 200)
    world.link("groups.member_of", aria, guild, 120, 150)
    assert found(api, outside) == []
    world.link("groups.member_of", aria, guild, 150, 250)
    world.link("groups.member_of", aria, guild, "90~", 110)
    assert found(api, outside) == [("definite", ["Guild", "Aria"]), ("possible", ["Guild", "Aria"])]
    assert of_rule(api, outside)[0]["message"] == (
        "“Aria” is a member of “Guild” while it doesn't exist."
    )

    assert severity(api, leader, "warning").status_code == 200
    bram = world.make("character", "Bram")
    world.link("groups.led_by", guild, bram, 130, 140)
    assert found(api, leader) == [("definite", ["Bram", "Guild"])]
    world.link("groups.member_of", bram, guild, "145~", 160)  # may start too late
    assert found(api, leader) == [("possible", ["Bram", "Guild"])]
    world.link("groups.member_of", bram, guild)  # timeless: always a member
    assert found(api, leader) == []
    rescanned(api)


def test_locations_rules(api: LinkApi, world: World) -> None:
    site, nested = (
        "locations.event_at_nonexistent_location",
        "locations.child_outside_parent_existence",
    )
    city = world.make("location", "Vael")
    world.fact(city, 100, 200)
    for name, start in (("Fair", 150), ("Siege", 250), ("Flood", "90~")):
        event = world.event(name, start)
        world.link("locations.event_site", event, city)
    assert found(api, site) == [("definite", ["Vael", "Siege"]), ("possible", ["Vael", "Flood"])]

    tower = world.make("location", "Tower", parent_id=city["id"])
    world.fact(tower, 120, 180)
    assert found(api, nested) == []
    world.fact(tower, 190, "210~")
    assert found(api, nested) == [("possible", ["Tower", "Vael"])]
    gate = world.make("location", "Gate", parent_id=city["id"])
    world.fact(gate, 50, 150)
    assert found(api, nested) == [("definite", ["Gate", "Vael"]), ("possible", ["Tower", "Vael"])]
    rescanned(api)


def test_species_and_languages_rules(api: LinkApi, world: World) -> None:
    member = "species.member_before_emergence"
    speakers, entries = "languages.speaker_outside_existence", "languages.entry_outside_existence"
    elves, aria, bram = (world.make(k, n) for k, n in (("species", "Elves"),
                         ("character", "Aria"), ("character", "Bram")))  # fmt: skip
    world.fact(elves, 100)
    world.fact(aria, 150)
    world.fact(bram, "90~", 120)
    world.link("species.is_a", aria, elves)
    world.link("species.is_a", bram, elves)
    assert found(api, member) == [("possible", ["Bram", "Elves"])]

    elvish = world.make("language", "Elvish")
    world.fact(elvish, 100, 200)
    world.link("languages.speaks", aria, elvish, 150, 250)
    world.link("languages.speaks", bram, elvish, 120, 130)
    assert found(api, speakers) == [("definite", ["Elvish", "Aria"])]
    for headword, start, end in (("mellon", 120, 150), ("galad", 50, 120), ("hîr", 150, "210~")):
        response = api.client.post(
            f"{api.base}/m/languages/{elvish['id']}/lexicon",
            json={"headword": headword, "timeline_id": world.prime, "valid_from": point(start),
                  "valid_to": point(end)},
        )  # fmt: skip
        assert response.status_code == 201, response.json()
    assert found(api, entries) == [("definite", ["Elvish"]), ("possible", ["Elvish"])]
    rescanned(api)

    # A disabled module's rules aren't evaluated, and come back with it.
    assert api.modules("species", enabled=False).status_code == 200
    assert found(api, member) == []
    assert api.modules("species", enabled=True).status_code == 200
    assert found(api, member) == [("possible", ["Bram", "Elves"])]
