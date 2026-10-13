"""The locations module (``docs/modules/locations.md``): the ``location`` kind, its link types
and the tree, events-here and residents endpoints."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def at(t: int) -> dict[str, Any]:
    return {"start": {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}}


def m(api: LinkApi, path: str, **params: Any) -> Any:
    return api.client.get(f"{api.base}/m/locations{path}", params=params)


class World:
    """Aetheria: Galaxy ⊃ Varn (city) ⊃ Spire (building); the Void (multiversal)."""

    def __init__(self, api: LinkApi) -> None:
        self.dimension = api.make("dimension", "Aetheria")
        api.calendar(self.dimension["id"])
        self.timeline = self.dimension["ext"]["prime_timeline_id"]
        home = {"dimension_id": self.dimension["id"]}
        self.galaxy = api.make("location", "Galaxy", fields={"location_type": "galaxy"}, **home)
        self.varn = api.make(
            "location",
            "Varn",
            parent_id=self.galaxy["id"],
            fields={"location_type": "city", "population": 12000},
            **home,
        )
        self.spire = api.make("location", "Spire", parent_id=self.varn["id"], **home)
        self.void = api.make("location", "The Void", fields={"location_type": "plane"})

        def event(name: str, t: int, site: dict[str, Any] | None) -> dict[str, Any]:
            made = api.make("event", name, ext=at(t), **home)
            if site is not None:
                api.made_link("locations.event_site", made, site)
            return made

        self.founding = event("Founding", 100, self.varn)
        self.siege = event("Siege", 300, self.spire)
        self.storm = event("Storm", 200, self.galaxy)
        self.elsewhere = event("Elsewhere", 50, None)


def test_kind_and_link_types(api: LinkApi) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    location = next(kind for kind in registry["kinds"] if kind["key"] == "location")
    assert location["icon"] == "map-pin"
    assert location["allowed_parents"] == ["location", "misc"]
    assert [field["key"] for field in location["fields"]] == [
        "location_type",
        "type_detail",
        "population",
        "climate",
        "area",
        "coordinates",
    ]
    keys = {link["key"] for link in registry["link_types"]}
    assert {
        "locations.event_site",
        "locations.resides_in",
        "locations.origin",
        "locations.connected_to",
    } <= keys


def test_link_rules(api: LinkApi) -> None:
    world = World(api)
    # Only events have sites; connections join locations and may cross dimensions (portals).
    refused = api.link("locations.event_site", world.galaxy, world.varn)
    problem(refused, 422, "link_type_not_allowed")
    other = api.make("dimension", "Umbra")
    shadow = api.make("location", "Shadow Gate", dimension_id=other["id"])
    portal = api.made_link("locations.connected_to", world.spire, shadow, data={"kind": "portal"})
    assert portal["data"] == {"kind": "portal"}
    bad = api.link("locations.connected_to", world.spire, world.void, data={"kind": "teleport"})
    problem(bad, 422, "validation_error")
    gadget = api.make("gadget", "Compass")
    api.made_link("locations.origin", gadget, world.varn)


def test_the_tree(api: LinkApi) -> None:
    world = World(api)
    top = m(api, "/tree").json()
    assert [(n["name"], n["location_type"], n["child_count"]) for n in top["items"]] == [
        ("Galaxy", "galaxy", 1),
        ("The Void", "plane", 0),
    ]
    assert top["items"][0]["children"] is None
    deep = m(api, "/tree", root=world.galaxy["id"], depth=3).json()
    (varn,) = deep["items"]
    assert (varn["name"], varn["location_type"]) == ("Varn", "city")
    (spire,) = varn["children"]
    assert (spire["name"], spire["location_type"], spire["children"]) == ("Spire", None, [])
    # A dimension's tree has its locations and the multiversal ones.
    in_dimension = m(api, "/tree", dimension=world.dimension["id"]).json()["items"]
    assert [n["name"] for n in in_dimension] == ["Galaxy", "The Void"]
    problem(m(api, "/tree", root=world.founding["id"]), 404, "not_found")


def test_events_here(api: LinkApi) -> None:
    world = World(api)

    def names(location: dict[str, Any], **params: Any) -> list[str]:
        response = m(api, f"/{location['id']}/events", timeline=world.timeline, **params)
        assert response.status_code == 200, response.json()
        return [item["name"] for item in response.json()["items"]]

    assert names(world.galaxy) == ["Founding", "Storm", "Siege"]
    assert names(world.galaxy, include_descendants="false") == ["Storm"]
    assert names(world.varn) == ["Founding", "Siege"]
    assert names(world.galaxy, **{"from": "150", "to": "250"}) == ["Storm"]
    item = m(api, f"/{world.varn['id']}/events", timeline=world.timeline).json()["items"][1]
    assert item["site_ids"] == [world.spire["id"]]
    assert (item["start_t"], item["display"]["start"]) == ("300", item["display"]["start"])
    # Trashed sites and links drop out.
    api.client.delete(f"{api.base}/entities/{world.spire['id']}")
    assert names(world.varn) == ["Founding"]
    problem(m(api, f"/{world.founding['id']}/events", timeline=world.timeline), 404, "not_found")
    problem(m(api, f"/{world.varn['id']}/events", timeline=world.varn["id"]), 404, "not_found")


def test_residents(api: LinkApi) -> None:
    world = World(api)
    hero = api.make("gadget", "Hero")
    exile = api.make("gadget", "Exile")
    api.made_link("locations.resides_in", hero, world.varn, data={"kind": "home"})
    api.made_link("locations.resides_in", exile, world.varn, data={"kind": "exile"})
    items = m(api, f"/{world.varn['id']}/residents").json()["items"]
    assert [(item["other"]["name"], item["link"]["data"]) for item in items] == [
        ("Exile", {"kind": "exile"}),
        ("Hero", {"kind": "home"}),
    ]
    assert m(api, f"/{world.spire['id']}/residents").json()["items"] == []


def test_disabling_hides_everything_without_data_loss(api: LinkApi) -> None:
    world = World(api)
    assert api.modules("locations", enabled=False).status_code == 200
    problem(m(api, "/tree"), 404, "module_disabled")
    problem(api.get(world.varn["id"]), 404, "module_disabled")
    assert api.links_of(world.founding) == []
    assert api.modules("locations", enabled=True).status_code == 200
    assert api.get(world.varn["id"]).json()["fields"]["population"] == "12000"
    assert [link["other"]["name"] for link in api.links_of(world.founding)] == ["Varn"]
