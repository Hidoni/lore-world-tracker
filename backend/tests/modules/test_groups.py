"""The groups module (``docs/modules/groups.md``): the ``group`` kind, its link types and the
members, leaders and territory endpoints."""

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


def m(api: LinkApi, path: str, **params: Any) -> Any:
    response = api.client.get(f"{api.base}/m/groups{path}", params=params)
    return response


def point(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


class Empire:
    """The Empire ⊃ Ministry of Tides ⊃ Harbor Office; its people, leaders and lands."""

    def __init__(self, api: LinkApi) -> None:
        self.dimension = api.make("dimension", "Aetheria")
        api.calendar(self.dimension["id"])
        self.timeline = self.dimension["ext"]["prime_timeline_id"]
        home = {"dimension_id": self.dimension["id"]}
        self.empire = api.make("group", "Empire", fields={"group_type": "government"}, **home)
        self.ministry = api.make("group", "Ministry of Tides", parent_id=self.empire["id"], **home)
        self.office = api.make("group", "Harbor Office", parent_id=self.ministry["id"], **home)
        self.ilsa = api.make("character", "Ilsa", **home)
        self.oren = api.make("character", "Oren", **home)
        self.tam = api.make("character", "Tam", **home)
        self.varn = api.make("location", "Varn", **home)


def test_kind_and_link_types(api: LinkApi) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    group = next(kind for kind in registry["kinds"] if kind["key"] == "group")
    assert (group["icon"], group["allowed_parents"]) == ("users", ["group", "misc"])
    keys = {link["key"] for link in registry["link_types"] if link["module"] == "groups"}
    assert keys == {
        "groups.member_of",
        "groups.led_by",
        "groups.part_of",
        "groups.allied_with",
        "groups.at_war_with",
        "groups.vassal_of",
        "groups.controls",
    }
    # Without locations there is no territory.
    api.modules("locations", enabled=False)
    registry = api.client.get(f"{api.base}/registry").json()
    assert "groups.controls" not in {link["key"] for link in registry["link_types"]}


def test_link_rules(api: LinkApi) -> None:
    e = Empire(api)
    api.made_link(
        "groups.member_of", e.ilsa, e.empire, data={"rank": "general", "is_leader": False}
    )
    problem(
        api.link("groups.member_of", e.ilsa, e.empire, data={"rank": 3}), 422, "validation_error"
    )
    problem(api.link("groups.allied_with", e.ilsa, e.empire), 422, "link_type_not_allowed")
    rivals = api.make("group", "Rebels", dimension_id=e.dimension["id"])
    war = api.made_link("groups.at_war_with", rivals, e.empire)
    assert {item["direction"] for item in api.links_of(e.empire)} == {"in", "both"}
    assert war["link_type"] == "groups.at_war_with"
    api.made_link("groups.vassal_of", e.ministry, e.empire)
    api.made_link("groups.part_of", e.office, e.empire)
    # Characters can serve groups now that the kind exists.
    api.made_link("characters.serves", e.oren, e.empire, data={"capacity": "envoy"})


def test_members_with_subgroups(api: LinkApi) -> None:
    e = Empire(api)
    api.made_link("groups.member_of", e.ilsa, e.empire, data={"rank": "Empress"})
    api.made_link("groups.member_of", e.oren, e.ministry, data={"title": "Minister"})
    api.made_link("groups.member_of", e.tam, e.office)

    def members(**params: Any) -> list[tuple[str, str]]:
        response = m(api, f"/{e.empire['id']}/members", **params)
        assert response.status_code == 200, response.json()
        return [(i["group_id"], i["item"]["other"]["name"]) for i in response.json()["items"]]

    assert members() == [(e.empire["id"], "Ilsa")]
    assert members(include_subgroups="true") == [
        (e.empire["id"], "Ilsa"),
        (e.ministry["id"], "Oren"),
        (e.office["id"], "Tam"),
    ]
    problem(m(api, f"/{e.ilsa['id']}/members"), 404, "not_found")


def test_leaders_in_succession(api: LinkApi) -> None:
    e = Empire(api)

    def lead(who: dict[str, Any], start: int | None, end: int | None = None) -> None:
        validity: dict[str, Any] = {}
        if start is not None:
            validity = {"timeline_id": e.timeline, "valid_from": point(start)}
            if end is not None:
                validity["valid_to"] = point(end)
        api.made_link("groups.led_by", e.empire, who, data={"title": "Ruler"}, **validity)

    lead(e.tam, 200)
    lead(e.oren, 100, 200)
    lead(e.ilsa, None)
    items = m(api, f"/{e.empire['id']}/leaders").json()["items"]
    # Link validity resolves to moments with temporal links (M7): until then every leader is
    # unordered by time, so by name; the stored specs come along.
    assert [(i["item"]["other"]["name"], i["from_t"]) for i in items] == [
        ("Ilsa", None),
        ("Oren", None),
        ("Tam", None),
    ]
    assert items[1]["item"]["link"]["valid_from"]["anchor"] == point(100)["anchor"]


def test_territory(api: LinkApi) -> None:
    e = Empire(api)
    api.made_link("groups.controls", e.empire, e.varn)
    items = m(api, f"/{e.empire['id']}/territory").json()["items"]
    assert [item["other"]["name"] for item in items] == ["Varn"]
    assert m(api, f"/{e.ministry['id']}/territory").json()["items"] == []


def test_disabling_keeps_groups(api: LinkApi) -> None:
    e = Empire(api)
    api.made_link("groups.member_of", e.ilsa, e.empire)
    assert api.modules("groups", enabled=False).status_code == 200
    problem(m(api, f"/{e.empire['id']}/members"), 404, "module_disabled")
    assert api.links_of(e.ilsa) == []
    assert api.modules("groups", enabled=True).status_code == 200
    assert [link["other"]["name"] for link in api.links_of(e.ilsa)] == ["Empire"]
