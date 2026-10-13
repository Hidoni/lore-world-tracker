"""Temporal links (``time-model.md`` §10.1, §10.3, §10.5 item 3): validity bounds resolve and
propagate (anchored to events, referenced by other dates), default timelines, as-of filtering of
entity links, backlinks and the modules' relationship endpoints, and certainty at precision
boundaries."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, update

from lore.core.links.models import Link
from lore.core.vaults.manager import LINK_TIMES_SYNCED
from lore.core.vaults.meta import VaultMeta
from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules
from tests.test_facts import DAY, absolute, after
from tests.test_state import YEAR, in_year


class Realm:
    """Aetheria with a calendar; Ana and Ben (characters), a wedding and a funeral."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        self.calendar = api.calendar(self.dimension["id"])
        self.timeline = self.dimension["ext"]["prime_timeline_id"]
        home = {"dimension_id": self.dimension["id"]}
        self.home = home
        self.ana = api.make("character", "Ana", **home)
        self.ben = api.make("character", "Ben", **home)
        self.wedding = api.make("event", "Wedding", ext={"start": absolute(10 * DAY)}, **home)
        self.funeral = api.make("event", "Funeral", ext={"start": absolute(40 * DAY)}, **home)

    def links(self, entity: dict[str, Any], path: str = "links", **params: Any) -> Any:
        response = self.api.client.get(
            f"{self.api.base}/entities/{entity['id']}/{path}", params=params
        )
        assert response.status_code == 200, response.json()
        return response.json()

    def names_at(self, entity: dict[str, Any], at: int | str, **params: Any) -> list[str]:
        items = self.links(entity, at=str(at), **params)["items"]
        return [item["other"]["name"] for item in items]


@pytest.fixture
def realm(tmp_path: Path) -> Iterator[Realm]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield Realm(LinkApi(client))


def test_validity_anchored_to_events_moves_with_them(realm: Realm) -> None:
    api = realm.api
    marriage = api.made_link(
        "characters.spouse_of", realm.ana, realm.ben,
        valid_from=after("event", realm.wedding["id"], "start"),
        valid_to=after("event", realm.funeral["id"], "start"),
    )  # fmt: skip
    # The timeline defaults to the prime timeline of the ends' dimension.
    assert marriage["timeline_id"] == realm.timeline
    assert (marriage["valid_from_t"], marriage["valid_to_t"], marriage["time_status"]) == (
        str(10 * DAY), str(40 * DAY), "ok"
    )  # fmt: skip
    # Another date may refer to the link's bounds.
    mourning = api.make("event", "Mourning", ext={"start": after("link", marriage["id"],
                        "valid_to", DAY)}, **realm.home)  # fmt: skip
    assert mourning["ext"]["start_t"] == str(41 * DAY)

    moved = api.patch(realm.funeral, ext={"start": absolute(50 * DAY)})
    assert moved.status_code == 200, moved.json()
    link = api.links_of(realm.ana)[0]["link"]
    assert (link["valid_from_t"], link["valid_to_t"]) == (str(10 * DAY), str(50 * DAY))
    assert api.get(mourning["id"]).json()["ext"]["start_t"] == str(51 * DAY)

    # Trashing the link: what is anchored to it keeps its last moment.
    assert api.delete_link(marriage["id"]).status_code == 200
    kept = api.get(mourning["id"]).json()["ext"]
    assert (kept["start_t"], kept["time_status"]) == (str(51 * DAY), "trashed_ref")


def test_timelines_bounds_and_errors(realm: Realm) -> None:
    api = realm.api
    link = api.made_link("core.related", realm.ana, realm.ben, valid_from=absolute(5))
    assert (link["timeline_id"], link["valid_from_t"]) == (realm.timeline, "5")
    # Clearing the bounds makes it timeless again.
    cleared = api.patch_link(link, valid_from=None)
    assert cleared.status_code == 200, cleared.json()
    assert (cleared.json()["link"]["timeline_id"], cleared.json()["link"]["valid_from_t"]) == (
        None, None
    )  # fmt: skip
    # Multiversal ends have no prime timeline: it must be given.
    wanderer, drifter = api.make("character", "Wanderer"), api.make("character", "Drifter")
    problem(api.link("core.related", wanderer, drifter, valid_from=absolute(5)), 422,
            "validation_error")  # fmt: skip
    # A bound that doesn't resolve is refused.
    nowhere = after("event", realm.ana["id"], "start")
    problem(api.link("core.related", realm.ana, realm.ben, valid_from=nowhere), 422,
            "time_constraint")  # fmt: skip


def test_as_of_filtering_of_links_and_backlinks(realm: Realm) -> None:
    api = realm.api
    cat = api.make("character", "Cat", **realm.home)
    api.made_link("core.related", realm.ana, cat)  # timeless: always
    api.made_link("characters.spouse_of", realm.ana, realm.ben,
                  valid_from=absolute(100), valid_to=absolute(200))  # fmt: skip
    api.made_link("characters.parent_of", realm.ana, cat, valid_from=absolute(150))

    assert sorted(realm.names_at(realm.ana, 50)) == ["Cat"]
    assert sorted(realm.names_at(realm.ana, 100)) == ["Ben", "Cat"]
    assert sorted(realm.names_at(realm.ana, 160)) == ["Ben", "Cat", "Cat"]
    assert sorted(realm.names_at(realm.ana, 200)) == ["Cat", "Cat"]
    assert len(realm.links(realm.ana)["items"]) == 3  # without `at`: every link
    assert {i["certainty"] for i in realm.links(realm.ana)["items"]} == {None}
    assert {i["certainty"] for i in realm.links(realm.ana, at="160")["items"]} == {"certain"}
    # Backlinks filter their links too (Ben's spouse is symmetric: "in" from both sides).
    backlinks = realm.links(realm.ben, "backlinks", at="250")["items"]
    assert backlinks == []
    assert [b["entity"]["name"] for b in realm.links(realm.ben, "backlinks", at="150")["items"]] \
        == ["Ana"]  # fmt: skip

    # In another dimension's timeline the temporal links aren't there; timeless ones are.
    other = api.make("dimension", "Elsewhere")["ext"]["prime_timeline_id"]
    assert realm.names_at(realm.ana, 150, timeline=other) == ["Cat"]
    # `present`, and errors.
    problem(api.client.get(f"{api.base}/entities/{realm.ana['id']}/links",
                           params={"at": "present"}), 422, "validation_error")  # fmt: skip
    api.patch(realm.dimension, ext={"present": absolute(120)})
    assert sorted(realm.names_at(realm.ana, "present")) == ["Ben", "Cat"]
    wanderer = api.make("character", "Wanderer")
    problem(api.client.get(f"{api.base}/entities/{wanderer['id']}/links", params={"at": "0"}),
            422, "validation_error")  # fmt: skip
    assert realm.names_at(wanderer, 0, timeline=realm.timeline) == []


def test_certainty_at_precision_boundaries(realm: Realm) -> None:
    """Ana lived in Varn from (some time in) year 2 until (some time in) year 4."""
    api = realm.api
    varn = api.make("location", "Varn", **realm.home)
    cal = realm.calendar
    api.made_link("locations.resides_in", realm.ana, varn, valid_from=in_year(cal, 2),
                  valid_to=in_year(cal, 4))  # fmt: skip

    def residents(at: int) -> list[tuple[str, str]]:
        response = api.client.get(f"{api.base}/m/locations/{varn['id']}/residents",
                                  params={"at": str(at)})  # fmt: skip
        assert response.status_code == 200, response.json()
        return [(i["other"]["name"], i["certainty"]) for i in response.json()["items"]]

    assert residents(YEAR - 1) == []
    assert residents(YEAR) == [("Ana", "possible")]
    assert residents(2 * YEAR - 1) == [("Ana", "certain")]
    assert residents(3 * YEAR) == [("Ana", "possible")]
    assert residents(4 * YEAR - 1) == []


def test_module_endpoints_filter_as_of(realm: Realm) -> None:
    api = realm.api
    home = realm.home
    guild = api.make("group", "Guild", **home)
    elves = api.make("species", "Elves", **home)
    varn = api.make("location", "Varn", **home)
    bounded = {"valid_from": absolute(100), "valid_to": absolute(200)}
    api.made_link("groups.member_of", realm.ana, guild, **bounded)
    api.made_link("groups.member_of", realm.ben, guild)
    api.made_link("groups.controls", guild, varn, **bounded)
    api.made_link("species.is_a", realm.ana, elves, **bounded)
    api.made_link("characters.spouse_of", realm.ana, realm.ben, **bounded)

    def get(path: str, at: int) -> Any:
        response = api.client.get(f"{api.base}/m/{path}", params={"at": str(at)})
        assert response.status_code == 200, response.json()
        return response.json()

    for at, members in ((150, ["Ana", "Ben"]), (250, ["Ben"])):
        body = get(f"groups/{guild['id']}/members", at)
        assert [i["item"]["other"]["name"] for i in body["items"]] == members
    assert [i["other"]["name"] for i in get(f"groups/{guild['id']}/territory", 150)["items"]] \
        == ["Varn"]  # fmt: skip
    assert get(f"groups/{guild['id']}/territory", 250)["items"] == []
    assert [i["other"]["name"] for i in get(f"species/{elves['id']}/members", 150)["items"]] \
        == ["Ana"]  # fmt: skip
    assert get(f"species/{elves['id']}/members", 50)["items"] == []

    def family(at: int) -> list[str]:
        groups = get(f"characters/{realm.ana['id']}/relationships", at)["groups"]
        return [i["other"]["name"] for g in groups for i in g["items"]]

    assert family(150) == ["Ben"]
    assert family(250) == []


def test_older_vaults_resolve_link_validity_on_open(tmp_path: Path) -> None:
    with make_client(tmp_path, with_real_modules()) as client:
        api = LinkApi(client)
        realm = Realm(api)
        link = api.made_link("core.related", realm.ana, realm.ben,
                             valid_from=after("event", realm.wedding["id"], "start"))  # fmt: skip
        vault = client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]
        with vault.write_sessions.begin() as session:  # as a v0.5.0 vault stored it
            session.execute(
                update(Link)
                .where(Link.id == link["id"])
                .values(valid_from_t=None, time_status=None)
            )
            session.execute(delete(VaultMeta).where(VaultMeta.key == LINK_TIMES_SYNCED))
        vault_id = api.vault
    with make_client(tmp_path, with_real_modules()) as client:
        api = LinkApi(client, vault_id)
        found = api.links_of({"id": realm.ana["id"]})[0]["link"]
        assert (found["valid_from_t"], found["time_status"]) == (str(10 * DAY), "ok")
