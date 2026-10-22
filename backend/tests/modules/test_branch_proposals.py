"""Re-parenting and merging branches (``time-model.md`` §4.7, #158): previews, the per-record
choice for the parent's own records after the branch point, overrides merged or dropped, child
branches and branch-only entities following, branch points pinned, stale proposals and undo.

The Empire (prime): the Reign 100 to 300, the Coronation at 100, the Assassination at 200.
"Survives" branches at the Assassination (200); "Exile" branches from it at 250.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import HEADERS, LinkApi, make_client, problem
from tests.entity_modules import with_real_modules
from tests.modules.test_branch_overrides import World, end
from tests.modules.test_branches import at, start_of


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class Proposals(World):
    def propose(self, timeline: str, **body: Any) -> Any:
        return self.api.client.post(
            f"{self.api.base}/m/branches/timelines/{timeline}/proposals", json=body
        )

    def proposed(self, timeline: str, **body: Any) -> dict[str, Any]:
        response = self.propose(timeline, **body)
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()
        return found

    def apply(self, proposal: dict[str, Any], **body: Any) -> Any:
        return self.api.client.post(
            f"{self.api.base}/m/branches/timelines/{proposal['timeline_id']}/proposals/"
            f"{proposal['id']}/apply",
            json=body,
        )

    def applied(self, proposal: dict[str, Any], **body: Any) -> dict[str, Any]:
        response = self.apply(proposal, **body)
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()
        return found

    def ext(self, entity_id: str) -> dict[str, Any]:
        found: dict[str, Any] = self.api.get(entity_id).json()["ext"]
        return found


@pytest.fixture
def world(api: LinkApi) -> Proposals:
    return Proposals(api)


def names(items: list[dict[str, Any]]) -> list[tuple[str | None, str | None]]:
    return sorted((i["name"], i.get("action")) for i in items)


def test_merging_a_branch_into_the_prime(api: LinkApi, world: Proposals) -> None:
    survives, reign = world.survives["id"], world.reign["id"]
    rescue = world.event("Rescue", 210, 220, timeline=survives)
    world.made("event", reign, survives, end=end(250))
    funeral = world.event("Funeral", 230)
    proposal = world.proposed(survives, operation="merge")
    assert proposal["operation"] == "merge"
    assert proposal["parent_timeline_id"] == world.prime
    assert names(proposal["records"]) == [("Reign", "apply"), ("Rescue", "move")]
    # The prime's own records at or after the branch point: kept unless discarded.
    conflicts = {c["name"]: c for c in proposal["conflicts"]}
    assert sorted(conflicts) == ["Assassination", "Funeral"]
    assert conflicts["Funeral"]["strategies"] == ["keep", "discard"]
    assert conflicts["Funeral"]["default_strategy"] == "keep"
    # Its branch-only entities (Exile, a branch of it, among them) become the prime's.
    assert sorted((e["name"], e["to_origin_id"]) for e in proposal["entities"]) == [
        ("Exile", None), ("Rescue", None)]  # fmt: skip
    assert [(t["name"], t["to_parent_id"]) for t in proposal["timelines"]] == [
        ("Exile", world.prime)
    ]
    assert proposal["summary"]["conflicts"] == 2
    # The preview changed nothing.
    assert world.window(world.prime)["Reign"] == ("100", "300")
    assert api.get(survives).json()["deleted_at"] is None

    result = world.applied(proposal, strategies={conflicts["Funeral"]["key"]: "discard"})
    assert (result["operation"], result["discarded"]) == ("merge", 1)
    window = world.window(world.prime)
    assert window["Reign"] == ("100", "250")
    assert window["Rescue"] == ("210", "220")
    assert "Assassination" in window
    assert "Funeral" not in window
    assert api.get(funeral["id"]).json()["deleted_at"] is not None
    # The emptied branch is in the trash; its event is the prime's now.
    assert api.get(survives).json()["deleted_at"] is not None
    assert api.get(rescue["id"]).json()["origin_timeline_id"] is None
    assert world.ext(rescue["id"])["timeline_id"] == world.prime
    assert world.ext(world.exile["id"])["parent_timeline_id"] == world.prime
    assert world.window(world.exile["id"])["Rescue"] == ("210", "220")
    # The proposal is used up.
    problem(world.apply(proposal), 404, "not_found")


def test_merging_moves_child_branches_and_replaces_overrides(
    api: LinkApi, world: Proposals
) -> None:
    survives, exile, reign = world.survives["id"], world.exile["id"], world.reign["id"]
    world.made("event", reign, survives, end=end(250))
    world.made("event", reign, exile, end=end(280))
    hideout = world.event("Hideout", 260, timeline=exile)
    deeper = world.branch("Deeper", at(270), parent=exile)
    proposal = world.proposed(exile, operation="merge")
    assert proposal["parent_timeline_id"] == survives
    assert names(proposal["records"]) == [("Hideout", "move"), ("Reign", "replace")]
    assert [(t["name"], t["to_parent_id"]) for t in proposal["timelines"]] == [("Deeper", survives)]
    world.applied(proposal)
    assert world.window(survives)["Reign"] == ("100", "280")
    assert world.window(survives)["Hideout"] == ("260", "260")
    assert world.window(world.prime)["Reign"] == ("100", "300")
    assert world.ext(deeper["id"])["parent_timeline_id"] == survives
    # Branch-only entities of the merged branch belong to its parent (a branch) now.
    assert api.get(hideout["id"]).json()["origin_timeline_id"] == survives
    assert api.get(deeper["id"]).json()["origin_timeline_id"] == survives
    assert world.window(deeper["id"])["Reign"] == ("100", "280")


def test_merging_fact_and_link_overrides(api: LinkApi, world: Proposals) -> None:
    survives = world.survives["id"]
    home = {"dimension_id": world.dimension["id"]}
    emperor = api.make("character", "Emperor", **home)
    lifespan = api.client.post(
        f"{api.base}/entities/{emperor['id']}/facts",
        json={"field_key": "core.exists", "timeline_id": world.prime, "valid_from": at(50),
              "valid_to": at(300)},
    ).json()["fact"]  # fmt: skip
    world.made("fact", lifespan["id"], survives, valid_to=at(230))
    world.applied(world.proposed(survives, operation="merge"))
    facts = api.client.get(
        f"{api.base}/entities/{emperor['id']}/facts", params={"timeline": world.prime}
    ).json()["items"]
    assert [(f["id"], f["valid_to_t"]) for f in facts] == [(lifespan["id"], "230")]


def test_choosing_strategies(api: LinkApi, world: Proposals) -> None:
    survives = world.survives["id"]
    world.event("Funeral", 230)
    proposal = world.proposed(survives, operation="merge")
    refused = world.apply(proposal, strategies={"event/nope": "keep"})
    assert problem(refused, 422, "validation_error")["errors"][0]["path"] == (
        "strategies.event/nope"
    )
    # Every conflict discarded by default.
    world.applied(proposal, default_strategy="discard")
    window = world.window(world.prime)
    assert "Funeral" not in window
    assert "Assassination" not in window


def test_a_stale_merge(api: LinkApi, world: Proposals) -> None:
    survives = world.survives["id"]
    proposal = world.proposed(survives, operation="merge")
    world.event("Funeral", 230)  # a new record of the prime after the branch point
    problem(world.apply(proposal), 409, "proposal_stale")
    world.applied(world.proposed(survives, operation="merge"))


def test_undoing_a_merge(api: LinkApi, world: Proposals) -> None:
    survives = world.survives["id"]
    rescue = world.event("Rescue", 210, 220, timeline=survives)
    world.made("event", world.reign["id"], survives, end=end(250))
    world.applied(world.proposed(survives, operation="merge"))
    last = api.client.get(f"{api.base}/changes").json()["items"][0]
    assert last["summary"] == "Merged the branch “Survives” into “Prime”"
    undo = api.client.post(f"{api.base}/changes/{last['id']}/revert", headers=HEADERS)
    assert undo.status_code == 200, undo.json()
    assert api.get(survives).json()["deleted_at"] is None
    assert world.window(world.prime)["Reign"] == ("100", "300")
    assert world.window(survives)["Reign"] == ("100", "250")
    assert world.ext(rescue["id"])["timeline_id"] == survives


def test_reparenting_a_branch(api: LinkApi, world: Proposals) -> None:
    survives, reign = world.survives["id"], world.reign["id"]
    regency = world.event("Regency", 210, 300, timeline=survives)
    # Exile branches 40 after the Regency starts (250) and ends both the Regency and the Reign.
    exile = world.branch("Exile2", start_of(regency, 40), parent=survives)["id"]
    world.made("event", regency["id"], exile, end=end(260))
    world.made("event", reign, exile, end=end(280))
    assert world.window(exile)["Regency"] == ("210", "260")
    proposal = world.proposed(exile, operation="reparent", parent_timeline_id=world.prime)
    # The Regency isn't the prime's: its override goes; the Reign's stays.
    assert names(proposal["records"]) == [("Regency", "drop")]
    assert [p["id"] for p in proposal["pinned"]] == [exile]
    assert [(t["id"], t["from_parent_id"], t["to_parent_id"]) for t in proposal["timelines"]] == [
        (exile, survives, world.prime)
    ]
    assert proposal["entities"] == [{"id": exile, "name": "Exile2", "to_origin_id": None}]
    world.applied(proposal)
    ext = world.ext(exile)
    assert ext["parent_timeline_id"] == world.prime
    assert ext["branch_t"] == "250"
    assert ext["branch_point"]["anchor"] == {"kind": "absolute", "t": "250"}
    window = world.window(exile)
    assert "Regency" not in window
    assert window["Reign"] == ("100", "280")
    assert api.get(exile).json()["origin_timeline_id"] is None
    # Survives keeps its own Regency.
    assert world.window(survives)["Regency"] == ("210", "300")


def test_reparenting_is_checked(api: LinkApi, world: Proposals) -> None:
    survives, exile = world.survives["id"], world.exile["id"]

    def refused(response: Any, path: str) -> None:
        errors = problem(response, 422, "validation_error")["errors"]
        assert errors[0]["path"] == path, errors

    refused(world.propose(survives, operation="reparent"), "parent_timeline_id")
    refused(world.propose(survives, operation="reparent", parent_timeline_id=exile),
            "parent_timeline_id")  # fmt: skip
    refused(world.propose(survives, operation="reparent", parent_timeline_id=survives),
            "parent_timeline_id")  # fmt: skip
    refused(world.propose(exile, operation="reparent", parent_timeline_id=survives),
            "parent_timeline_id")  # fmt: skip
    refused(world.propose(world.prime, operation="merge"), "timeline_id")
    other = api.make("dimension", "Elsewhere")["ext"]["prime_timeline_id"]
    refused(world.propose(exile, operation="reparent", parent_timeline_id=other),
            "parent_timeline_id")  # fmt: skip


def test_merging_into_a_branch_rehomes_overrides_and_moves_notes(
    api: LinkApi, world: Proposals
) -> None:
    survives, exile = world.survives["id"], world.exile["id"]
    world.made("event", world.reign["id"], exile, end=end(270))
    hero = api.make("character", "Hero", dimension_id=world.dimension["id"])
    note = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "In exile she became a pirate."}]}]}  # fmt: skip
    put = api.client.put(
        f"{api.base}/m/branches/notes/{hero['id']}/{exile}", json={"body": note, "revision": 0}
    )
    assert put.status_code == 200, put.json()
    proposal = world.proposed(exile, operation="merge")
    assert names(proposal["records"]) == [("Reign", "rehome")]
    assert proposal["summary"]["notes_moved"] == 1
    world.applied(proposal)
    assert world.window(survives)["Reign"] == ("100", "270")
    assert world.window(world.prime)["Reign"] == ("100", "300")
    moved = api.client.get(f"{api.base}/m/branches/notes/{hero['id']}/{survives}").json()
    assert moved["body"] == note
