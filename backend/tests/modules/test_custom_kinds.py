"""Custom kinds (``docs/modules/custom_fields.md``): authors' kinds served with the registry and
treated like built-in kinds by the entity APIs, search, graph and consistency; archive, delete
only when unused, and converting entities between kinds."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, invalid, make_client, problem
from tests.entity_modules import with_real_modules


class Kinds:
    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.client = api.client
        self.base = f"{api.base}/m/custom_fields"

    def create(self, key: str = "artifact", **body: Any) -> Any:
        body.setdefault("label", key.title())
        body.setdefault("plural", f"{key.title()}s")
        return self.client.post(f"{self.base}/kinds", json={"key": key, **body})

    def made(self, key: str = "artifact", **body: Any) -> dict[str, Any]:
        response = self.create(key, **body)
        assert response.status_code == 201, response.json()
        kind: dict[str, Any] = response.json()["kind"]
        return kind

    def get(self, key: str) -> dict[str, Any]:
        response = self.client.get(f"{self.base}/kinds/{key}")
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()
        return found

    def patch(self, key: str, **body: Any) -> Any:
        body.setdefault("revision", self.get(key)["revision"])
        return self.client.patch(f"{self.base}/kinds/{key}", json=body)

    def convert(self, entities: list[dict[str, Any]], to_kind: str, **body: Any) -> Any:
        ids = [entity["id"] for entity in entities]
        return self.client.post(f"{self.base}/convert-kind",
                                json={"entity_ids": ids, "to_kind": to_kind, **body})  # fmt: skip

    def field(self, key: str, type_key: str, kind: str = "custom.artifact") -> Any:
        body = {"kind_key": kind, "key": key, "label": key.title(), "type": type_key}
        return self.client.post(f"{self.base}/fields", json=body)

    def registry_kinds(self) -> dict[str, dict[str, Any]]:
        registry = self.client.get(f"{self.api.base}/registry").json()
        return {kind["key"]: kind for kind in registry["kinds"]}

    def search(self, q: str) -> list[str]:
        response = self.client.get(f"{self.api.base}/search", params={"q": q})
        assert response.status_code == 200, response.json()
        return [hit["entity_id"] for hit in response.json()["items"]]

    def listed(self, kind: str) -> list[str]:
        response = self.client.get(f"{self.api.base}/entities", params={"kind": kind})
        assert response.status_code == 200, response.json()
        return [item["name"] for item in response.json()["items"]]


@pytest.fixture
def kinds(tmp_path: Path) -> Iterator[Kinds]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield Kinds(LinkApi(client))


def test_a_custom_kind_works_like_a_built_in_one(kinds: Kinds) -> None:
    api = kinds.api
    created = kinds.made(icon="sword", color="#aa3300", description="Things of power",
                         allowed_parents=["custom.artifact", "location"],
                         capabilities={"can_have_worldline": True},
                         default_visibility="spoiler")  # fmt: skip
    assert (created["key"], created["entities"]) == ("custom.artifact", 0)
    shown = kinds.registry_kinds()["custom.artifact"]
    assert (shown["module"], shown["label"], shown["icon"]) == (
        "custom_fields",
        "Artifact",
        "sword",
    )
    assert shown["capabilities"]["can_have_worldline"] is True
    assert shown["capabilities"]["is_system"] is False
    assert shown["default_visibility"] == "spoiler"

    # Custom fields on the kind; entities of it validate, list, search and nest.
    field = kinds.field("power", "integer")
    assert field.status_code == 201, field.json()
    vault = api.make("location", "Vault")
    sword = api.make("custom.artifact", "Dawnbringer", parent_id=vault["id"],
                     fields={"custom.power": "9"})  # fmt: skip
    assert (sword["visibility"], sword["fields"]) == ("spoiler", {"custom.power": "9"})
    hilt = api.make("custom.artifact", "Hilt", parent_id=sword["id"], visibility="public")
    assert hilt["visibility"] == "public"
    assert invalid(api.create("custom.artifact", "X", fields={"custom.power": "much"})) == [
        "fields.custom.power"
    ]
    assert kinds.listed("custom.artifact") == ["Dawnbringer", "Hilt"]
    assert kinds.search("Dawnbringer") == [sword["id"]]
    assert kinds.get("custom.artifact")["entities"] == 2
    # Links of any-kind link types; the graph shows the entity.
    ilsa = api.make("character", "Ilsa")
    api.made_link("core.related", ilsa, sword)
    graph = kinds.client.get(f"{api.base}/m/graph/graph").json()
    assert sword["id"] in {node["id"] for node in graph["nodes"]}

    # Keys and parents are checked.
    assert invalid(kinds.create("artifact")) == ["key"]
    assert invalid(kinds.create("spell", allowed_parents=["nothing"])) == ["allowed_parents.0"]
    problem(kinds.patch("custom.artifact", label="Relic", revision=99), 409, "conflict")
    assert invalid(kinds.patch("custom.artifact", capabilities={"can_be_multiversal": False})) == [
        "capabilities.can_be_multiversal"
    ]


def test_archive_hides_the_kind_and_its_entities(kinds: Kinds) -> None:
    api = kinds.api
    kinds.made()
    sword = api.make("custom.artifact", "Dawnbringer")
    archived = kinds.patch("custom.artifact", archived=True)
    assert archived.status_code == 200, archived.json()
    assert archived.json()["affected"]["entities"] == [sword["id"]]
    assert "custom.artifact" not in kinds.registry_kinds()
    assert api.get(sword["id"]).status_code in (404, 409)
    assert kinds.search("Dawnbringer") == []
    assert invalid(api.create("custom.artifact", "Other")) == ["kind"]
    assert kinds.get("custom.artifact")["archived"] is True
    kinds.patch("custom.artifact", archived=False)
    assert api.get(sword["id"]).status_code == 200
    assert kinds.search("Dawnbringer") == [sword["id"]]


def test_delete_only_when_unused(kinds: Kinds) -> None:
    api = kinds.api
    kinds.made()
    kinds.field("power", "integer")
    sword = api.make("custom.artifact", "Dawnbringer")
    assert api.delete(sword["id"]).status_code == 200  # the trash still counts
    conflict = problem(kinds.client.delete(f"{kinds.base}/kinds/custom.artifact"), 409, "conflict")
    assert conflict["context"] == {"entities": 1}
    assert api.delete(sword["id"], purge=True).status_code in (200, 204)
    deleted = kinds.client.delete(f"{kinds.base}/kinds/custom.artifact")
    assert deleted.status_code == 200, deleted.json()
    problem(kinds.client.get(f"{kinds.base}/kinds/custom.artifact"), 404, "not_found")
    assert (
        kinds.client.get(f"{kinds.base}/fields", params={"kind": "custom.artifact"}).json()["items"]
        == []
    )


def test_convert_to_misc_and_back(kinds: Kinds) -> None:
    api = kinds.api
    world = api.make("dimension", "Aetheria")
    api.calendar(world["id"])
    timeline = world["ext"]["prime_timeline_id"]
    kinds.made()
    for key, label, kind, temporal in (
        ("power", "Power", "custom.artifact", True),
        ("origin", "Origin", "custom.artifact", False),
    ):
        response = kinds.client.post(f"{kinds.base}/fields", json={
            "kind_key": kind, "key": key, "label": label, "type": "text",
            "temporal": temporal})  # fmt: skip
        assert response.status_code == 201, response.json()
    sword = api.make("custom.artifact", "Dawnbringer", dimension_id=world["id"],
                     fields={"custom.power": "great", "custom.origin": "the sun"},
                     field_visibility={"custom.origin": "private"})  # fmt: skip
    fact = api.client.post(f"{api.base}/entities/{sword['id']}/facts", json={
        "field_key": "custom.power", "value": "waning", "timeline_id": timeline})  # fmt: skip
    assert fact.status_code == 201, fact.json()

    # To misc: the origin becomes the category; the power (and its fact) stay stored, hidden.
    converted = kinds.convert([sword], "misc", field_mapping={"custom.origin": "category"})
    assert converted.status_code == 200, converted.json()
    entity = api.get(sword["id"]).json()
    assert (entity["kind"], entity["fields"]) == ("misc", {"category": "the sun"})
    assert entity["field_visibility"] == {"category": "private"}
    assert kinds.listed("misc") == ["Dawnbringer"]
    assert kinds.get("custom.artifact")["entities"] == 0

    # And back: the power returns with its fact.
    back = kinds.convert([sword], "custom.artifact", field_mapping={"category": "custom.origin"})
    assert back.status_code == 200, back.json()
    entity = api.get(sword["id"]).json()
    assert (entity["kind"], entity["fields"]) == (
        "custom.artifact", {"custom.power": "great", "custom.origin": "the sun"},
    )  # fmt: skip
    facts = api.client.get(f"{api.base}/entities/{sword['id']}/facts").json()["items"]
    assert [(f["field_key"], f["value"]) for f in facts] == [("custom.power", "waning")]

    # One changeset: undo returns it to misc.
    last = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    assert last["summary"] == "Converted 1 entity to Artifacts"
    assert api.client.post(f"{api.base}/changes/{last['id']}/revert").status_code == 200
    assert api.get(sword["id"]).json()["kind"] == "misc"

    # What can't be converted.
    event = api.make("event", "Battle", dimension_id=world["id"])
    assert invalid(kinds.convert([event], "misc")) == ["entity_ids.0"]
    assert invalid(kinds.convert([sword], "event")) == ["to_kind"]
    assert invalid(kinds.convert([sword], "custom.nothing")) == ["to_kind"]
    assert invalid(kinds.convert([sword], "custom.artifact",
                                 field_mapping={"category": "custom.missing"})) == [
        "field_mapping.category"
    ]  # fmt: skip
    # Facts must land on a temporal field.
    back = kinds.convert([sword], "custom.artifact",
                         field_mapping={"custom.power": "custom.origin"})  # fmt: skip
    assert invalid(back) == ["field_mapping.custom.power"]


def test_disabling_the_module_hides_custom_kinds(kinds: Kinds) -> None:
    api = kinds.api
    kinds.made()
    sword = api.make("custom.artifact", "Dawnbringer")
    assert api.modules("custom_fields", enabled=False).status_code == 200
    assert "custom.artifact" not in kinds.registry_kinds()
    assert kinds.search("Dawnbringer") == []
    assert api.modules("custom_fields", enabled=True).status_code == 200
    assert api.get(sword["id"]).status_code == 200
    assert kinds.search("Dawnbringer") == [sword["id"]]


def test_readers(kinds: Kinds) -> None:
    kinds.made()
    problem(kinds.client.get(f"{kinds.base}/kinds", params={"as_reader": "true"}), 404,
            "not_found")  # fmt: skip
