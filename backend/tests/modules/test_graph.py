"""The graph module (``docs/modules/graph.md``): nodes and link, mention and parent edges, every
filter, the local graph, the time cursor, truncation and visibility."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules
from tests.test_facts import absolute
from tests.test_richtext import block, doc, mention, p, text


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def graph(api: LinkApi, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/m/graph/graph", params=params)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


class World:
    """Aetheria: Aria (tagged Royal) and Bram are married from 100 to 200; Aria's text mentions
    Varn (and, in a private block, the Spy); Varn contains the Tower; the Spy is private and
    rivals Aria; Bram exists until 50; a misc note stands alone in another dimension."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        self.prime = self.dimension["ext"]["prime_timeline_id"]
        home = {"dimension_id": self.dimension["id"]}
        self.varn = api.make("location", "Varn", **home)
        self.tower = api.make("location", "Tower", parent_id=self.varn["id"], **home)
        self.spy = api.make("character", "Spy", visibility="private", **home)
        self.bram = api.make("character", "Bram", **home)
        self.aria = api.make(
            "character",
            "Aria",
            tags=["Royal"],
            body=doc(
                p(text("Lives in "), text("Varn", mention(self.varn["id"]))),
                block("private", p(text("watched by "), text("Spy", mention(self.spy["id"])))),
            ),
            **home,
        )
        self.other = api.make("dimension", "Elsewhere")
        self.note = api.make("misc", "Note", dimension_id=self.other["id"])
        self.marriage = api.made_link(
            "characters.spouse_of", self.aria, self.bram, timeline_id=self.prime,
            valid_from=absolute(100), valid_to=absolute(200), role="queen consort",
        )  # fmt: skip
        self.rivalry = api.made_link("characters.rival_of", self.spy, self.aria)
        self.home = api.made_link("locations.resides_in", self.aria, self.varn)
        response = api.client.post(
            f"{api.base}/entities/{self.bram['id']}/facts",
            json={"field_key": "core.exists", "timeline_id": self.prime,
                  "valid_to": absolute(50)},
        )  # fmt: skip
        assert response.status_code == 201, response.json()


@pytest.fixture
def world(api: LinkApi) -> World:
    return World(api)


def names(body: dict[str, Any]) -> set[str]:
    return {node["name"] for node in body["nodes"]}


SYMMETRIC = {"characters.spouse_of", "core.related"}


def edges(body: dict[str, Any]) -> set[tuple[str, str, str, str | None]]:
    """(kind, source name, target name, link type); a symmetric link's ends sorted by name
    (they are stored in a canonical order)."""
    by_id = {node["id"]: node["name"] for node in body["nodes"]}
    found = set()
    for edge in body["edges"]:
        ends = [by_id[edge["source"]], by_id[edge["target"]]]
        if edge["link_type"] in SYMMETRIC:
            ends.sort()
        found.add((edge["kind"], ends[0], ends[1], edge["link_type"]))
    return found


PEOPLE = {"Aria", "Bram", "Spy", "Varn", "Tower"}


def test_the_whole_graph(api: LinkApi, world: World) -> None:
    body = graph(api, dimension=world.dimension["id"])
    assert names(body) >= PEOPLE
    assert "Note" not in names(body)  # another dimension
    assert edges(body) >= {
        ("link", "Aria", "Bram", "characters.spouse_of"),
        ("link", "Spy", "Aria", "characters.rival_of"),
        ("link", "Aria", "Varn", "locations.resides_in"),
        ("mention", "Aria", "Varn", None),
        ("mention", "Aria", "Spy", None),  # authors see mentions in private blocks
        ("parent", "Varn", "Tower", None),
    }
    aria = next(node for node in body["nodes"] if node["name"] == "Aria")
    assert aria["degree"] == 5
    assert aria["existence"] is None  # no cursor
    assert body["nodes"][0]["name"] == "Aria"  # highest degree first
    spouse = next(e for e in body["edges"] if e["link_type"] == "characters.spouse_of")
    assert (spouse["label"], spouse["weight"]) == ("queen consort", 1)
    assert body["truncated"] is False
    # The whole vault: the other dimension's note too.
    assert "Note" in names(graph(api))


def test_filters(api: LinkApi, world: World) -> None:
    home = world.dimension["id"]
    assert names(graph(api, dimension=home, kind=["location"])) == {"Varn", "Tower"}
    only_spouses = graph(api, dimension=home, link_type=["characters.spouse_of"],
                         include_mentions=False, include_hierarchy=False)  # fmt: skip
    assert {e[0:3] for e in edges(only_spouses)} == {("link", "Aria", "Bram")}
    no_mentions = edges(graph(api, dimension=home, include_mentions=False))
    assert not any(edge[0] == "mention" for edge in no_mentions)
    assert not any(edge[0] == "parent" for edge in edges(
        graph(api, dimension=home, include_hierarchy=False)))  # fmt: skip
    tags = api.client.get(f"{api.base}/tags").json()["items"]
    royal = next(tag["id"] for tag in tags if tag["name"] == "Royal")
    assert names(graph(api, tag=[royal])) == {"Aria"}


def test_the_local_graph(api: LinkApi, world: World) -> None:
    one = graph(api, center=world.varn["id"], depth=1)
    assert names(one) == {"Varn", "Tower", "Aria"}
    # Aria's spouse and rival are two steps away; edges among the reached nodes come too.
    two = graph(api, center=world.varn["id"], depth=2)
    assert names(two) == PEOPLE
    assert ("link", "Spy", "Aria", "characters.rival_of") in edges(two)
    hidden = api.client.get(f"{api.base}/m/graph/graph",
                            params={"center": world.spy["id"], "as_reader": True})  # fmt: skip
    problem(hidden, 404, "not_found")


def test_the_time_cursor(api: LinkApi, world: World) -> None:
    home = world.dimension["id"]
    # At 150: married, but Bram no longer exists (until 50): his node and edges are left out.
    late = graph(api, dimension=home, timeline=world.prime, at=150)
    assert "Bram" not in names(late)
    existence = {node["name"]: node["existence"] for node in late["nodes"]}
    assert existence["Aria"] == "unknown"
    # At 20: Bram exists, but the marriage is yet to come.
    early = graph(api, dimension=home, timeline=world.prime, at=20)
    assert {node["name"]: node["existence"] for node in early["nodes"]}["Bram"] == "exists"
    assert ("link", "Aria", "Bram", "characters.spouse_of") not in edges(early)
    assert ("link", "Aria", "Varn", "locations.resides_in") in edges(early)  # timeless
    # Without a timeline: the prime of the dimension.
    assert names(graph(api, dimension=home, at=20)) == names(early)
    # The local graph stops at entities that don't exist then.
    local = graph(api, center=world.aria["id"], at=150)
    assert "Bram" not in names(local)


def test_truncation_keeps_the_best_connected(api: LinkApi, world: World) -> None:
    body = graph(api, dimension=world.dimension["id"], limit=2)
    assert body["truncated"] is True
    assert [node["name"] for node in body["nodes"]][:1] == ["Aria"]
    assert len(body["nodes"]) == 2
    kept = {node["id"] for node in body["nodes"]}
    assert all(e["source"] in kept and e["target"] in kept for e in body["edges"])


def test_readers_see_only_what_they_may(api: LinkApi, world: World) -> None:
    body = graph(api, dimension=world.dimension["id"], as_reader=True)
    assert "Spy" not in names(body)
    assert not any(world.spy["id"] in (e["source"], e["target"]) for e in body["edges"])
    # A private link between visible entities, and a mention only in a private block.
    api.made_link("core.related", world.bram, world.varn, visibility="private")
    bram = api.get(world.bram["id"]).json()
    secret = doc(block("private", p(text("Varn", mention(world.tower["id"])))))
    assert api.patch(bram, body=secret).status_code == 200
    assert ("mention", "Bram", "Tower", None) in edges(graph(api, dimension=world.dimension["id"]))
    reader = edges(graph(api, dimension=world.dimension["id"], as_reader=True))
    assert ("link", "Bram", "Varn", "core.related") not in reader
    assert ("mention", "Bram", "Tower", None) not in reader
    assert ("link", "Bram", "Varn", "core.related") in edges(
        graph(api, dimension=world.dimension["id"]))  # fmt: skip


def test_disabled_module(api: LinkApi, world: World) -> None:
    assert api.modules("graph", enabled=False).status_code == 200
    response = api.client.get(f"{api.base}/m/graph/graph")
    problem(response, 404, "module_disabled")
