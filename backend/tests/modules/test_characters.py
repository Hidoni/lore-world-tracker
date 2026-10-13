"""The characters module (``docs/modules/characters.md``): the ``character`` kind, relationship
link types and the relationships and life endpoints."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lore.modules.characters.links import CATEGORIES
from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def m(api: LinkApi, path: str, **params: Any) -> Any:
    return api.client.get(f"{api.base}/m/characters{path}", params=params)


def groups(api: LinkApi, character: dict[str, Any]) -> dict[str, list[tuple[str, str, Any]]]:
    """Category → (label, other's name, data) of the character's relationships."""
    response = m(api, f"/{character['id']}/relationships")
    assert response.status_code == 200, response.json()
    return {
        group["category"]: [
            (item["label"], item["other"]["name"], item["link"]["data"]) for item in group["items"]
        ]
        for group in response.json()["groups"]
    }


def test_the_kind(api: LinkApi) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    character = next(kind for kind in registry["kinds"] if kind["key"] == "character")
    assert (character["icon"], character["capabilities"]["can_have_worldline"]) == ("user", True)
    fields = {field["key"]: field for field in character["fields"]}
    assert list(fields) == [
        "full_name",
        "epithet",
        "title",
        "gender",
        "occupation",
        "appearance",
        "personality",
        "secret",
    ]
    assert fields["secret"]["default_visibility"] == "private"
    assert (fields["title"]["multiple"], fields["title"]["temporal"]) == (True, True)
    keys = {link["key"] for link in registry["link_types"] if link["module"] == "characters"}
    assert keys == set(CATEGORIES)


def test_every_relationship_type(api: LinkApi) -> None:
    ilsa = api.make("character", "Ilsa")
    oren = api.make("character", "Oren")
    for key in CATEGORIES:
        api.made_link(key, ilsa, oren)
    from_ilsa, from_oren = groups(api, ilsa), groups(api, oren)
    assert [label for label, _, _ in from_ilsa["family"]] == [
        "parent of",
        "sibling of",
        "spouse of",
    ]
    # Directed types read inversely from the other side; symmetric ones the same.
    assert [label for label, _, _ in from_oren["family"]] == ["child of", "sibling of", "spouse of"]
    assert sorted(label for label, _, _ in from_oren["social"]) == [
        "enemy of",
        "friend of",
        "rival of",
        "romantic partner of",
        "served by",
        "student of",
    ]
    assert [label for label, _, _ in from_ilsa["custom"]] == ["related to"]


def test_data_and_kind_rules(api: LinkApi) -> None:
    ilsa = api.make("character", "Ilsa")
    oren = api.make("character", "Oren")
    api.made_link("characters.parent_of", ilsa, oren, data={"kind": "adoptive"})
    api.made_link("characters.sibling_of", oren, ilsa, data={"kind": "half"})
    api.made_link("characters.serves", oren, ilsa, data={"capacity": "steward"})
    family = groups(api, ilsa)["family"]
    assert ("parent of", "Oren", {"kind": "adoptive"}) in family
    assert ("sibling of", "Oren", {"kind": "half"}) in family
    bad = api.link("characters.spouse_of", ilsa, oren, data={"kind": "fling"})
    problem(bad, 422, "validation_error")
    gadget = api.make("gadget", "Sword")
    problem(api.link("characters.friend_of", ilsa, gadget), 422, "link_type_not_allowed")
    # Siblings are timeless.
    dimension = api.make("dimension")
    timed = api.link(
        "characters.sibling_of",
        ilsa,
        api.make("character", "Tam"),
        timeline_id=dimension["ext"]["prime_timeline_id"],
        valid_from={"anchor": {"kind": "absolute", "t": "5"}, "precision": "base"},
    )
    assert timed.status_code == 422, timed.json()


def test_custom_link_types_count_between_characters(api: LinkApi) -> None:
    ilsa = api.make("character", "Ilsa")
    oren = api.make("character", "Oren")
    sword = api.make("gadget", "Sword")
    sworn = api.link_types(label="Sworn to").json()
    api.made_link(sworn["key"], ilsa, oren)
    api.made_link(sworn["key"], ilsa, sword)
    api.made_link("core.related", ilsa, oren)
    assert groups(api, ilsa)["custom"] == [("Sworn to", "Oren", {})]


def test_life(api: LinkApi) -> None:
    ilsa = api.make("character", "Ilsa")
    dimension = api.make("dimension", "Aetheria")
    api.calendar(dimension["id"])
    timeline = dimension["ext"]["prime_timeline_id"]

    def event(name: str, t: int) -> dict[str, Any]:
        start = {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}
        return api.make("event", name, dimension_id=dimension["id"], ext={"start": start})

    crowning, birth, war = event("Crowning", 300), event("Birth", 100), event("War", 200)
    api.made_link("core.participant", crowning, ilsa, role="queen")
    api.made_link("core.participant", birth, ilsa, role="newborn")
    api.made_link("core.participant", birth, ilsa)
    api.made_link("core.related", war, ilsa)
    response = m(api, f"/{ilsa['id']}/life", timeline=timeline)
    assert response.status_code == 200, response.json()
    items = response.json()["items"]
    assert [(item["name"], item["roles"]) for item in items] == [
        ("Birth", ["newborn"]),
        ("Crowning", ["queen"]),
    ]
    assert items[0]["start_t"] == "100"
    problem(m(api, f"/{war['id']}/life", timeline=timeline), 404, "not_found")
    problem(m(api, f"/{war['id']}/relationships"), 404, "not_found")
    problem(m(api, f"/{ilsa['id']}/life", timeline=dimension["id"]), 404, "not_found")


def test_disabling_keeps_relationships(api: LinkApi) -> None:
    ilsa = api.make("character", "Ilsa", fields={"secret": "a spy"})
    oren = api.make("character", "Oren")
    api.made_link("characters.spouse_of", ilsa, oren)
    assert api.modules("characters", enabled=False).status_code == 200
    problem(m(api, f"/{ilsa['id']}/relationships"), 404, "module_disabled")
    problem(api.get(ilsa["id"]), 404, "module_disabled")
    assert api.modules("characters", enabled=True).status_code == 200
    assert api.get(ilsa["id"]).json()["fields"]["secret"] == "a spy"
    assert groups(api, ilsa)["family"] == [("spouse of", "Oren", {})]


def family(api: LinkApi) -> dict[str, dict[str, Any]]:
    """Three generations: Aldric and Bera (married) have Cyra and Dain; Aldric remarried Elin
    and has Fenn (Cyra's half-brother); Cyra married Gord and has Hale; Dain has a linked
    sister Ivy with no recorded parents."""
    people = {
        name: api.make("character", name)
        for name in ["Aldric", "Bera", "Cyra", "Dain", "Elin", "Fenn", "Gord", "Hale", "Ivy"]
    }
    a, b, c, d, e, f, g, h, i = people.values()

    def parent(x: dict[str, Any], y: dict[str, Any]) -> None:
        api.made_link("characters.parent_of", x, y, data={"kind": "biological"})

    api.made_link("characters.spouse_of", a, b, data={"kind": "marriage"})
    api.made_link("characters.spouse_of", a, e)
    api.made_link("characters.spouse_of", c, g)
    for child in (c, d):
        parent(a, child)
        parent(b, child)
    parent(a, f)
    parent(e, f)
    parent(c, h)
    parent(g, h)
    api.made_link("characters.sibling_of", d, i, data={"kind": "half"})
    return people


def tree(api: LinkApi, root: dict[str, Any], **params: Any) -> dict[str, Any]:
    response = m(api, f"/{root['id']}/family-tree", **params)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def generations(body: dict[str, Any]) -> dict[str, int]:
    return {person["name"]: person["generation"] for person in body["people"]}


def test_family_tree_generations_spouses_and_siblings(api: LinkApi) -> None:
    people = family(api)
    body = tree(api, people["Cyra"])
    assert body["root_id"] == people["Cyra"]["id"]
    assert body["people"][0]["name"] == "Cyra"
    assert generations(body) == {
        "Cyra": 0,
        "Aldric": -1,
        "Bera": -1,
        "Dain": 0,
        "Fenn": 0,
        "Elin": -1,
        "Gord": 0,
        "Hale": 1,
    }
    # Existence comes with temporal facts: unknown for now.
    assert {(p["from_t"], p["to_t"]) for p in body["people"]} == {(None, None)}
    names = {person["id"]: person["name"] for person in body["people"]}
    edges = {
        (edge["kind"], names[edge["source_id"]], names[edge["target_id"]], edge["relation"])
        for edge in body["edges"]
    }
    assert ("parent", "Aldric", "Fenn", "biological") in edges
    assert ("spouse", "Aldric", "Elin", None) in edges
    assert ("spouse", "Cyra", "Gord", None) in edges
    assert len(edges) == len(body["edges"]) == 11
    assert body["truncated"] is False

    # Dain's linked sister Ivy (no recorded parents) comes with his siblings.
    assert generations(tree(api, people["Dain"], up=0, down=0))["Ivy"] == 0


def test_family_tree_depth_and_options(api: LinkApi) -> None:
    people = family(api)
    # From the grandson: grandparents two generations up, the mother's (half-)brothers, and
    # the half-uncle's mother.
    up = generations(tree(api, people["Hale"], up=2, down=0))
    assert up == {
        "Hale": 0,
        "Cyra": -1,
        "Gord": -1,
        "Dain": -1,
        "Fenn": -1,
        "Aldric": -2,
        "Bera": -2,
        "Elin": -2,
    }
    assert generations(tree(api, people["Hale"], up=1, down=0)) == {
        "Hale": 0,
        "Cyra": -1,
        "Gord": -1,
    }
    bare = tree(api, people["Aldric"], include_spouses=False, include_siblings=False)
    assert generations(bare) == {"Aldric": 0, "Cyra": 1, "Dain": 1, "Fenn": 1, "Hale": 2}
    assert {edge["kind"] for edge in bare["edges"]} == {"parent"}
    # With spouses: the other parents of the children (Bera, Elin, Gord).
    assert set(generations(tree(api, people["Aldric"]))) == {
        "Aldric",
        "Bera",
        "Elin",
        "Cyra",
        "Dain",
        "Fenn",
        "Gord",
        "Hale",
    }
    limited = tree(api, people["Aldric"], limit=3)
    assert len(limited["people"]) == 3
    assert limited["truncated"] is True


def test_family_tree_leaves_out_the_trash_and_other_kinds(api: LinkApi) -> None:
    people = family(api)
    assert api.client.delete(f"{api.base}/entities/{people['Fenn']['id']}").status_code == 200
    assert "Fenn" not in generations(tree(api, people["Aldric"]))
    place = api.make("misc", "Hearth")
    problem(m(api, f"/{place['id']}/family-tree"), 404, "not_found")
    problem(
        m(api, f"/{people['Aldric']['id']}/family-tree", timeline=place["id"]), 404, "not_found"
    )
