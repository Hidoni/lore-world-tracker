"""The branches module (``docs/modules/branches.md``, ``time-model.md`` §4): creating branches,
their branch points (bounds, anchors to the parent's records, moving with their anchor),
branch-only entities and trashing a branch with what it holds."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules


def at(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def start_of(event: dict[str, Any], units: int = 0) -> dict[str, Any]:
    ref = {"type": "event", "id": event["id"], "slot": "start"}
    offset = {"kind": "base", "units": str(units)}
    return {"anchor": {"kind": "relative", "ref": ref, "offset": offset}, "precision": "base"}


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class Empire:
    """The Empire (prime): the Reign from 100 to 300, the Coronation at 100 and the
    Assassination at 200. "Survives" branches at the Assassination's start (anchored)."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Empire")
        self.prime = self.dimension["ext"]["prime_timeline_id"]
        api.calendar(self.dimension["id"])
        self.reign = self.event("Reign", 100, 300)
        self.coronation = self.event("Coronation", 100)
        self.assassination = self.event("Assassination", 200)
        self.survives = self.branch("Survives", start_of(self.assassination))

    def event(
        self, name: str, start: int, end: int | None = None, timeline: str | None = None
    ) -> dict[str, Any]:
        ext: dict[str, Any] = {"start": at(start)}
        if end is not None:
            ext["end"] = {"kind": "time_point", "time_point": at(end)}
        if timeline is not None:
            ext["timeline_id"] = timeline
        return self.api.make("event", name, dimension_id=self.dimension["id"], ext=ext)

    def create_branch(self, name: str, point: dict[str, Any], parent: str | None = None) -> Any:
        return self.api.client.post(
            f"{self.api.base}/m/branches/timelines",
            json={
                "parent_timeline_id": parent or self.prime,
                "branch_point": point,
                "name": name,
                "summary": f"What if… ({name})",
            },
        )

    def branch(self, name: str, point: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
        response = self.create_branch(name, point, parent)
        assert response.status_code == 201, response.json()
        entity: dict[str, Any] = response.json()["entity"]
        return entity

    def timeline(self, timeline_id: str) -> dict[str, Any]:
        response = self.api.get(timeline_id)
        assert response.status_code == 200, response.json()
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
def empire(api: LinkApi) -> Empire:
    return Empire(api)


def test_creating_a_branch(api: LinkApi, empire: Empire) -> None:
    survives = empire.timeline(empire.survives["id"])
    assert survives["kind"] == "timeline"
    assert survives["summary"] == "What if… (Survives)"
    assert survives["dimension_id"] == empire.dimension["id"]
    assert survives["origin_timeline_id"] is None  # a branch of the prime: shown everywhere
    ext = survives["ext"]
    assert (ext["parent_timeline_id"], ext["is_prime"], ext["branch_t"]) == (
        empire.prime,
        False,
        "200",
    )
    tree = api.client.get(f"{api.base}/dimensions/{empire.dimension['id']}/timelines").json()
    [prime] = tree["items"]
    assert [child["name"] for child in prime["children"]] == ["Survives"]
    # A branch of a branch is branch-only in its parent's lineage.
    exile = empire.branch("Exile", at(250), parent=empire.survives["id"])
    assert empire.timeline(exile["id"])["origin_timeline_id"] == empire.survives["id"]
    # Timelines still can't be made through the generic entity API.
    response = api.create("timeline", "Direct", dimension_id=empire.dimension["id"])
    problem(response, 422, "validation_error")


def test_branch_points_must_be_valid(api: LinkApi, empire: Empire) -> None:
    beyond = empire.create_branch("Beyond", at(10**13))  # D = 10^12
    assert problem(beyond, 422, "validation_error")["errors"][0]["code"] == "out_of_bounds"
    missing = empire.create_branch("Orphan", at(5), parent="01000000-0000-7000-8000-000000000000")
    problem(missing, 404, "not_found")
    # Anchored to an event of a sibling branch: the prime doesn't have it.
    elsewhere = empire.event("Rescue", 210, timeline=empire.survives["id"])
    response = empire.create_branch("Sibling", start_of(elsewhere))
    errors = problem(response, 422, "validation_error")["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("branch_point", "branch_point_invalid")]
    # The branch's own events are fine for a branch of it.
    nested = empire.branch("After the rescue", start_of(elsewhere, 5), parent=empire.survives["id"])
    assert empire.timeline(nested["id"])["ext"]["branch_t"] == "215"


def test_anchored_branch_points_move_with_their_event(api: LinkApi, empire: Empire) -> None:
    assassination = api.get(empire.assassination["id"]).json()
    moved = api.patch(assassination, ext={"start": at(250)})
    assert moved.status_code == 200, moved.json()
    assert empire.timeline(empire.survives["id"])["ext"]["branch_t"] == "250"
    # The tree reports the moved branch point too.
    tree = api.client.get(f"{api.base}/dimensions/{empire.dimension['id']}/timelines").json()
    assert tree["items"][0]["children"][0]["branch_t"] == "250"


def test_branch_only_entities(api: LinkApi, empire: Empire) -> None:
    home = {"dimension_id": empire.dimension["id"]}
    survives = empire.survives["id"]
    url = f"{api.base}/entities"
    rebel = api.client.post(
        url, params={"timeline": survives}, json={"kind": "character", "name": "Rebel", **home}
    )
    assert rebel.status_code == 201, rebel.json()
    assert rebel.json()["entity"]["origin_timeline_id"] == survives
    # Created in the prime: shown everywhere.
    loyal = api.client.post(url, params={"timeline": empire.prime},
                            json={"kind": "character", "name": "Loyalist", **home})  # fmt: skip
    assert loyal.json()["entity"]["origin_timeline_id"] is None
    # An event of the branch is branch-only too.
    rescue = empire.event("Rescue", 210, timeline=survives)
    assert rescue["origin_timeline_id"] == survives

    def names(**params: Any) -> set[str]:
        response = api.client.get(url, params={"dimension": empire.dimension["id"], **params})
        assert response.status_code == 200, response.json()
        return {item["name"] for item in response.json()["items"]}

    assert {"Rebel", "Rescue"}.isdisjoint(names())  # the prime view
    assert {"Rebel", "Rescue", "Loyalist"} <= names(timeline=survives)
    exile = empire.branch("Exile", at(250), parent=survives)
    assert {"Rebel", "Rescue"} <= names(timeline=exile["id"])  # inherited by descendants
    assert {"Rebel", "Rescue"}.isdisjoint(names(timeline=empire.prime))
    # The page itself stays reachable.
    assert api.get(rebel.json()["entity"]["id"]).status_code == 200
    # A timeline of another dimension, or a missing one, is refused.
    other = api.make("dimension", "Elsewhere")
    response = api.client.post(url, params={"timeline": other["ext"]["prime_timeline_id"]},
                               json={"kind": "character", "name": "Stray", **home})  # fmt: skip
    assert problem(response, 422, "validation_error")["errors"][0]["path"] == "timeline"


def test_trashing_a_branch_takes_its_contents_along(api: LinkApi, empire: Empire) -> None:
    survives = empire.survives["id"]
    exile = empire.branch("Exile", at(250), parent=survives)
    rescue = empire.event("Rescue", 210, timeline=survives)
    # Nothing in it: trashed without confirmation.
    lonely = empire.branch("Lonely", at(50))
    assert api.delete(lonely["id"]).status_code == 200
    # With contents: the request must confirm, and learns what goes along.
    refused = problem(api.delete(survives), 409, "cascade_required")
    assert [d["name"] for d in refused["context"]["descendants"]] == ["Exile"]
    assert [e["name"] for e in refused["context"]["entities"]] == ["Rescue"]
    assert refused["context"]["records"] == {"events": 1}
    response = api.client.delete(f"{api.base}/entities/{survives}", params={"cascade": "true"})
    assert response.status_code == 200, response.json()
    for entity_id in (survives, exile["id"], rescue["id"]):
        assert api.get(entity_id).json()["deleted_at"] is not None
    # A descendant comes back with its parent, not alone.
    problem(api.restore(exile["id"]), 409, "conflict")
    assert api.restore(survives).status_code == 200
    for entity_id in (survives, exile["id"], rescue["id"]):
        assert api.get(entity_id).json()["deleted_at"] is None
    # The prime still can't be trashed on its own.
    problem(api.delete(empire.prime), 409, "conflict")
