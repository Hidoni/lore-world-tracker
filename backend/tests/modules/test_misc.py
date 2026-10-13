"""The misc module (``docs/modules/misc.md``): the ``misc`` kind, its ``category`` field and its
role as the parent of entities of any kind."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lore.core.registry import CORE_KINDS
from lore.modules import ALL_MODULES
from tests.entity_api import Api, make_client, problem


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    with make_client(tmp_path) as client:
        yield Api(client)


def tree(api: Api, **params: Any) -> list[str]:
    response = api.client.get(f"{api.base}/tree", params=params)
    assert response.status_code == 200, response.json()
    return [node["name"] for node in response.json()["items"]]


def test_every_non_system_kind_can_be_a_child_of_a_misc_entry() -> None:
    kinds = [*CORE_KINDS, *(kind for module in ALL_MODULES for kind in module.kinds)]
    missing = [
        kind.key
        for kind in kinds
        if not kind.capabilities.is_system and "misc" not in kind.allowed_parents
    ]
    assert missing == []


def test_the_misc_kind(api: Api) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    misc = next(kind for kind in registry["kinds"] if kind["key"] == "misc")
    assert (misc["label"], misc["plural"], misc["icon"]) == ("Misc entry", "Misc entries", "shapes")
    assert [field["key"] for field in misc["fields"]] == ["category"]
    module = next(module for module in registry["modules"] if module["id"] == "misc")
    assert module["enabled"] is True


def test_a_misc_entry_is_the_parent_of_any_kind(api: Api) -> None:
    dimension = api.make("dimension", "Aetheria")
    api.calendar(dimension["id"])
    topic = api.make("misc", "Time Travel", fields={"category": "Concept"})
    paradox = api.make("misc", "Paradoxes", parent_id=topic["id"])
    machine = api.make("gadget", "Chronosphere", parent_id=topic["id"])
    relic = api.make(
        "relic",
        "Hourglass",
        dimension_id=dimension["id"],
        parent_id=topic["id"],
        fields={"origin": "x"},
    )
    beast = api.make("beast", "Time Hound", parent_id=topic["id"])
    jump = api.make("event", "First Jump", dimension_id=dimension["id"], parent_id=topic["id"])
    assert {e["parent_id"] for e in (paradox, machine, relic, beast, jump)} == {topic["id"]}

    children = api.client.get(f"{api.base}/entities/{topic['id']}/children").json()["items"]
    assert sorted((child["kind"], child["name"]) for child in children) == [
        ("beast", "Time Hound"),
        ("event", "First Jump"),
        ("gadget", "Chronosphere"),
        ("misc", "Paradoxes"),
        ("relic", "Hourglass"),
    ]
    # Only misc entries take children of every kind.
    refused = api.create("gadget", "Cog", parent_id=beast["id"])
    problem(refused, 422, "parent_not_allowed")


def test_categories_are_suggested_from_existing_values(api: Api) -> None:
    for name, category in (("A", "Concept"), ("B", "Concept"), ("C", "Technology"), ("D", "Magic")):
        api.make("misc", name, fields={"category": category})
    response = api.client.get(
        f"{api.base}/entities/field-values", params={"kind": "misc", "field": "category"}
    )
    values = [item["value"] for item in response.json()["items"]]
    assert values[0] == "Concept"  # the most used first
    assert sorted(values) == ["Concept", "Magic", "Technology"]


def test_disabling_and_re_enabling_keeps_everything(api: Api) -> None:
    topic = api.make("misc", "Time Travel", fields={"category": "Concept"})
    machine = api.make("gadget", "Chronosphere", parent_id=topic["id"])
    assert tree(api) == ["Time Travel"]

    assert api.modules("misc", enabled=False).status_code == 200
    problem(api.get(topic["id"]), 404, "module_disabled")
    problem(api.create("misc", "Another"), 404, "module_disabled")
    # Children of hidden misc entries show as roots.
    assert tree(api) == ["Chronosphere"]
    assert api.get(machine["id"]).status_code == 200

    assert api.modules("misc", enabled=True).status_code == 200
    back = api.get(topic["id"]).json()
    assert (back["name"], back["fields"]) == ("Time Travel", {"category": "Concept"})
    assert tree(api) == ["Time Travel"]
    assert tree(api, parent=topic["id"]) == ["Chronosphere"]


def test_the_real_modules_serve_misc_entries(tmp_path: Path) -> None:
    with make_client(tmp_path, modules=tuple(ALL_MODULES)) as client:
        api = Api(client)
        topic = api.make("misc", "Time Travel", fields={"category": "Concept"})
        assert api.make("misc", "Paradoxes", parent_id=topic["id"])["parent_id"] == topic["id"]


def test_the_tree_groups_by_category(api: Api) -> None:
    api.make("misc", "Time Travel", fields={"category": " Concept "})
    api.make("misc", "Loose end")
    api.make(
        "misc",
        "Secret",
        fields={"category": "Cabal"},
        field_visibility={"category": "private"},
    )
    response = api.client.get(f"{api.base}/tree", params={"kind": "misc", "group_by": "category"})
    groups = {node["name"]: node["group"] for node in response.json()["items"]}
    # Authors see every category; readers' leak tests cover hidden ones.
    assert groups == {"Loose end": None, "Secret": "Cabal", "Time Travel": "Concept"}
    plain = api.client.get(f"{api.base}/tree", params={"kind": "misc"}).json()["items"]
    assert {node["group"] for node in plain} == {None}

    for params, path in (
        ({"group_by": "category"}, "group_by"),
        ({"kind": ["misc", "gadget"], "group_by": "category"}, "group_by"),
        ({"kind": "misc", "group_by": "nope"}, "group_by"),
    ):
        refused = api.client.get(f"{api.base}/tree", params=params)
        body = problem(refused, 422, "validation_error")
        assert [error["path"] for error in body["errors"]] == [path]
