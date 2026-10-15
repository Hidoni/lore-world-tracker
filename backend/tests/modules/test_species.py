"""The species module (``docs/modules/species.md``): the ``species`` kind, its link types and
the members and descent-tree endpoints."""

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


def get(api: LinkApi, path: str, **params: Any) -> Any:
    return api.client.get(f"{api.base}/m/species{path}", params=params)


def test_kind_and_link_types(api: LinkApi) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    species = next(kind for kind in registry["kinds"] if kind["key"] == "species")
    assert (species["icon"], species["allowed_parents"]) == ("dna", ["species", "misc"])
    fields = {field["key"]: field for field in species["fields"]}
    assert fields["typical_lifespan"]["type"] == "duration"
    assert fields["population"]["temporal"] is True
    keys = {link["key"] for link in registry["link_types"] if link["module"] == "species"}
    assert keys == {"species.is_a", "species.descended_from", "species.native_to"}
    api.modules("locations", enabled=False, cascade=True)  # maps depends on it
    registry = api.client.get(f"{api.base}/registry").json()
    assert "species.native_to" not in {link["key"] for link in registry["link_types"]}


def test_members_and_rules(api: LinkApi) -> None:
    elves = api.make("species", "Elves", fields={"sapience": "sapient"})
    ilsa = api.make("character", "Ilsa")
    wolf = api.make("gadget", "Wolf statue")
    api.made_link("species.is_a", ilsa, elves)
    api.made_link("species.is_a", wolf, elves)
    response = get(api, f"/{elves['id']}/members")
    assert response.status_code == 200, response.json()
    assert [item["other"]["name"] for item in response.json()["items"]] == ["Ilsa", "Wolf statue"]
    problem(get(api, f"/{ilsa['id']}/members"), 404, "not_found")
    problem(api.link("species.descended_from", ilsa, elves), 422, "link_type_not_allowed")
    varn = api.make("location", "Varn")
    api.made_link("species.native_to", elves, varn)
    bad = api.create("species", "X", fields={"sapience": "very"})
    problem(bad, 422, "validation_error")


def test_descent_tree(api: LinkApi) -> None:
    world = api.make("dimension", "Aetheria")
    home = {"dimension_id": world["id"]}
    first = api.make("species", "First Folk", **home)
    elves = api.make("species", "Elves", **home)
    sea = api.make("species", "Sea Elves", parent_id=elves["id"], **home)
    api.make("species", "Dragons")  # multiversal, unrelated
    other = api.make("species", "Shades", dimension_id=api.make("dimension")["id"])
    link = api.made_link("species.descended_from", elves, first)
    api.made_link("species.descended_from", other, first)
    response = get(api, "/descent-tree", dimension=world["id"])
    assert response.status_code == 200, response.json()
    graph = response.json()
    assert [node["name"] for node in graph["nodes"]] == [
        "Dragons",
        "Elves",
        "First Folk",
        "Sea Elves",
    ]
    assert sorted((e["kind"], e["source_id"], e["target_id"]) for e in graph["edges"]) == sorted(
        [
            ("descended_from", elves["id"], first["id"]),
            ("subspecies", sea["id"], elves["id"]),
        ]
    )
    assert link["id"] in {edge["id"] for edge in graph["edges"]}
    assert len(get(api, "/descent-tree").json()["nodes"]) == 5


def test_disabling_hides_species(api: LinkApi) -> None:
    elves = api.make("species", "Elves")
    assert api.modules("species", enabled=False).status_code == 200
    problem(get(api, "/descent-tree"), 404, "module_disabled")
    problem(api.get(elves["id"]), 404, "module_disabled")
    assert api.modules("species", enabled=True).status_code == 200
    assert [n["name"] for n in get(api, "/descent-tree").json()["nodes"]] == ["Elves"]
