"""Every time-bound read honors a branch (``time-model.md`` §4.3, #114): windows, event trees,
causality, facts, state, links and the module reads with a time cursor, and the graph.

The Empire (prime): the Reign 100 to 300, the Coronation at 100, the Assassination at 200 and the
Succession at 250. "Survives" branches at the Assassination (200) and adds the Rescue at 210;
"Exile" branches from it at 250 (after it), "Plot" at 150 (before it).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client
from tests.entity_modules import with_real_modules
from tests.modules.test_branches import Empire, at


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class World(Empire):
    def __init__(self, api: LinkApi) -> None:
        super().__init__(api)
        self.succession = self.event("Succession", 250)
        self.rescue = self.event("Rescue", 210, timeline=self.survives["id"])
        self.exile = self.branch("Exile", at(250), parent=self.survives["id"])
        self.plot = self.branch("Plot", at(150), parent=self.survives["id"])
        api.made_link("core.causes", self.assassination, self.succession)
        api.made_link("core.causes", self.rescue, self.reign)  # the branch's own cause


@pytest.fixture
def world(api: LinkApi) -> World:
    return World(api)


def window(api: LinkApi, timeline: str) -> list[str]:
    response = api.client.get(f"{api.base}/timelines/{timeline}/window",
                              params={"from": "0", "to": "1000", "px": 1000})  # fmt: skip
    assert response.status_code == 200, response.json()
    return [item["name"] for item in response.json()["items"]]


def test_windows_and_event_trees_follow_the_lineage(api: LinkApi, world: World) -> None:
    prime = ["Coronation", "Reign", "Assassination", "Succession"]
    assert sorted(window(api, world.prime)) == sorted(prime)
    # Before the branch moment only; the Assassination starts exactly at it.
    assert sorted(window(api, world.survives["id"])) == ["Coronation", "Reign", "Rescue"]
    # A later branch point: its parent's whole past up to 250, cut off at its parent's 200.
    assert sorted(window(api, world.exile["id"])) == ["Coronation", "Reign", "Rescue"]
    # An earlier one: the cut-off is 150, before the Rescue.
    assert sorted(window(api, world.plot["id"])) == ["Coronation", "Reign"]
    tree = api.client.get(f"{api.base}/timelines/{world.survives['id']}/event-tree").json()
    assert sorted(node["name"] for node in tree["items"]) == ["Coronation", "Reign", "Rescue"]


def test_causality_follows_the_lineage(api: LinkApi, world: World) -> None:
    def causes(timeline: str, event: dict[str, Any]) -> set[str]:
        response = api.client.get(f"{api.base}/timelines/{timeline}/causality",
                                  params={"event": event["id"]})  # fmt: skip
        assert response.status_code == 200, response.json()
        return {node["name"] for node in response.json()["nodes"]}

    assert "Succession" in causes(world.prime, world.assassination)
    assert "Rescue" in causes(world.survives["id"], world.reign)
    assert "Rescue" not in causes(world.prime, world.reign)


def test_facts_and_state_follow_the_lineage(api: LinkApi, world: World) -> None:
    home = {"dimension_id": world.dimension["id"]}
    emperor = api.make("character", "Emperor", **home)

    def fact(timeline: str, start: int, end: int | None = None) -> None:
        body: dict[str, Any] = {"field_key": "core.exists", "timeline_id": timeline,
                                "valid_from": at(start)}  # fmt: skip
        if end is not None:
            body["valid_to"] = at(end)
        response = api.client.post(f"{api.base}/entities/{emperor['id']}/facts", json=body)
        assert response.status_code == 201, response.json()

    fact(world.prime, 50, 200)  # born at 50, assassinated at 200
    fact(world.survives["id"], 220)  # in the branch, (also) alive from 220 on

    def facts(timeline: str) -> list[str]:
        response = api.client.get(f"{api.base}/entities/{emperor['id']}/facts",
                                  params={"timeline": timeline})  # fmt: skip
        assert response.status_code == 200, response.json()
        return sorted(item["valid_from_t"] for item in response.json()["items"])

    assert facts(world.prime) == ["50"]
    assert facts(world.survives["id"]) == ["220", "50"]  # inherited and its own
    assert facts(world.plot["id"]) == ["50"]  # its cut-off (150) is before 220

    def existence(timeline: str, t: int) -> str:
        response = api.client.get(f"{api.base}/entities/{emperor['id']}/state",
                                  params={"timeline": timeline, "at": str(t)})  # fmt: skip
        assert response.status_code == 200, response.json()
        value: str = response.json()["existence"]
        return value

    assert existence(world.prime, 230) == "not_exists"
    assert existence(world.survives["id"], 230) == "exists"
    assert existence(world.exile["id"], 260) == "exists"
    # Lists at a moment use the same states.
    listed = api.client.get(f"{api.base}/entities", params={
        "kind": "character", "dimension": world.dimension["id"], "at": "230",
        "timeline": world.survives["id"]}).json()  # fmt: skip
    assert [item["name"] for item in listed["items"]] == ["Emperor"]
    listed = api.client.get(f"{api.base}/entities", params={
        "kind": "character", "dimension": world.dimension["id"], "at": "230",
        "timeline": world.prime}).json()  # fmt: skip
    assert listed["items"] == []


def test_links_and_module_reads_at_a_moment(api: LinkApi, world: World) -> None:
    home = {"dimension_id": world.dimension["id"]}
    emperor = api.make("character", "Emperor", **home)
    heir = api.make("character", "Heir", **home)
    rebel = api.make("character", "Rebel", **home)
    guard = api.make("group", "Guard", **home)
    palace = api.make("location", "Palace", **home)
    # Prime: the heir succeeds at 250; the branch: the rebel joins the guard at 210.
    api.made_link("characters.rival_of", heir, emperor, timeline_id=world.prime,
                  valid_from=at(250))  # fmt: skip
    api.made_link("groups.member_of", rebel, guard, timeline_id=world.survives["id"],
                  valid_from=at(210))  # fmt: skip
    api.made_link("locations.resides_in", emperor, palace, timeline_id=world.prime,
                  valid_from=at(100))  # fmt: skip

    def get(path: str, timeline: str, t: int) -> Any:
        response = api.client.get(f"{api.base}{path}", params={"timeline": timeline, "at": str(t)})
        assert response.status_code == 200, response.json()
        return response.json()

    def others(body: dict[str, Any]) -> set[str]:
        return {item["other"]["name"] for item in body["items"]}

    links = f"/entities/{emperor['id']}/links"
    assert others(get(links, world.prime, 260)) == {"Heir", "Palace"}
    # The branch doesn't inherit what starts at or after its branch moment.
    assert others(get(links, world.survives["id"], 260)) == {"Palace"}
    members = f"/m/groups/{guard['id']}/members"
    assert {
        m["item"]["other"]["name"] for m in get(members, world.survives["id"], 230)["items"]
    } == {"Rebel"}
    assert get(members, world.prime, 230)["items"] == []
    residents = f"/m/locations/{palace['id']}/residents"
    assert others(get(residents, world.exile["id"], 260)) == {"Emperor"}  # inherited twice
    relationships = get(f"/m/characters/{emperor['id']}/relationships", world.survives["id"], 260)
    assert not any(group["items"] for group in relationships["groups"])
    # The graph at a moment of the branch.
    graph = get(f"/m/graph/graph?dimension={world.dimension['id']}", world.survives["id"], 230)
    linked = {(e["source"], e["target"]) for e in graph["edges"] if e["kind"] == "link"}
    assert (rebel["id"], guard["id"]) in linked
