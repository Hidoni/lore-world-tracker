"""The groups module (``docs/modules/groups.md``): the ``group`` kind, its link types and the
members, leaders and territory endpoints."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from lore.core.links.models import Link
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
    api.modules("locations", enabled=False, cascade=True)  # maps depends on it
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
    # Timeless leaders first, then by the start of their validity.
    assert [(i["item"]["other"]["name"], i["from_t"], i["to_t"]) for i in items] == [
        ("Ilsa", None, None),
        ("Oren", "100", "200"),
        ("Tam", "200", None),
    ]
    assert items[1]["item"]["link"]["valid_from"]["anchor"] == point(100)["anchor"]
    # As of a moment: the timeless leader and the one leading then.
    for at, expected in (("150", ["Ilsa", "Oren"]), ("200", ["Ilsa", "Tam"]), ("50", ["Ilsa"])):
        then = m(api, f"/{e.empire['id']}/leaders", at=at).json()["items"]
        assert [i["item"]["other"]["name"] for i in then] == expected
        assert {i["item"]["certainty"] for i in then} == {"certain"}


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


def resolve(api: LinkApi, link: dict[str, Any], start: int | None, end: int | None) -> None:
    """Sets a link's resolved validity as temporal links will (M7)."""
    vault = api.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]
    with vault.write_sessions.begin() as session:
        session.execute(
            update(Link).where(Link.id == link["id"]).values(valid_from_t=start, valid_to_t=end)
        )


def test_membership_bounds(api: LinkApi) -> None:
    e = Empire(api)
    first = api.made_link("groups.member_of", e.ilsa, e.empire)
    api.made_link("groups.member_of", e.oren, e.empire)
    resolve(api, first, 100, 250)
    items = m(api, f"/{e.empire['id']}/members").json()["items"]
    assert [(i["item"]["other"]["name"], i["from_t"], i["to_t"]) for i in items] == [
        ("Ilsa", "100", "250"),
        ("Oren", None, None),
    ]


def test_org_chart(api: LinkApi) -> None:
    e = Empire(api)
    home = {"dimension_id": e.dimension["id"]}
    guild = api.make("group", "Pilots' Guild", **home)
    part = api.made_link("groups.part_of", guild, e.empire)
    api.made_link("groups.led_by", e.empire, e.ilsa, data={"title": "Empress"})
    old = api.made_link("groups.led_by", e.ministry, e.oren)
    api.made_link("groups.member_of", e.tam, e.ministry)
    api.made_link("groups.member_of", e.oren, e.ministry)
    api.made_link("groups.member_of", e.ilsa, e.empire)

    def chart(**params: Any) -> dict[str, Any]:
        response = m(api, f"/{e.empire['id']}/org-chart", **params)
        assert response.status_code == 200, response.json()
        body: dict[str, Any] = response.json()
        return body

    def units(body: dict[str, Any]) -> list[tuple[str, str | None, str, int]]:
        names = {u["id"]: u["name"] for u in body["units"]}
        return [
            (u["name"], names.get(u["parent_id"]), u["via"], u["member_count"])
            for u in body["units"]
        ]

    body = chart()
    assert body["root_id"] == e.empire["id"]
    assert units(body) == [
        ("Empire", None, "root", 1),
        ("Ministry of Tides", "Empire", "subgroup", 2),
        ("Pilots' Guild", "Empire", "part_of", 0),
        ("Harbor Office", "Ministry of Tides", "subgroup", 0),
    ]
    assert body["units"][0]["leaders"] == [{"id": e.ilsa["id"], "name": "Ilsa", "title": "Empress"}]
    assert [u["depth"] for u in body["units"]] == [0, 1, 1, 2]
    assert [u[0] for u in units(chart(depth=1))] == ["Empire", "Ministry of Tides", "Pilots' Guild"]

    # As of a moment: links valid then (open bounds count).
    resolve(api, part, 100, 200)
    resolve(api, old, None, 150)
    assert [u[0] for u in units(chart(at="300"))] == [
        "Empire",
        "Ministry of Tides",
        "Harbor Office",
    ]
    then = chart(at="120", timeline=e.timeline)
    assert "Pilots' Guild" in [u[0] for u in units(then)]
    assert [leader["name"] for leader in then["units"][1]["leaders"]] == ["Oren"]
    assert chart(at="160")["units"][1]["leaders"] == []

    # Readers count only the members they see.
    secret = api.make("character", "Spy", visibility="private", **home)
    api.made_link("groups.member_of", secret, e.ministry)
    assert units(chart())[1][3] == 3
    assert units(chart(as_reader="true"))[1][3] == 2
    # …and parts by links they see.
    school = api.make("group", "Pilot School", **home)
    api.made_link("groups.part_of", school, e.empire, visibility="private")
    assert "Pilot School" in [u[0] for u in units(chart())]
    assert "Pilot School" not in [u[0] for u in units(chart(as_reader="true"))]

    problem(m(api, f"/{e.ilsa['id']}/org-chart"), 404, "not_found")
    problem(m(api, f"/{e.empire['id']}/org-chart", timeline=e.ilsa["id"]), 404, "not_found")
    problem(m(api, f"/{e.empire['id']}/org-chart", at="soon"), 422, "validation_error")
