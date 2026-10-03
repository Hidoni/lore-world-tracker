from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import local_client
from tests.entity_api import HEADERS, LinkApi, invalid, make_client, new_app, problem

POINT = {"anchor": {"kind": "absolute", "t": "10"}, "precision": "base"}
LATER = {"anchor": {"kind": "absolute", "t": "20"}, "precision": "base"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with local_client(new_app(tmp_path), headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> LinkApi:
    return LinkApi(client)


def summary(items: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(item["label"], item["direction"], item["other"]["name"]) for item in items]


# --- create and list ------------------------------------------------------------------------


def test_create_and_list(api: LinkApi) -> None:
    owner = api.make("misc", "Guild")
    gadget = api.make("gadget", "Engine")
    response = api.link("world.owns", owner, gadget, role="founder", visibility="spoiler")
    assert response.status_code == 201
    created = response.json()
    link = created["link"]
    assert (link["source_id"], link["target_id"], link["role"], link["visibility"]) == (
        owner["id"],
        gadget["id"],
        "founder",
        "spoiler",
    )
    assert (link["timeline_id"], link["valid_from"], link["revision"]) == (None, None, 1)
    assert created["affected"] == {
        "entities": [owner["id"], gadget["id"]],
        "dimensions": [],
        "time_changed": False,
        "search_changed": False,
    }
    assert summary(api.links_of(owner)) == [("owns", "out", "Engine")]
    assert summary(api.links_of(gadget)) == [("owned by", "in", "Guild")]
    assert api.links_of(gadget)[0]["link"] == link
    assert api.links_of(gadget, direction="out") == []
    assert len(api.links_of(gadget, direction="in")) == 1


def test_entity_links_order_and_filters(api: LinkApi) -> None:
    hub = api.make("misc", "Hub")
    names = ["Gadget 10", "Gadget 2", "Manual"]
    for name in names:
        gadget = api.make("gadget", name)
        api.made_link("core.related", hub, gadget, sort_key="a" if name == "Manual" else None)
    api.made_link("world.ally", hub, api.make("misc", "Friend"))
    assert summary(api.links_of(hub)) == [
        ("related to", "both", "Manual"),
        ("related to", "both", "Gadget 2"),
        ("related to", "both", "Gadget 10"),
        ("allied with", "both", "Friend"),
    ]  # by type key (core.related < world.ally), manual order first, then names
    related = [item["other"]["name"] for item in api.links_of(hub, type="core.related")]
    assert related == ["Manual", "Gadget 2", "Gadget 10"]
    assert len(api.links_of(hub, type=["core.related", "world.ally"])) == 4
    assert len(api.links_of(hub, direction="in")) == 4  # symmetric links count both ways


def test_hidden_links(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    beast = api.make("beast", "Wolf")
    link = api.made_link("core.related", a, b)
    api.made_link("extra.hunts", beast, a)
    assert len(api.links_of(a)) == 2
    api.modules("extra", enabled=False)  # the type's module and the other end disappear
    assert [i["other"]["name"] for i in api.links_of(a)] == ["B"]
    problem(api.link("extra.hunts", beast, a), 404, "module_disabled")
    api.modules("extra", enabled=True)
    api.delete(b["id"])  # links to trashed entities are hidden by default
    assert [i["other"]["name"] for i in api.links_of(a)] == ["Wolf"]
    shown = api.links_of(a, include_trashed="true")
    assert {i["other"]["name"] for i in shown} == {"Wolf", "B"}
    assert next(i for i in shown if i["link"]["id"] == link["id"])["other"]["deleted_at"]
    api.restore(b["id"])
    trashed = api.delete_link(link["id"])
    assert trashed.status_code == 200
    assert trashed.json()["link"]["deleted_at"] is not None
    assert api.delete_link(link["id"]).status_code == 200  # idempotent
    assert [i["other"]["name"] for i in api.links_of(a, include_trashed="true")] == ["Wolf"]
    problem(api.patch_link(trashed.json()["link"], role="x"), 409, "conflict")


def test_entity_links_errors(api: LinkApi) -> None:
    missing = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    problem(api.client.get(f"{api.base}/entities/{missing}/links"), 404, "not_found")
    beast = api.make("beast")
    api.modules("extra", enabled=False)
    problem(api.client.get(f"{api.base}/entities/{beast['id']}/links"), 404, "module_disabled")


# --- validation -----------------------------------------------------------------------------


def test_kind_and_endpoint_rules(api: LinkApi) -> None:
    misc, gadget = api.make("misc"), api.make("gadget")
    body = problem(api.link("world.owns", gadget, misc), 422, "link_type_not_allowed")
    assert "can't connect" in body["detail"]
    problem(api.link("world.ally", misc, gadget), 422, "link_type_not_allowed")
    assert api.link("core.related", gadget, misc).status_code == 201  # any kind
    assert invalid(api.link("core.related", misc, misc)) == ["target_id"]  # no self-links
    assert invalid(api.link("world.nope", misc, gadget)) == ["link_type"]
    problem(api.link("world.old", misc, gadget), 422, "link_type_not_allowed")  # archived
    api.delete(gadget["id"])
    assert invalid(api.link("core.related", misc, gadget)) == ["target_id"]
    ghost = {"id": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"}
    assert invalid(api.link("core.related", ghost, misc)) == ["source_id"]
    problem(api.link("core.related", misc, {"id": "x"}), 422, "validation_error")


def test_symmetric_links_are_stored_once(api: LinkApi) -> None:
    first, second = api.make("misc", "First"), api.make("misc", "Second")
    low, high = sorted([first, second], key=lambda e: e["id"])
    link = api.made_link("world.ally", high, low)
    assert (link["source_id"], link["target_id"]) == (low["id"], high["id"])
    # per pair (timeless): the other direction is the same pair
    body = problem(api.link("world.ally", low, high), 409, "conflict")
    assert body["context"] == {"links": [link["id"]]}
    assert summary(api.links_of(low)) == [("allied with", "both", high["name"])]
    assert summary(api.links_of(high)) == [("allied with", "both", low["name"])]


def test_uniqueness(api: LinkApi) -> None:
    owner, other = api.make("misc", "Owner"), api.make("misc", "Other")
    gadget = api.make("gadget")
    timeline = api.timeline()
    api.made_link("world.owns", owner, gadget, timeline_id=timeline["id"], valid_from=POINT)
    # per_pair counts every link, temporal ones too
    problem(api.link("world.owns", owner, gadget), 409, "conflict")
    # per_pair_per_period: timeless links are unique, links with bounds are accepted (#102)
    a, b = api.make("misc", "A"), api.make("misc", "B")
    api.made_link("world.ally", a, b)
    problem(api.link("world.ally", a, b), 409, "conflict")
    for bound in (POINT, LATER):
        api.made_link("world.ally", a, b, timeline_id=timeline["id"], valid_from=bound)
    # a trashed link doesn't count
    owned = api.links_of(gadget)[0]["link"]
    api.delete_link(owned["id"])
    api.made_link("world.owns", other, gadget)


def test_cardinality_counts_timeless_links_only(api: LinkApi) -> None:
    owner, rival = api.make("misc", "Owner"), api.make("misc", "Rival")
    gadget = api.make("gadget")
    api.made_link("world.owns", owner, gadget)
    body = problem(api.link("world.owns", rival, gadget), 409, "conflict")
    assert body["context"] == {"limit": "max_sources_per_target", "max": 1}
    timeline = api.timeline()
    api.made_link("world.owns", rival, gadget, timeline_id=timeline["id"], valid_from=POINT)
    # symmetric max: links on either side count
    hub = api.make("misc", "Hub")
    for name in ("X", "Y"):
        api.made_link("world.ally", api.make("misc", name), hub)
    problem(api.link("world.ally", hub, api.make("misc", "Z")), 409, "conflict")


def test_validity_rules(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    timeline = api.timeline()
    assert invalid(
        api.link(
            "world.rates", a, b, data={"stars": 1}, timeline_id=timeline["id"], valid_from=POINT
        )
    ) == ["valid_from"]
    assert invalid(api.link("world.reigns", a, b)) == ["valid_from"]
    assert invalid(api.link("core.related", a, b, valid_to=POINT)) == ["timeline_id"]
    assert invalid(api.link("core.related", a, b, timeline_id=timeline["id"])) == ["timeline_id"]
    assert invalid(api.link("core.related", a, b, timeline_id=a["id"], valid_from=POINT)) == [
        "timeline_id"
    ]
    problem(
        api.link(
            "core.related",
            a,
            b,
            timeline_id=timeline["id"],
            valid_from={"anchor": {"kind": "absolute", "t": "-1"}, "precision": "base"},
        ),
        422,
        "validation_error",
    )
    link = api.made_link("world.reigns", a, b, timeline_id=timeline["id"], valid_to=LATER)
    assert link["valid_to"] == {**LATER, "approximate": False}
    assert link["valid_from"] is None
    assert link["time_status"] is None  # resolved by #102
    api.delete(timeline["id"])
    assert invalid(
        api.link("world.reigns", b, a, timeline_id=timeline["id"], valid_from=POINT)
    ) == ["timeline_id"]


def test_data_schema(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    response = api.link("world.rates", a, b, data={"stars": 0})
    assert problem(response, 422, "validation_error")["errors"] == [
        {
            "path": "data.stars",
            "code": "invalid_value",
            "message": "0 is less than the minimum of 1",
        },
    ]
    assert invalid(api.link("world.rates", a, b)) == ["data"]
    assert api.made_link("world.rates", a, b, data={"stars": 5})["data"] == {"stars": 5}


# --- update ---------------------------------------------------------------------------------


def test_update(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    timeline = api.timeline()
    link = api.made_link("core.related", a, b, role="old")
    response = api.patch_link(
        link,
        role="new",
        data={"x": 1},
        visibility="private",
        timeline_id=timeline["id"],
        valid_from=POINT,
    )
    assert response.status_code == 200
    updated = response.json()["link"]
    assert (updated["role"], updated["data"], updated["visibility"], updated["revision"]) == (
        "new",
        {"x": 1},
        "private",
        2,
    )
    assert updated["valid_from"]["anchor"] == POINT["anchor"]
    stale = problem(api.patch_link(link, role="x"), 409, "revision_conflict")
    assert stale["context"]["current"]["role"] == "new"
    timeless = api.patch_link(updated, timeline_id=None, valid_from=None).json()["link"]
    assert (timeless["timeline_id"], timeless["valid_from"]) == (None, None)
    assert invalid(api.patch_link(timeless, valid_to=LATER)) == ["timeline_id"]
    problem(api.patch_link(timeless, visibility=None), 422, "validation_error")
    problem(api.patch_link(timeless, data=None), 422, "validation_error")
    problem(api.patch_link(timeless, source_id=b["id"]), 422, "validation_error")  # fixed ends
    same = api.patch_link(timeless).json()["link"]
    assert same["revision"] == timeless["revision"]


def test_update_rechecks_limits(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    timeline = api.timeline()
    api.made_link("world.ally", a, b)
    period = api.made_link("world.ally", a, b, timeline_id=timeline["id"], valid_from=POINT)
    problem(api.patch_link(period, timeline_id=None, valid_from=None), 409, "conflict")


def test_unknown_and_unavailable_links(api: LinkApi) -> None:
    missing = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    problem(api.delete_link(missing), 404, "not_found")
    problem(api.patch_link({"id": missing, "revision": 1}), 404, "not_found")
    link = api.made_link("extra.hunts", api.make("beast"), api.make("misc"))
    api.modules("extra", enabled=False)
    problem(api.patch_link(link, role="x"), 404, "module_disabled")
    problem(api.delete_link(link["id"]), 404, "module_disabled")


# --- inline links on entity writes ----------------------------------------------------------


def test_links_on_entity_create(api: LinkApi) -> None:
    owner = api.make("misc", "Owner")
    friend = api.make("misc", "Friend")
    response = api.create(
        "misc",
        "New",
        links_add=[
            {"link_type": "core.related", "target_id": friend["id"], "role": "pal"},
            {"link_type": "world.ally", "source_id": owner["id"]},
        ],
    )
    assert response.status_code == 201
    entity = response.json()["entity"]
    assert response.json()["affected"]["entities"] == [entity["id"], friend["id"], owner["id"]]
    assert {(i["label"], i["other"]["name"]) for i in api.links_of({"id": entity["id"]})} == {
        ("related to", "Friend"),
        ("allied with", "Owner"),
    }

    # one transaction: a bad link rolls back the entity too
    failed = api.create(
        "misc",
        "Doomed",
        links_add=[
            {"link_type": "core.related", "target_id": friend["id"]},
            {"link_type": "world.owns", "target_id": friend["id"]},
        ],
    )
    body = problem(failed, 422, "link_type_not_allowed")
    assert body["errors"][0]["path"] == "links_add.1"
    names = {i["other"]["name"] for i in api.links_of(friend)}
    assert names == {"New"}
    paths = invalid(
        api.create(
            "misc",
            links_add=[
                {"link_type": "core.related", "target_id": friend["id"], "source_id": owner["id"]}
            ],
        )
    )
    assert paths == ["links_add.0"]
    paths = invalid(
        api.create(
            "misc",
            links_add=[
                {"link_type": "world.rates", "target_id": friend["id"], "data": {"stars": 0}}
            ],
        )
    )
    assert paths == ["links_add.0.data.stars"]


def test_links_on_entity_update(api: LinkApi) -> None:
    owner, heir = api.make("misc", "Owner"), api.make("misc", "Heir")
    gadget = api.make("gadget")
    link = api.made_link("world.owns", owner, gadget)
    # replace the owner in one request (max one owner: the removal runs first)
    response = api.patch(
        gadget,
        links_remove=[link["id"]],
        links_add=[{"link_type": "world.owns", "source_id": heir["id"]}],
    )
    assert response.status_code == 200, response.json()
    assert response.json()["entity"]["revision"] == 2
    assert set(response.json()["affected"]["entities"]) == {gadget["id"], owner["id"], heir["id"]}
    assert summary(api.links_of(gadget)) == [("owned by", "in", "Heir")]
    other = api.made_link("core.related", owner, heir)
    entity = response.json()["entity"]
    assert invalid(api.patch(entity, links_remove=[other["id"]])) == ["links_remove.0"]


# --- user-defined link types ----------------------------------------------------------------


def test_custom_link_type_lifecycle(api: LinkApi) -> None:
    created = api.link_types(
        label="Sworn enemy of",
        symmetric=True,
        source_kinds=["misc"],
        target_kinds=["misc"],
        graph={"color": "#FF0000"},
    )
    assert created.status_code == 201
    link_type = created.json()
    assert link_type["key"] == "custom.sworn_enemy_of"
    assert (link_type["user_defined"], link_type["revision"]) == (True, 1)
    assert link_type["graph"] == {"color": "#ff0000", "dashed": False, "weight": 1}
    assert api.link_types(label="Sworn enemy of").json()["key"] == "custom.sworn_enemy_of_2"
    assert api.link_types(label="Été 1").json()["key"] == "custom.ete_1"
    assert api.link_types(label="42").json()["key"] == "custom.t_42"
    assert api.link_types(label="!!").json()["key"] == "custom.type"
    problem(api.link_types(key="custom.sworn_enemy_of", label="x"), 409, "conflict")
    problem(api.link_types(key="world.x", label="x"), 422, "validation_error")

    listed = api.client.get(f"{api.base}/link-types").json()["items"]
    keys = [t["key"] for t in listed]
    assert {"core.related", "custom.sworn_enemy_of", "world.old"} <= set(keys)
    assert next(t for t in listed if t["key"] == "world.old")["archived"] is True

    a, b = api.make("misc", "A"), api.make("misc", "B")
    link = api.made_link("custom.sworn_enemy_of", a, b)
    renamed = api.patch_type(link_type, label="Nemesis of", description="Bad blood.")
    assert renamed.status_code == 200
    link_type = renamed.json()
    assert (link_type["label"], link_type["revision"]) == ("Nemesis of", 2)
    assert summary(api.links_of(a)) == [("Nemesis of", "both", "B")]
    problem(api.patch_type({**link_type, "revision": 1}, label="x"), 409, "revision_conflict")

    archived = api.patch_type(link_type, archived=True).json()
    problem(
        api.link("custom.sworn_enemy_of", b, api.make("misc", "C")), 422, "link_type_not_allowed"
    )
    assert summary(api.links_of(a)) == [("Nemesis of", "both", "B")]  # existing links stay
    assert api.patch_link(link, role="still editable").status_code == 200

    body = problem(api.client.delete(f"{api.base}/link-types/{archived['key']}"), 409, "conflict")
    assert body["context"] == {"links": 1}
    api.delete_link(link["id"])  # trashed links still count
    problem(api.client.delete(f"{api.base}/link-types/{archived['key']}"), 409, "conflict")
    deleted = api.client.delete(f"{api.base}/link-types/custom.sworn_enemy_of_2")
    assert deleted.json() == {"key": "custom.sworn_enemy_of_2"}
    problem(api.client.delete(f"{api.base}/link-types/custom.sworn_enemy_of_2"), 404, "not_found")
    problem(api.client.delete(f"{api.base}/link-types/core.related"), 403, "forbidden")
    problem(api.patch_type({"key": "core.related", "revision": 1}, label="x"), 403, "forbidden")


def test_custom_link_type_validation(api: LinkApi) -> None:
    assert invalid(api.link_types(label="x", source_kinds=["misc", "ghost"])) == ["source_kinds.1"]
    assert invalid(api.link_types(label="x", data_schema={"type": 5})) == ["data_schema"]
    problem(api.link_types(label="x", source_kinds=[]), 422, "validation_error")
    problem(api.link_types(label="x", temporal="sometimes"), 422, "validation_error")
    beasts = api.link_types(label="tames", source_kinds=["beast", "beast"]).json()
    assert beasts["source_kinds"] == ["beast"]
    api.modules("extra", enabled=False)  # its only source kind is gone: not offered
    keys = [t["key"] for t in api.client.get(f"{api.base}/link-types").json()["items"]]
    assert "custom.tames" not in keys
    link_type = api.link_types(label="x").json()
    problem(api.patch_type(link_type, label=None), 422, "validation_error")


def test_custom_link_type_edits_are_checked_against_links(api: LinkApi) -> None:
    link_type = api.link_types(label="knows").json()
    misc, gadget, other = api.make("misc", "M"), api.make("gadget", "G"), api.make("misc", "O")
    timeline = api.timeline()
    api.made_link("custom.knows", misc, gadget)
    api.made_link("custom.knows", misc, gadget, data={"n": 1})
    api.made_link("custom.knows", misc, other, timeline_id=timeline["id"], valid_from=POINT)

    def conflicts(**change: Any) -> dict[str, int]:
        result: dict[str, int] = problem(api.patch_type(link_type, **change), 409, "conflict")[
            "context"
        ]["conflicts"]
        return result

    assert conflicts(target_kinds=["misc"]) == {"kinds": 2}
    assert conflicts(unique="per_pair") == {"unique": 1}
    assert conflicts(unique="per_pair_per_period") == {"unique": 1}
    assert conflicts(max_targets_per_source=1) == {"max_targets_per_source": 1}
    assert conflicts(max_sources_per_target=1) == {"max_sources_per_target": 1}
    assert conflicts(temporal="never") == {"temporal": 1}
    assert conflicts(temporal="required") == {"temporal": 2}
    assert conflicts(symmetric=True) == {"symmetric": 3}
    schema = {"type": "object", "required": ["n"]}
    assert conflicts(data_schema=schema) == {"data_schema": 2}
    assert conflicts(source_kinds=["gadget"], temporal="never") == {"kinds": 3, "temporal": 1}
    # compatible changes go through
    ok = api.patch_type(link_type, target_kinds=["misc", "gadget"], max_targets_per_source=3)
    assert ok.status_code == 200, ok.json()
    # symmetric, with the kinds fitting either way round
    pair = api.link_types(
        label="pairs", symmetric=True, source_kinds=["misc"], target_kinds=["gadget"]
    ).json()
    api.made_link("custom.pairs", gadget, misc)
    assert api.patch_type(pair, unique="per_pair").status_code == 200


# --- misc -----------------------------------------------------------------------------------


def test_read_only_server(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = LinkApi(client)
        a, b = api.make("misc"), api.make("misc")
        link = api.made_link("core.related", a, b)
    with make_client(tmp_path, read_only=True) as client:
        api = LinkApi(client, api.vault)
        assert len(api.links_of(a)) == 1
        assert client.get(f"{api.base}/link-types").status_code == 200
        problem(api.link("core.related", a, b), 403, "read_only")
        problem(api.patch_link(link, role="x"), 403, "read_only")
        problem(api.delete_link(link["id"]), 403, "read_only")
        problem(api.link_types(label="x"), 403, "read_only")


def test_purging_an_entity_deletes_its_links(api: LinkApi) -> None:
    a, b = api.make("misc", "A"), api.make("misc", "B")
    api.made_link("core.related", a, b)
    api.delete(a["id"])
    api.delete(a["id"], purge=True)
    assert api.links_of(b, include_trashed="true") == []


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    base = "/api/v1/vaults/{vault_id}"
    assert paths[f"{base}/links"]["post"]["operationId"] == "links_create"
    assert paths[f"{base}/links/{{link_id}}"]["patch"]["operationId"] == "links_update"
    assert paths[f"{base}/links/{{link_id}}"]["delete"]["operationId"] == "links_delete"
    assert paths[f"{base}/link-types"]["get"]["operationId"] == "link_types_list"
    assert paths[f"{base}/link-types"]["post"]["operationId"] == "link_types_create"
    assert paths[f"{base}/link-types/{{key}}"]["patch"]["operationId"] == "link_types_update"
    assert paths[f"{base}/link-types/{{key}}"]["delete"]["operationId"] == "link_types_delete"
    assert paths[f"{base}/entities/{{entity_id}}/links"]["get"]["operationId"] == "entities_links"
