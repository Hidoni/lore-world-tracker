"""The characters module (``docs/modules/characters.md``): the ``character`` kind, relationship
link types and the relationships and life endpoints."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lore.modules.characters import MODULE as CHARACTERS
from lore.modules.characters.links import CATEGORIES
from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import ENTITY_MODULES


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, (*ENTITY_MODULES, CHARACTERS)) as client:
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
