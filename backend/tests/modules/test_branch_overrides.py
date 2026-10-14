"""Branch overrides (``time-model.md`` §4.4, ``recurrence.md`` §6, #115): what each record type
may change after the branch point, nested overrides (the closest timeline wins), anchors seeing
the override of their own timeline, keeping overrides in step with their root, and reverting.

The Empire (prime): the Reign 100 to 300, the Coronation at 100, the Assassination at 200.
"Survives" branches at the Assassination (200); "Exile" branches from it at 250.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules
from tests.modules.test_branches import Empire, at


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class World(Empire):
    def __init__(self, api: LinkApi) -> None:
        super().__init__(api)
        self.exile = self.branch("Exile", at(250), parent=self.survives["id"])

    def override(self, record_type: str, root_id: str, timeline: str, **changes: Any) -> Any:
        return self.api.client.post(
            f"{self.api.base}/m/branches/overrides",
            json={
                "record_type": record_type,
                "root_id": root_id,
                "timeline_id": timeline,
                "changes": changes,
            },
        )

    def made(self, *args: Any, **changes: Any) -> dict[str, Any]:
        response = self.override(*args, **changes)
        assert response.status_code == 201, response.json()
        body: dict[str, Any] = response.json()
        return body

    def revert(self, record_type: str, override_id: str) -> Any:
        return self.api.client.delete(
            f"{self.api.base}/m/branches/overrides/{record_type}/{override_id}"
        )

    def window(self, timeline: str) -> dict[str, tuple[str, str]]:
        response = self.api.client.get(
            f"{self.api.base}/timelines/{timeline}/window",
            params={"from": "0", "to": "1000", "px": 1000},
        )
        assert response.status_code == 200, response.json()
        return {i["name"]: (i["start_t"], i["end_t"]) for i in response.json()["items"]}


@pytest.fixture
def world(api: LinkApi) -> World:
    return World(api)


def end(t: int) -> dict[str, Any]:
    return {"kind": "time_point", "time_point": at(t)}


def test_event_overrides_and_the_closest_timeline(api: LinkApi, world: World) -> None:
    reign, survives, exile = world.reign["id"], world.survives["id"], world.exile["id"]
    shortened = world.made("event", reign, survives, end=end(250))
    assert world.window(world.prime)["Reign"] == ("100", "300")
    assert world.window(survives)["Reign"] == ("100", "250")
    assert world.window(exile)["Reign"] == ("100", "250")  # inherited from its parent
    # A nested override wins in its own timeline only.
    world.made("event", reign, exile, end=end(280))
    assert world.window(exile)["Reign"] == ("100", "280")
    assert world.window(survives)["Reign"] == ("100", "250")
    # Overriding again updates the same row.
    again = world.made("event", reign, survives, end=end(260))
    assert again["id"] == shortened["id"]
    assert world.window(survives)["Reign"] == ("100", "260")
    # Reverting: the branch sees the inherited record again.
    reverted = world.revert("event", shortened["id"])
    assert reverted.status_code == 200, reverted.json()
    assert world.window(survives)["Reign"] == ("100", "300")
    assert world.window(world.prime)["Reign"] == ("100", "300")


def test_what_an_event_override_may_change(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]

    def refused(response: Any, path: str) -> None:
        errors = problem(response, 422, "validation_error")["errors"]
        assert errors[0]["path"] == path, errors

    refused(world.override("event", world.reign["id"], survives, start=at(50)), "changes.start")
    # Before the branch point: the shared past.
    refused(world.override("event", world.reign["id"], survives, end=end(150)), "changes.end")
    # Not spanning the branch point: ended before it, or starting at or after it.
    refused(world.override("event", world.coronation["id"], survives, end=end(250)), "root_id")
    refused(world.override("event", world.assassination["id"], survives, end=end(250)), "root_id")
    # The branch's own events are edited directly; the prime has nothing to override.
    rescue = world.event("Rescue", 210, 220, timeline=survives)
    refused(world.override("event", rescue["id"], survives, end=end(230)), "root_id")
    refused(world.override("event", world.reign["id"], world.prime, end=end(250)), "timeline_id")
    refused(world.override("segment", world.reign["id"], survives, end=end(250)), "record_type")
    # Ending exactly at the branch point is how a branch removes a record.
    world.made("event", world.reign["id"], survives, end=end(200))
    assert world.window(survives)["Reign"] == ("100", "200")


def test_anchors_see_the_override_of_their_timeline(api: LinkApi, world: World) -> None:
    survives, reign = world.survives["id"], world.reign["id"]
    after_reign = {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": reign, "slot": "end"},
            "offset": {"kind": "base", "units": "5"},
        },
        "precision": "base",
    }
    home = {"dimension_id": world.dimension["id"]}
    mourning = api.make("event", "Mourning", ext={"start": after_reign}, **home)
    jubilee = api.make(
        "event", "Jubilee", ext={"start": after_reign, "timeline_id": survives}, **home
    )
    assert api.get(jubilee["id"]).json()["ext"]["start_t"] == "305"
    override = world.made("event", reign, survives, end=end(250))
    # The branch's own event follows the branch's Reign; the prime's doesn't move.
    assert api.get(jubilee["id"]).json()["ext"]["start_t"] == "255"
    assert api.get(mourning["id"]).json()["ext"]["start_t"] == "305"
    # Moving the override moves them again; reverting brings back the inherited end.
    world.made("event", reign, survives, end=end(240))
    assert api.get(jubilee["id"]).json()["ext"]["start_t"] == "245"
    assert world.revert("event", override["id"]).status_code == 200
    assert api.get(jubilee["id"]).json()["ext"]["start_t"] == "305"


def test_overrides_follow_their_roots_start(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    world.made("event", world.reign["id"], survives, end=end(250))
    reign = api.get(world.reign["id"]).json()
    moved = api.patch(reign, ext={"start": at(120)})
    assert moved.status_code == 200, moved.json()
    assert world.window(survives)["Reign"] == ("120", "250")
    findings = api.client.get(
        f"{api.base}/consistency/findings", params={"rule": "branches.override_start_changed"}
    ).json()
    assert findings["items"] == []


def test_fact_and_link_overrides(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    home = {"dimension_id": world.dimension["id"]}
    emperor = api.make("character", "Emperor", **home)
    heir = api.make("character", "Heir", **home)
    response = api.client.post(
        f"{api.base}/entities/{emperor['id']}/facts",
        json={
            "field_key": "core.exists",
            "timeline_id": world.prime,
            "valid_from": at(50),
            "valid_to": at(300),
        },
    )
    lifespan = response.json()["fact"]
    link = api.made_link(
        "characters.rival_of",
        heir,
        emperor,
        timeline_id=world.prime,
        valid_from=at(100),
        valid_to=at(300),
        role="pretender",
    )

    def existence(timeline: str, t: int) -> str:
        found = api.client.get(
            f"{api.base}/entities/{emperor['id']}/state",
            params={"timeline": timeline, "at": str(t)},
        ).json()
        value: str = found["existence"]
        return value

    # The emperor dies earlier in the branch.
    fact = world.made("fact", lifespan["id"], survives, valid_to=at(230))
    assert existence(survives, 240) == "not_exists"
    assert existence(world.prime, 240) == "exists"
    # Facts list the override in the branch, the root elsewhere.
    listed = api.client.get(
        f"{api.base}/entities/{emperor['id']}/facts", params={"timeline": survives}
    ).json()["items"]
    assert [(f["id"], f["valid_to_t"]) for f in listed] == [(fact["id"], "230")]
    refused = world.override("fact", lifespan["id"], survives, valid_from=at(60))
    assert problem(refused, 422, "validation_error")["errors"][0]["path"] == "changes.valid_from"
    # The override changes through the module only; deleting its root takes it along.
    patched = api.client.patch(f"{api.base}/facts/{fact['id']}", json={"revision": 1, "note": "x"})
    problem(patched, 422, "validation_error")
    # Links: the rivalry ends early in the branch, with another role.
    world.made("link", link["id"], survives, valid_to=at(220), role="exile")

    def rivals(timeline: str, t: int) -> list[str | None]:
        found = api.client.get(
            f"{api.base}/entities/{emperor['id']}/links",
            params={"timeline": timeline, "at": str(t)},
        ).json()
        return [item["link"]["role"] for item in found["items"]]

    assert rivals(world.prime, 250) == ["pretender"]
    assert rivals(survives, 210) == ["exile"]
    assert rivals(survives, 250) == []
    assert api.client.delete(f"{api.base}/facts/{lifespan['id']}").status_code == 200
    listed = api.client.get(
        f"{api.base}/entities/{emperor['id']}/facts", params={"timeline": survives}
    ).json()["items"]
    assert listed == []


def test_series_overrides(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    rule = {"kind": "interval", "every": "50", "limit": {"kind": "never"}}
    festival = api.make(
        "event",
        "Festival",
        dimension_id=world.dimension["id"],
        ext={"start": at(0), "recurrence": rule},
    )

    def starts(timeline: str) -> list[str]:
        response = api.client.get(
            f"{api.base}/events/{festival['id']}/occurrences",
            params={"from": "0", "to": "500", "timeline": timeline},
        )
        assert response.status_code == 200, response.json()
        return [o["start_t"] for o in response.json()["items"]]

    assert starts(survives)[-1] == "450"
    # Abolished in the branch: the last occurrence is the one before the branch point.
    abolished = {**rule, "limit": {"kind": "until", "until": at(199)}}
    world.made("event", festival["id"], survives, recurrence=abolished)
    assert starts(survives) == ["0", "50", "100", "150"]
    assert starts(world.prime)[-1] == "450"
    # Only the limit and new exclusions after the branch point may change.
    faster = {**rule, "every": "25"}
    refused = world.override("event", festival["id"], survives, recurrence=faster)
    problem(refused, 422, "validation_error")
    early = {**rule, "limit": {"kind": "until", "until": at(120)}}
    problem(
        world.override("event", festival["id"], survives, recurrence=early), 422, "validation_error"
    )


def test_notes_per_timeline(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    emperor = api.make("character", "Emperor", dimension_id=world.dimension["id"])
    url = f"{api.base}/m/branches/notes/{emperor['id']}/{survives}"
    empty = api.client.get(url).json()
    assert (empty["body"], empty["revision"]) == (None, 0)
    body = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "He lives."}]}],
    }
    saved = api.client.put(url, json={"body": body, "revision": 0})
    assert saved.status_code == 200, saved.json()
    assert saved.json()["revision"] == 1
    assert api.client.get(url).json()["body"] == body
    # Edits check the revision; an empty body deletes the note.
    problem(api.client.put(url, json={"body": body, "revision": 0}), 409, "revision_conflict")
    assert api.client.put(url, json={"body": body, "revision": 1}).json()["revision"] == 2
    gone = api.client.put(url, json={"body": None, "revision": 2})
    assert gone.json()["revision"] == 0
    assert api.client.get(url).json()["body"] is None
    # Prime timelines have the page itself; branch-only entities only in their lineage.
    prime = f"{api.base}/m/branches/notes/{emperor['id']}/{world.prime}"
    problem(api.client.get(prime), 422, "validation_error")
    rescuer = api.client.post(
        f"{api.base}/entities",
        params={"timeline": world.exile["id"]},
        json={"kind": "character", "name": "Rescuer", "dimension_id": world.dimension["id"]},
    ).json()["entity"]
    problem(
        api.client.get(f"{api.base}/m/branches/notes/{rescuer['id']}/{survives}"), 404, "not_found"
    )
    assert (
        api.client.get(
            f"{api.base}/m/branches/notes/{rescuer['id']}/{world.exile['id']}"
        ).status_code
        == 200
    )


def test_diff_against_the_parent(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    world.made("event", world.reign["id"], survives, end=end(250))
    rescue = world.event("Rescue", 210, 220, timeline=survives)
    world.event("Regency", 150, 400)

    def diff(timeline: str, **params: Any) -> dict[str, Any]:
        response = api.client.get(f"{api.base}/m/branches/timelines/{timeline}/diff", params=params)
        assert response.status_code == 200, response.json()
        body: dict[str, Any] = response.json()
        return body

    found = diff(survives)
    assert found["against_id"] == world.prime
    assert [r["entity_id"] for r in found["created"]] == [rescue["id"]]
    [overridden] = found["overridden"]
    assert (overridden["entity_id"], overridden["name"]) == (world.reign["id"], "Reign")
    assert overridden["root_id"] is not None
    assert overridden["before"] == {"end_t": "300"}
    assert overridden["after"] == {"end_t": "250"}
    assert [r["name"] for r in found["inherited_spanning"]] == ["Regency"]
    assert not found["truncated"]
    # Exile (at 250) inherits Regency; Rescue ended and Survives' Reign ends at its point.
    nested = diff(world.exile["id"])
    assert nested["against_id"] == survives
    assert [r["name"] for r in nested["inherited_spanning"]] == ["Regency"]
    assert diff(survives, limit=1)["truncated"] is False
    problem(
        api.client.get(f"{api.base}/m/branches/timelines/{world.prime}/diff"),
        422,
        "validation_error",
    )


def test_branch_records_in_the_shared_past(api: LinkApi, world: World) -> None:
    survives = world.survives["id"]
    plot = world.event("Plot", 150, 210, timeline=survives)
    world.event("Rescue", 210, 220, timeline=survives)

    def findings() -> list[dict[str, Any]]:
        response = api.client.get(
            f"{api.base}/consistency/findings", params={"rule": "core.branch.shared_past_modified"}
        )
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    [finding] = findings()
    assert [s["id"] for s in finding["subjects"]] == [plot["id"]], finding
    assert (finding["severity"], finding["timeline_id"]) == ("warning", survives)
    # Overrides start where their root does: never a finding.
    world.made("event", world.reign["id"], survives, end=end(250))
    assert len(findings()) == 1
