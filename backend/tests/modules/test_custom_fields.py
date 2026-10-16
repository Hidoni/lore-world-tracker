"""The custom_fields module (``docs/modules/custom_fields.md``): authors' fields on kinds, served
with the registry and validated, indexed and shown like any other field; the rules for changes
(safe type conversions migrating values, options in use, temporal off, delete with values)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from lore.core.time.models import EntityTimeField
from tests.entity_api import LinkApi, invalid, make_client, problem
from tests.entity_modules import with_real_modules


class Fields:
    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.client = api.client
        self.base = f"{api.base}/m/custom_fields/fields"

    def create(self, kind_key: str = "character", key: str = "title", **body: Any) -> Any:
        body.setdefault("label", key.title())
        body.setdefault("type", "text")
        return self.client.post(self.base, json={"kind_key": kind_key, "key": key, **body})

    def made(self, kind_key: str = "character", key: str = "title", **body: Any) -> dict[str, Any]:
        response = self.create(kind_key, key, **body)
        assert response.status_code == 201, response.json()
        field: dict[str, Any] = response.json()["field"]
        return field

    def get(self, field: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(f"{self.base}/{field['id']}")
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()
        return found

    def patch(self, field: dict[str, Any], **body: Any) -> Any:
        body.setdefault("revision", self.get(field)["revision"])
        return self.client.patch(f"{self.base}/{field['id']}", json=body)

    def patched(self, field: dict[str, Any], **body: Any) -> dict[str, Any]:
        response = self.patch(field, **body)
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()["field"]
        return found

    def delete(self, field: dict[str, Any], **params: Any) -> Any:
        return self.client.delete(f"{self.base}/{field['id']}", params=params)

    def registry_fields(self, kind: str) -> dict[str, dict[str, Any]]:
        registry = self.client.get(f"{self.api.base}/registry").json()
        found = next(k for k in registry["kinds"] if k["key"] == kind)
        return {field["key"]: field for field in found["fields"]}

    def values(self, entity: dict[str, Any], **params: Any) -> dict[str, Any]:
        response = self.api.client.get(f"{self.api.base}/entities/{entity['id']}", params=params)
        assert response.status_code == 200, response.json()
        fields: dict[str, Any] = response.json()["fields"]
        return fields

    def undo_last(self) -> None:
        last = self.client.get(f"{self.api.base}/changes", params={"limit": 1}).json()["items"][0]
        response = self.client.post(f"{self.api.base}/changes/{last['id']}/revert")
        assert response.status_code == 200, response.json()


@pytest.fixture
def fields(tmp_path: Path) -> Iterator[Fields]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield Fields(LinkApi(client))


def options(*keys: str) -> list[dict[str, Any]]:
    return [{"key": key, "label": key.title()} for key in keys]


def test_fields_join_the_registry_and_validate(fields: Fields) -> None:
    api = fields.api
    title = fields.made(help="How they are addressed", section="Court")
    assert (title["key"], title["sort_key"], title["entities_with_values"]) == (
        "custom.title", "000001", 0,
    )  # fmt: skip
    rank = fields.made("*", "rank", type="integer")
    shown = fields.registry_fields("character")
    assert shown["custom.title"]["help"] == "How they are addressed"
    assert shown["custom.rank"]["type"] == "integer"
    assert "custom.rank" in fields.registry_fields("location")
    assert "custom.rank" not in fields.registry_fields("dimension")  # a system kind
    assert "custom.title" not in fields.registry_fields("location")

    ilsa = api.make("character", "Ilsa", fields={"custom.title": "Queen", "custom.rank": 3})
    assert fields.values(ilsa) == {"custom.title": "Queen", "custom.rank": "3"}
    assert invalid(api.create("character", "X", fields={"custom.rank": "high"})) == [
        "fields.custom.rank"
    ]
    assert invalid(api.create("location", "X", fields={"custom.title": "Lord"})) == [
        "fields.custom.title"
    ]
    assert fields.get(title)["entities_with_values"] == 1
    hits = api.client.get(f"{api.base}/search", params={"q": "Queen"}).json()["items"]
    assert [hit["entity_id"] for hit in hits] == [ilsa["id"]]

    # Keys: unique per kind, a "*" key everywhere; kinds and types must exist.
    assert invalid(fields.create(key="title")) == ["key"]
    assert invalid(fields.create("location", "rank")) == ["key"]
    assert fields.create("location", "title").status_code == 201
    assert invalid(fields.create("spell", "power")) == ["kind_key"]
    assert invalid(fields.create(key="aura", type="colour")) == ["type"]
    assert invalid(fields.create(key="house", type="enum")) == ["options"]
    assert invalid(fields.create(key="motto", options=options("a"))) == ["options"]

    listed = fields.client.get(fields.base, params={"kind": "character"}).json()["items"]
    assert [field["key"] for field in listed] == ["custom.rank", "custom.title"]
    reordered = fields.client.post(
        f"{fields.base}/reorder", json={"kind_key": "*", "ids": [rank["id"]]}
    )
    assert reordered.status_code == 200, reordered.json()
    assert invalid(fields.client.post(f"{fields.base}/reorder",
                                      json={"kind_key": "character", "ids": [rank["id"]]})) == [
        "ids"
    ]  # fmt: skip


def test_reorder(fields: Fields) -> None:
    first, second, third = (fields.made(key=key) for key in ("a", "b", "c"))
    response = fields.client.post(
        f"{fields.base}/reorder",
        json={"kind_key": "character", "ids": [third["id"], first["id"], second["id"]]},
    )
    assert response.status_code == 200, response.json()
    assert [f["key"] for f in response.json()["items"]] == ["custom.c", "custom.a", "custom.b"]
    shown = [k for k in fields.registry_fields("character") if k.startswith("custom.")]
    assert shown == ["custom.c", "custom.a", "custom.b"]


def test_archive_keeps_values_hidden_and_required(fields: Fields) -> None:
    api = fields.api
    title = fields.made()
    ilsa = api.make("character", "Ilsa", fields={"custom.title": "Queen"})
    archived = fields.patched(title, archived=True)
    assert archived["archived"] is True
    assert fields.values(ilsa) == {}
    assert fields.registry_fields("character")["custom.title"]["archived"] is True
    fields.patched(title, archived=False)
    assert fields.values(ilsa) == {"custom.title": "Queen"}
    # Required applies on the next save.
    bob = api.make("character", "Bob")
    fields.patched(title, required=True)
    assert invalid(api.patch(bob, name="Bobby")) == ["fields.custom.title"]
    problem(fields.patch(title, label="Old", revision=1), 409, "conflict")


def test_safe_type_conversions_migrate_values(fields: Fields) -> None:
    api = fields.api
    motto = fields.made(key="motto", type="long_text")
    house = fields.made(key="house")
    ilsa = api.make("character", "Ilsa", fields={"custom.motto": "Iron\n\nendures",
                                                  "custom.house": "stark"})  # fmt: skip
    bob = api.make("character", "Bob", fields={"custom.house": "Lannister"})
    fields.patched(motto, type="text")
    assert fields.values(ilsa)["custom.motto"] == "Iron endures"

    # text → enum needs a mapping of every value to an option (or null: cleared).
    house_options = options("north", "west")
    assert invalid(fields.patch(house, type="enum", options=house_options)) == ["value_map"]
    assert invalid(fields.patch(house, type="enum", options=house_options,
                                value_map={"stark": "north", "Lannister": "east"})) == [
        "value_map"
    ]  # fmt: skip
    changed = fields.patch(house, type="enum", options=house_options,
                           value_map={"stark": "north", "Lannister": None})  # fmt: skip
    assert changed.status_code == 200, changed.json()
    assert sorted(changed.json()["affected"]["entities"]) == sorted([ilsa["id"], bob["id"]])
    assert fields.values(ilsa)["custom.house"] == "north"
    assert "custom.house" not in fields.values(bob)

    # Options in use can't go; unused ones can.
    assert invalid(fields.patch(house, options=options("west"))) == ["options"]
    fields.patched(house, options=options("north"))
    # enum → multi_enum wraps the values.
    fields.patched(house, type="multi_enum")
    assert fields.values(ilsa)["custom.house"] == ["north"]

    # integer → decimal; anything else is refused.
    age = fields.made(key="age", type="integer")
    api.patch(api.get(ilsa["id"]).json(), fields={"custom.age": 30})
    fields.patched(age, type="decimal")
    assert fields.values(ilsa)["custom.age"] == "30"
    response = fields.patch(motto, type="integer")
    assert problem(response, 422, "validation_error")["errors"][0]["code"] == "unsafe_type_change"


def test_multiple(fields: Fields) -> None:
    api = fields.api
    alias = fields.made(key="alias")
    ilsa = api.make("character", "Ilsa", fields={"custom.alias": "Ice"})
    fields.patched(alias, multiple=True)
    assert fields.values(ilsa)["custom.alias"] == ["Ice"]
    api.patch(api.get(ilsa["id"]).json(), fields={"custom.alias": ["Ice", "Snow"]})
    assert invalid(fields.patch(alias, multiple=False)) == ["multiple"]
    api.patch(api.get(ilsa["id"]).json(), fields={"custom.alias": ["Ice"]})
    fields.patched(alias, multiple=False)
    assert fields.values(ilsa)["custom.alias"] == "Ice"


def test_temporal_fields_and_turning_temporal_off(fields: Fields) -> None:
    api = fields.api
    world = api.make("dimension", "Aetheria")
    api.calendar(world["id"])
    timeline = world["ext"]["prime_timeline_id"]
    rank = fields.made(key="rank", type="integer", temporal=True)
    ilsa = api.make("character", "Ilsa", dimension_id=world["id"], fields={"custom.rank": 1})
    url = f"{api.base}/entities/{ilsa['id']}/facts"
    fact = api.client.post(url, json={"field_key": "custom.rank", "value": 2,
                                      "timeline_id": timeline})  # fmt: skip
    assert fact.status_code == 201, fact.json()
    assert fields.get(rank)["entities_with_values"] == 1
    assert invalid(fields.patch(rank, temporal=False)) == ["facts"]
    fields.patched(rank, temporal=False, facts="keep")
    assert len(api.client.get(url).json()["items"]) == 1
    fields.patched(rank, temporal=True)
    fields.patched(rank, temporal=False, facts="drop")
    assert api.client.get(url).json()["items"] == []
    assert fields.values(ilsa)["custom.rank"] == "1"


def test_delete_needs_delete_values_and_undo_restores(fields: Fields) -> None:
    api = fields.api
    world = api.make("dimension", "Aetheria")
    api.calendar(world["id"])
    crowned = fields.made(key="crowned", type="time_point")
    coronation = api.make("event", "Coronation", dimension_id=world["id"], ext={
        "start": {"anchor": {"kind": "absolute", "t": "500"}, "precision": "base"}})  # fmt: skip
    ref = {"type": "event", "id": coronation["id"], "slot": "start"}
    moment = {"anchor": {"kind": "relative", "ref": ref, "offset": {"kind": "base", "units": "0"}},
              "precision": "base"}  # fmt: skip
    ilsa = api.make("character", "Ilsa", dimension_id=world["id"],
                    fields={"custom.crowned": moment},
                    field_visibility={"custom.crowned": "private"})  # fmt: skip
    vault = api.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]

    def rows() -> dict[str, str | None]:
        with vault.sessions() as session:
            found = session.scalars(select(EntityTimeField).where(
                EntityTimeField.entity_id == ilsa["id"]))  # fmt: skip
            return {row.field_key: None if row.t is None else str(row.t) for row in found}

    # A time-point custom field propagates: it follows the event.
    assert rows() == {"custom.crowned": "500"}
    moved = api.patch(coronation, ext={"start": {"anchor": {"kind": "absolute", "t": "700"},
                                                 "precision": "base"}})  # fmt: skip
    assert moved.status_code == 200, moved.json()
    assert rows() == {"custom.crowned": "700"}
    conflict = problem(fields.delete(crowned), 409, "conflict")
    assert conflict["context"] == {"entities": 1}
    response = fields.delete(crowned, delete_values="true")
    assert response.status_code == 200, response.json()
    assert response.json()["affected"]["time_changed"] is True
    assert "custom.crowned" not in fields.registry_fields("character")
    entity = api.get(ilsa["id"]).json()
    assert entity["field_visibility"] == {}
    assert rows() == {}
    fields.undo_last()
    assert fields.values(ilsa)["custom.crowned"]["anchor"]["ref"]["id"] == coronation["id"]
    assert rows() == {"custom.crowned": "700"}
    assert api.get(ilsa["id"]).json()["field_visibility"] == {"custom.crowned": "private"}
    # Without values, a plain delete.
    empty = fields.made(key="empty")
    assert fields.delete(empty).status_code == 200
    problem(fields.client.get(f"{fields.base}/{empty['id']}"), 404, "not_found")


def test_default_visibility_and_readers(fields: Fields) -> None:
    api = fields.api
    fields.made(key="secret", default_visibility="private")
    ilsa = api.make("character", "Ilsa", fields={"custom.secret": "Spy"})
    assert fields.values(ilsa, as_reader="true") == {}
    assert fields.values(ilsa) == {"custom.secret": "Spy"}
    hits = api.client.get(f"{api.base}/search", params={"q": "Spy", "as_reader": "true"})
    assert hits.json()["items"] == []
    problem(fields.client.get(fields.base, params={"as_reader": "true"}), 404, "not_found")


def test_media_type_needs_the_media_module(fields: Fields) -> None:
    assert fields.create(key="portrait", type="media").status_code == 201
    response = fields.api.modules("media", enabled=False, cascade=True)
    assert response.status_code == 200, response.json()
    assert invalid(fields.create(key="banner", type="media")) == ["type"]
    assert "custom.portrait" not in fields.registry_fields("character")


def test_disabling_the_module_keeps_values(fields: Fields) -> None:
    api = fields.api
    fields.made()
    ilsa = api.make("character", "Ilsa", fields={"custom.title": "Queen"})
    assert api.modules("custom_fields", enabled=False).status_code == 200
    assert "custom.title" not in fields.registry_fields("character")
    assert fields.values(ilsa) == {}
    problem(fields.create(key="other"), 404, "module_disabled")
    renamed = api.patch(api.get(ilsa["id"]).json(), name="Ilsa II")
    assert renamed.status_code == 200, renamed.json()
    assert api.modules("custom_fields", enabled=True).status_code == 200
    assert fields.values(ilsa) == {"custom.title": "Queen"}
