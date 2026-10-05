from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lore.core.entities.models import entity_sort_name
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, invalid, new_app, problem
from tests.migration_harness import MigrationHarness


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with local_client(new_app(tmp_path), headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)


def entities(api: Api, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/entities", params=params)
    assert response.status_code == 200, response.json()
    page: dict[str, Any] = response.json()
    return page


def names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


def all_pages(api: Api, path: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        page = api.client.get(f"{api.base}{path}", params=query).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def tree(api: Api, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/tree", params=params)
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


# --- sort names -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ordered"),
    [
        ["apple", "Banana", "cherry"],
        ["Eagle", "Élan", "elk"],
        ["Chapter 2", "Chapter 10", "Chapter 100"],
        ["Chapter 007", "Chapter 8"],
        ["2 apples", "10 apples", "apple"],
        ["Zeta", "Æther"],  # Æ folds to "æ", after z (no decomposition)
    ],
)
def test_sort_names(ordered: list[str]) -> None:
    assert sorted(ordered, key=entity_sort_name) == ordered


def test_sort_name_examples() -> None:
    assert entity_sort_name("Élan 7") == "elan 0017"
    assert entity_sort_name("x0") == "x0010"
    assert entity_sort_name("x" + "9" * 1200).endswith("9" * 999)


def test_sort_name_backfill(migrations: MigrationHarness) -> None:
    migrations.upgrade("4170d09b94db")
    migrations.execute(
        "INSERT INTO entities (id, kind, name, slug, created_at, updated_at) VALUES "
        "('a', 'misc', 'Élan 10', 'e', '2026-10-04T00:00:00.000000+00:00', "
        "'2026-10-04T00:00:00.000000+00:00')"
    )
    migrations.upgrade()
    assert migrations.rows("SELECT sort_name FROM entities") == [("elan 00210",)]


# --- list -----------------------------------------------------------------------------------


def test_list_filters(api: Api) -> None:
    first, second = api.make("dimension", "First"), api.make("dimension", "Second")
    folder = api.make("misc", "Folder", dimension_id=first["id"], tags=["Red"])
    gadget = api.make("gadget", "Gizmo 10", dimension_id=first["id"], parent_id=folder["id"],
                      aliases=[{"alias": "Widget"}], tags=["Red", "Blue"])  # fmt: skip
    api.make("gadget", "gizmo 9", dimension_id=second["id"])
    api.make("gadget", "Anywhere")  # multiversal
    trashed = api.make("misc", "Old", dimension_id=first["id"])
    api.delete(trashed["id"])

    assert names(entities(api)) == [
        "Anywhere",
        "First",
        "Folder",
        "gizmo 9",
        "Gizmo 10",
        "Prime",
        "Prime",
        "Second",
    ]  # each dimension has its prime timeline
    assert names(entities(api, kind="gadget")) == ["Anywhere", "gizmo 9", "Gizmo 10"]
    assert names(entities(api, kind=["misc", "dimension"])) == ["First", "Folder", "Second"]
    assert names(entities(api, dimension=first["id"])) == [
        "Anywhere",
        "Folder",
        "Gizmo 10",
        "Prime",
    ]
    assert names(entities(api, dimension=first["id"], include_multiversal="false")) == [
        "Folder", "Gizmo 10", "Prime",
    ]  # fmt: skip
    assert names(entities(api, parent=folder["id"])) == ["Gizmo 10"]
    red, blue = (next(t["id"] for t in gadget["tags"] if t["name"] == n) for n in ("Red", "Blue"))
    assert names(entities(api, tag=red)) == ["Folder", "Gizmo 10"]
    assert names(entities(api, tag=[red, blue])) == ["Gizmo 10"]
    assert names(entities(api, q="giz")) == ["gizmo 9", "Gizmo 10"]
    assert names(entities(api, q="wid")) == ["Gizmo 10"]  # alias
    assert names(entities(api, q="%")) == []
    assert names(entities(api, include_trashed="true", kind="misc")) == ["Folder", "Old"]
    assert entities(api, kind="misc")["items"][0] == {
        key: folder[key]
        for key in ("id", "kind", "dimension_id", "parent_id", "name", "slug", "summary",
                    "fields", "visibility", "icon", "color", "sort_key", "revision",
                    "created_at", "updated_at", "deleted_at")
    }  # fmt: skip


def test_list_sorts(api: Api) -> None:
    for name in ("b", "c", "a"):
        api.make("misc", name)
    assert names(entities(api, sort="-name")) == ["c", "b", "a"]
    assert names(entities(api, sort="created")) == ["b", "c", "a"]
    assert names(entities(api, sort="-created")) == ["a", "c", "b"]
    b = entities(api, q="b")["items"][0]
    api.patch(b, summary="touched")
    assert names(entities(api, sort="-updated"))[0] == "b"
    assert names(entities(api, sort="updated"))[-1] == "b"
    c = entities(api, q="c")["items"][0]
    api.patch(c, sort_key="a0")
    assert names(entities(api, sort="sort_key")) == ["c", "a", "b"]
    problem(api.client.get(f"{api.base}/entities", params={"sort": "kind"}), 422,
            "validation_error")  # fmt: skip


def test_list_errors_and_disabled_kinds(api: Api) -> None:
    assert invalid(api.client.get(f"{api.base}/entities", params={"kind": "ghost"})) == ["kind"]
    problem(api.client.get(f"{api.base}/entities", params={"limit": 501}), 422, "validation_error")
    problem(api.client.get(f"{api.base}/entities", params={"dimension": "x"}), 422,
            "validation_error")  # fmt: skip
    api.make("beast", "Wolf")
    api.modules("extra", enabled=False)
    assert names(entities(api)) == []
    assert names(entities(api, kind="beast")) == []


@pytest.mark.parametrize("sort", ["name", "-name", "created", "-created", "updated", "sort_key"])
def test_pagination_is_stable_across_inserts(api: Api, sort: str) -> None:
    for index in range(7):
        api.make("misc", f"Item {index}", sort_key=f"k{index}" if index % 2 else None)
    expected = [item["name"] for item in all_pages(api, "/entities", sort=sort, limit=100)]
    first = entities(api, sort=sort, limit=3)
    # entities created meanwhile don't shift the pages already handed out
    api.make("misc", "AAA new", sort_key="a")
    api.make("misc", "zzz new")
    seen = names(first)
    cursor = first["next_cursor"]
    while cursor:
        page = entities(api, sort=sort, limit=3, cursor=cursor)
        seen += names(page)
        cursor = page["next_cursor"]
    old = [name for name in seen if not name.endswith(" new")]
    assert old == expected
    assert len(seen) == len(set(seen))


def test_bad_cursors(api: Api) -> None:
    api.make("misc", "a")
    api.make("misc", "b")
    cursor = entities(api, limit=1)["next_cursor"]
    for params in (
        {"cursor": "garbage!"},
        {"cursor": cursor, "sort": "created"},  # another sort
        {"cursor": "eyJzIjoibmFtZSIsInYiOlsieCJdfQ"},  # {"s":"name","v":["x"]}: too few values
    ):
        assert invalid(api.client.get(f"{api.base}/entities", params=params)) == ["cursor"]


# --- tree and children ----------------------------------------------------------------------


def test_tree_levels_counts_and_order(api: Api) -> None:
    dimension = api.make("dimension", "World")
    folder = api.make("misc", "Folder", dimension_id=dimension["id"])
    for name, sort_key in (("Gadget 10", None), ("Gadget 2", None), ("Last", "b"), ("First", "a")):
        api.make("gadget", name, dimension_id=dimension["id"], parent_id=folder["id"],
                 sort_key=sort_key)  # fmt: skip
    api.make("misc", "Sub", dimension_id=dimension["id"], parent_id=folder["id"])
    api.make("misc", "Elsewhere", dimension_id=api.make("dimension", "Other")["id"])

    roots = tree(api, dimension=dimension["id"])
    # the dimension itself isn't part of its tree
    assert [(n["name"], n["has_children"], n["child_counts"]) for n in roots] == [
        ("Folder", True, {"gadget": 4, "misc": 1}),
        ("Prime", False, {}),  # the dimension's prime timeline
    ]
    children = tree(api, dimension=dimension["id"], parent=folder["id"])
    # manual order first, then by name (numbers by value)
    assert [n["name"] for n in children] == ["First", "Last", "Gadget 2", "Gadget 10", "Sub"]
    assert children[0]["multiversal"] is False
    gadgets = tree(api, dimension=dimension["id"], parent=folder["id"], kind="gadget")
    assert len(gadgets) == 4
    assert tree(api, dimension=dimension["id"], kind="misc")[0]["child_counts"] == {"misc": 1}


def test_tree_multiversal_and_orphans(api: Api) -> None:
    first, second = api.make("dimension", "First"), api.make("dimension", "Second")
    everywhere = api.make("misc", "Everywhere")  # multiversal: in every dimension
    local = api.make("misc", "Local", dimension_id=second["id"], parent_id=everywhere["id"])
    folder = api.make("misc", "Folder", dimension_id=first["id"])
    orphan = api.make("gadget", "Orphan", dimension_id=first["id"], parent_id=folder["id"])
    nested = api.make("gadget", "Nested", dimension_id=first["id"], parent_id=orphan["id"])

    roots = {n["name"]: n for n in tree(api, dimension=first["id"])}
    assert set(roots) == {"Everywhere", "Folder", "Prime"}
    assert roots["Everywhere"]["multiversal"] is True
    assert roots["Everywhere"]["has_children"] is False  # "Local" is in the other dimension
    assert [n["name"] for n in tree(api, dimension=second["id"], parent=everywhere["id"])] == [
        local["name"]
    ]
    # kind sections: a gadget whose parent is filtered out is a root of the gadget section
    assert [n["name"] for n in tree(api, dimension=first["id"], kind="gadget")] == ["Orphan"]
    # trashed parent: its children become roots
    api.delete(folder["id"])
    assert {n["name"] for n in tree(api, dimension=first["id"])} == {
        "Everywhere",
        "Orphan",
        "Prime",
    }
    assert tree(api, dimension=first["id"], parent=orphan["id"])[0]["id"] == nested["id"]


def test_tree_hides_disabled_kinds_and_their_parents(api: Api) -> None:
    beast = api.make("beast", "Wolf")
    folder = api.make("misc", "Folder")
    api.make("misc", "Pup", parent_id=folder["id"])
    api.make("misc", "Den")
    api.modules("extra", enabled=False)
    assert [n["name"] for n in tree(api)] == ["Den", "Folder"]
    assert beast["id"] not in {n["id"] for n in tree(api)}


def test_tree_pagination(api: Api) -> None:
    for index in range(5):
        api.make("misc", f"N{index}", sort_key=f"k{index}" if index < 2 else None)
    items = all_pages(api, "/tree", limit=2)
    assert [n["name"] for n in items] == ["N0", "N1", "N2", "N3", "N4"]


def test_children(api: Api) -> None:
    first, second = api.make("dimension", "First"), api.make("dimension", "Second")
    folder = api.make("misc", "Folder")
    for name, dimension in (("B", first), ("A", second)):
        api.make("gadget", name, dimension_id=dimension["id"], parent_id=folder["id"])
    sub = api.make("misc", "C", parent_id=folder["id"])
    api.make("misc", "Leaf", parent_id=sub["id"])
    gone = api.make("misc", "Gone", parent_id=folder["id"])
    api.delete(gone["id"])

    response = api.client.get(f"{api.base}/entities/{folder['id']}/children")
    nodes = response.json()["items"]
    assert [(n["name"], n["child_counts"]) for n in nodes] == [
        ("A", {}), ("B", {}), ("C", {"misc": 1}),
    ]  # fmt: skip
    only = api.client.get(f"{api.base}/entities/{folder['id']}/children", params={"kind": "misc"})
    assert [n["name"] for n in only.json()["items"]] == ["C"]
    missing = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    problem(api.client.get(f"{api.base}/entities/{missing}/children"), 404, "not_found")


# --- trash ----------------------------------------------------------------------------------


def test_trash(api: Api) -> None:
    parent = api.make("misc", "Parent")
    api.make("misc", "Kid 1", parent_id=parent["id"])
    kid = api.make("misc", "Kid 2", parent_id=parent["id"])
    alone = api.make("misc", "Alone")
    api.delete(parent["id"])
    api.delete(alone["id"])
    api.delete(kid["id"])
    beast = api.make("beast")
    api.delete(beast["id"])

    trash = api.client.get(f"{api.base}/trash").json()
    assert [(i["name"], i["orphan_count"]) for i in trash["items"]] == [
        ("Thing", 0), ("Kid 2", 0), ("Alone", 0), ("Parent", 1),
    ]  # fmt: skip
    assert trash["items"][3]["deleted_at"] is not None
    paged = all_pages(api, "/trash", limit=1)
    assert [i["name"] for i in paged] == ["Thing", "Kid 2", "Alone", "Parent"]
    api.modules("extra", enabled=False)
    assert len(api.client.get(f"{api.base}/trash").json()["items"]) == 3


# --- field values ---------------------------------------------------------------------------


def suggestions(api: Api, **params: Any) -> Any:
    return api.client.get(f"{api.base}/entities/field-values", params=params)


def test_field_values(api: Api) -> None:
    for text in ("Magic", "magic", "Mágic", "Machines", "Machines", "Science", "  ", "Other"):
        api.make("gadget", fields={"text": text})
    api.make("gadget")  # no value
    gone = api.make("gadget", fields={"text": "Other"})
    api.delete(gone["id"])
    api.make("misc")

    items = suggestions(api, kind="gadget", field="text").json()["items"]
    assert items == [
        {"value": "Magic", "count": 3},  # merged; ties between spellings: by name order
        {"value": "Machines", "count": 2},
        {"value": "Other", "count": 1},  # the trashed entity doesn't count
        {"value": "Science", "count": 1},
    ]
    assert suggestions(api, kind="gadget", field="text", q="MA").json()["items"] == items[:2]
    assert suggestions(api, kind="gadget", field="text", q="mag").json()["items"] == items[:1]
    assert suggestions(api, kind="gadget", field="text", limit=1).json()["items"] == items[:1]


def test_field_values_spelling_and_multiple(api: Api) -> None:
    for text in ("dragon", "Dragon", "Dragon"):
        api.make("gadget", fields={"text": text})
    assert suggestions(api, kind="gadget", field="text").json()["items"] == [
        {"value": "Dragon", "count": 3}  # the most used spelling
    ]
    api.make("gadget", fields={"nicknames": ["Bob", "Rob"]})
    api.make("gadget", fields={"nicknames": ["bob"]})
    assert suggestions(api, kind="gadget", field="nicknames").json()["items"] == [
        {"value": "Bob", "count": 2},
        {"value": "Rob", "count": 1},
    ]


def test_field_values_errors(api: Api) -> None:
    assert invalid(suggestions(api, kind="ghost", field="text")) == ["kind"]
    assert invalid(suggestions(api, kind="gadget", field="boolean")) == ["field"]
    assert invalid(suggestions(api, kind="gadget", field="nope")) == ["field"]
    problem(suggestions(api, kind="gadget"), 422, "validation_error")
    api.modules("extra", enabled=False)
    problem(suggestions(api, kind="beast", field="x"), 404, "module_disabled")


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    base = "/api/v1/vaults/{vault_id}"
    assert paths[f"{base}/entities"]["get"]["operationId"] == "entities_list"
    assert paths[f"{base}/entities/field-values"]["get"]["operationId"] == "entities_field_values"
    assert paths[f"{base}/entities/{{entity_id}}/children"]["get"]["operationId"] == (
        "entities_children"
    )
    assert paths[f"{base}/tree"]["get"]["operationId"] == "tree_get"
    assert paths[f"{base}/trash"]["get"]["operationId"] == "trash_list"
