"""The maps module (``docs/modules/maps.md``): maps of locations, pins filtered by time (explicit
validity vs the target's existence), drill-down and breadcrumbs, branch overrides of pins, reader
visibility and the map rules."""

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from tests.entity_api import HEADERS, LinkApi, invalid, make_client
from tests.entity_modules import with_real_modules
from tests.modules.test_branches import at


def png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "olive").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class Atlas:
    """Aetheria: the continent Varn (a map), the city Port inside it (its own map)."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        api.calendar(self.dimension["id"])
        self.prime: str = self.dimension["ext"]["prime_timeline_id"]
        home = {"dimension_id": self.dimension["id"]}
        self.varn = api.make("location", "Varn", **home)
        self.port = api.make("location", "Port", parent_id=self.varn["id"], **home)
        self.continent = self.made_map(self.varn, "Varn", self.upload(png(1000, 800)))
        self.city = self.made_map(self.port, "Port", self.upload(png(400, 300)))

    @property
    def base(self) -> str:
        return f"{self.api.base}/m/maps"

    def upload(self, data: bytes, filename: str = "map.png") -> str:
        response = self.api.client.post(
            f"{self.api.base}/m/media/items", files={"file": (filename, data)}, headers=HEADERS
        )
        assert response.status_code == 201, response.json()
        media_id: str = response.json()["item"]["id"]
        return media_id

    def create_map(self, location: dict[str, Any], name: str, media_id: str, **body: Any) -> Any:
        return self.api.client.post(f"{self.base}/maps", json={
            "location_id": location["id"], "media_id": media_id, "name": name, **body})  # fmt: skip

    def made_map(self, *args: Any, **body: Any) -> dict[str, Any]:
        response = self.create_map(*args, **body)
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()["map"]
        return found

    def add_pin(self, map_row: dict[str, Any], **body: Any) -> Any:
        body.setdefault("x", 10)
        body.setdefault("y", 10)
        return self.api.client.post(f"{self.base}/maps/{map_row['id']}/pins", json=body)

    def pin(self, map_row: dict[str, Any], **body: Any) -> dict[str, Any]:
        response = self.add_pin(map_row, **body)
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()["pin"]
        return found

    def detail(self, map_row: dict[str, Any], **params: Any) -> dict[str, Any]:
        response = self.api.client.get(f"{self.base}/maps/{map_row['id']}", params=params)
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()
        return found

    def shown(self, map_row: dict[str, Any], **params: Any) -> dict[str, str]:
        return {p["display_label"]: p["shown"] for p in self.detail(map_row, **params)["pins"]}


@pytest.fixture
def atlas(api: LinkApi) -> Atlas:
    return Atlas(api)


def test_maps_of_locations(atlas: Atlas) -> None:
    api = atlas.api
    assert (atlas.continent["width"], atlas.continent["height"]) == (1000, 800)
    listed = api.client.get(f"{atlas.base}/maps", params={"location": atlas.varn["id"]}).json()
    assert [m["name"] for m in listed["items"]] == ["Varn"]
    # Only locations, only pictures.
    gadget = api.make("misc", "Gadget")
    assert invalid(atlas.create_map(gadget, "No", atlas.continent["media_id"])) == ["location_id"]
    pdf = atlas.upload(b"%PDF-1.4\n%%EOF\n", "atlas.pdf")
    assert invalid(atlas.create_map(atlas.varn, "No", pdf)) == ["media_id"]
    # The map uses its image: the media library says so, and it isn't collected.
    image = api.client.get(f"{api.base}/m/media/items/{atlas.continent['media_id']}").json()
    assert {(r["entity_id"], r["context"]) for r in image["refs"]} == {(atlas.varn["id"], "map")}
    trashed = api.client.delete(f"{atlas.base}/maps/{atlas.continent['id']}", headers=HEADERS)
    assert trashed.status_code == 200
    image = api.client.get(f"{api.base}/m/media/items/{atlas.continent['media_id']}").json()
    assert image["refs"] == []


def test_pins_drill_down_and_breadcrumbs(atlas: Atlas) -> None:
    port = atlas.pin(atlas.continent, target_entity_id=atlas.port["id"], x=500, y=400)
    assert (port["display_label"], port["drill_map_id"]) == ("Port", atlas.city["id"])
    assert port["child_map_id"] is None  # the default: the target location's first map
    label = atlas.pin(atlas.continent, label="Here be dragons", x=900, y=50)
    assert label["target"] is None
    assert invalid(atlas.add_pin(atlas.continent)) == ["label"]
    assert invalid(atlas.add_pin(atlas.continent, label="Far", x=1001)) == ["x"]
    crumbs = atlas.detail(atlas.city)["breadcrumbs"]
    assert [(c["map_id"], c["name"]) for c in crumbs] == [(atlas.continent["id"], "Varn")]
    pins = atlas.api.client.get(f"{atlas.base}/entities/{atlas.port['id']}/pins").json()
    assert [(i["map"]["id"], i["pin"]["id"]) for i in pins["items"]] == [
        (atlas.continent["id"], port["id"])
    ]


def test_pins_follow_their_validity_or_their_targets_existence(atlas: Atlas) -> None:
    api = atlas.api
    home = {"dimension_id": atlas.dimension["id"]}
    # An explicit validity: the camp stands from 100 until 200.
    atlas.pin(atlas.continent, label="Camp", timeline_id=atlas.prime,
              valid_from=at(100), valid_to=at(200))  # fmt: skip
    # Existence: the fort exists from 50 until 150; the inn says nothing (always shown).
    fort = api.make("location", "Fort", parent_id=atlas.varn["id"], **home)
    added = api.client.post(f"{api.base}/entities/{fort['id']}/facts", json={
        "field_key": "core.exists", "timeline_id": atlas.prime,
        "valid_from": at(50), "valid_to": at(150)})  # fmt: skip
    assert added.status_code == 201, added.json()
    atlas.pin(atlas.continent, target_entity_id=fort["id"])
    inn = api.make("location", "Inn", parent_id=atlas.varn["id"], **home)
    atlas.pin(atlas.continent, target_entity_id=inn["id"])
    # An event shows while it happens.
    battle = api.make("event", "Battle", ext={"start": at(120), "end": {
        "kind": "time_point", "time_point": at(130)}}, **home)  # fmt: skip
    atlas.pin(atlas.continent, target_entity_id=battle["id"])
    assert set(atlas.shown(atlas.continent)) == {"Camp", "Fort", "Inn", "Battle"}
    assert set(atlas.shown(atlas.continent, at="60")) == {"Fort", "Inn"}
    assert set(atlas.shown(atlas.continent, at="125")) == {"Camp", "Fort", "Inn", "Battle"}
    assert set(atlas.shown(atlas.continent, at="175")) == {"Camp", "Inn"}
    assert set(atlas.shown(atlas.continent, at="250")) == {"Inn"}
    # A validity needs a timeline of the location's dimension.
    other = api.make("dimension", "Elsewhere")
    refused = atlas.add_pin(atlas.continent, label="Odd", valid_from=at(1),
                            timeline_id=other["ext"]["prime_timeline_id"])  # fmt: skip
    assert invalid(refused) == ["timeline_id"]
    assert invalid(atlas.add_pin(atlas.continent, label="Odd", valid_from=at(1))) == ["timeline_id"]


def test_a_branch_ends_a_pin_early(atlas: Atlas) -> None:
    api = atlas.api
    camp = atlas.pin(atlas.continent, label="Camp", timeline_id=atlas.prime,
                     valid_from=at(100), valid_to=at(300))  # fmt: skip
    response = api.client.post(f"{api.base}/m/branches/timelines", json={
        "parent_timeline_id": atlas.prime, "branch_point": at(150), "name": "Burned"})  # fmt: skip
    assert response.status_code == 201, response.json()
    branch = response.json()["entity"]["id"]
    override = api.client.post(f"{api.base}/m/branches/overrides", json={
        "record_type": "maps.pin", "root_id": camp["id"], "timeline_id": branch,
        "changes": {"valid_to": at(160)}})  # fmt: skip
    assert override.status_code == 201, override.json()
    assert "Camp" in atlas.shown(atlas.continent, at="170")
    assert "Camp" not in atlas.shown(atlas.continent, timeline=branch, at="170")
    assert "Camp" in atlas.shown(atlas.continent, timeline=branch, at="155")
    # Only the end may change.
    refused = api.client.post(f"{api.base}/m/branches/overrides", json={
        "record_type": "maps.pin", "root_id": camp["id"], "timeline_id": branch,
        "changes": {"valid_from": at(120)}})  # fmt: skip
    assert refused.status_code == 422
    reverted = api.client.delete(
        f"{api.base}/m/branches/overrides/maps.pin/{override.json()['id']}", headers=HEADERS
    )
    assert reverted.status_code == 200, reverted.json()
    assert "Camp" in atlas.shown(atlas.continent, timeline=branch, at="170")


def test_readers_see_pins_only_when_everything_is_visible(atlas: Atlas) -> None:
    api = atlas.api
    home = {"dimension_id": atlas.dimension["id"]}
    secret = api.make("location", "Secret Cove", visibility="private", **home)
    atlas.pin(atlas.continent, target_entity_id=secret["id"])
    atlas.pin(atlas.continent, label="Hidden note", visibility="private")
    atlas.pin(atlas.continent, target_entity_id=atlas.port["id"])
    reader = atlas.detail(atlas.continent, as_reader=True)
    assert [p["display_label"] for p in reader["pins"]] == ["Port"]
    hidden_map = atlas.made_map(atlas.varn, "Plans", atlas.continent["media_id"],
                                visibility="private")  # fmt: skip
    hidden = api.client.get(f"{atlas.base}/maps/{hidden_map['id']}", params={"as_reader": True})
    assert hidden.status_code == 404
    listed = api.client.get(f"{atlas.base}/maps", params={"as_reader": True}).json()
    assert {m["name"] for m in listed["items"]} == {"Varn", "Port"}


def findings(atlas: Atlas, rule: str) -> list[dict[str, Any]]:
    response = atlas.api.client.get(f"{atlas.api.base}/consistency/findings",
                                    params={"rule": rule})  # fmt: skip
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_map_rules(atlas: Atlas) -> None:
    api = atlas.api
    home = {"dimension_id": atlas.dimension["id"]}
    ruin = api.make("location", "Ruin", parent_id=atlas.varn["id"], **home)
    atlas.pin(atlas.continent, target_entity_id=ruin["id"])
    assert findings(atlas, "maps.pin_target_missing") == []
    assert api.delete(ruin["id"]).status_code == 200
    [missing] = findings(atlas, "maps.pin_target_missing")
    assert {s["id"] for s in missing["subjects"]} == {atlas.varn["id"], ruin["id"]}
    # Off by default: a location pinned on a map of somewhere else.
    faraway = api.make("location", "Faraway", **home)
    atlas.pin(atlas.city, target_entity_id=faraway["id"])
    rule = "maps.pin_outside_map_location"
    patched = api.client.patch(f"{api.base}/consistency/rules/{rule}",
                               json={"severity": "warning"})  # fmt: skip
    assert patched.status_code == 200
    [outside] = findings(atlas, rule)
    assert {s["id"] for s in outside["subjects"]} == {atlas.port["id"], faraway["id"]}
