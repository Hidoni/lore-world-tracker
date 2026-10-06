"""Events (``time-model.md`` §5.5, §9.1-§9.4; R-EVT-1…5, R-DIM-5): the kind's ``ext``, time
specs and propagation, sub-events, causes and participants, the event tree and history."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.history import recorder
from tests.entity_api import LinkApi, invalid, make_client, problem

DAY = 86_400
YEAR = 365 * DAY


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path) as client:
        yield LinkApi(client)


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    calendar = api.calendar(dimension["id"])
    return {"dimension": dimension, "calendar": calendar, "prime": prime_of(api, dimension)}


def prime_of(api: LinkApi, dimension: dict[str, Any]) -> str:
    prime: str = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    return prime


def at(t: int, precision: str = "base") -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision}


def after(event: dict[str, Any], units: int, slot: str = "start") -> dict[str, Any]:
    return {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": event["id"], "slot": slot},
            "offset": {"kind": "base", "units": str(units)},
        },
        "precision": "base",
    }


def in_year(calendar: dict[str, Any], year: int) -> dict[str, Any]:
    fields = {"year": str(year)}
    return {"anchor": {"kind": "calendar", "calendar_id": calendar["id"], "fields": fields},
            "precision": "year"}  # fmt: skip


def lasting(units: int) -> dict[str, Any]:
    return {"kind": "duration", "duration": {"kind": "base", "units": str(units)}}


def event(api: LinkApi, world: dict[str, Any], name: str = "Event", **ext: Any) -> dict[str, Any]:
    body: dict[str, Any] = {k: ext.pop(k) for k in ("parent_id", "visibility") if k in ext}
    ext.setdefault("start", at(0))
    return api.make("event", name, dimension_id=world["dimension"]["id"], ext=ext, **body)


def ext_of(api: LinkApi, entity: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity["id"]).json()["ext"]
    return found


def times(api: LinkApi, *entities: dict[str, Any]) -> list[tuple[str, str]]:
    return [(ext_of(api, e)["start_t"], ext_of(api, e)["end_t"]) for e in entities]


def fresh(api: LinkApi, entity: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity["id"]).json()
    return found


# --- creating and reading --------------------------------------------------------------------


def test_defaults_and_reads(api: LinkApi, world: dict[str, Any]) -> None:
    created = event(api, world, "Founding", start=at(YEAR, "year"))
    ext = created["ext"]
    assert ext["timeline_id"] == world["prime"]
    assert ext["end"] == {"kind": "instant"}  # decided 2026-10-06
    assert (ext["start_t"], ext["end_t"], ext["time_status"]) == (str(YEAR), str(YEAR), "ok")
    assert (ext["importance"], ext["category"]) == (3, None)
    assert ext["display"] == {
        "calendar_id": world["calendar"]["id"],
        "start": ext["display"]["start"],
        "end": ext["display"]["end"],
    }
    assert ext["display"]["start"]
    assert "2" in ext["display"]["start"]  # year 2


@pytest.mark.parametrize(
    ("end", "expected_end"),
    [
        ({"kind": "time_point", "time_point": at(5 * DAY)}, 5 * DAY),
        (lasting(DAY), 2 * DAY),
        ({"kind": "instant"}, DAY),
        ({"kind": "end_of_time"}, 10**12),
        ({"kind": "unknown"}, DAY),
    ],
)
def test_end_kinds(
    api: LinkApi, world: dict[str, Any], end: dict[str, Any], expected_end: int
) -> None:
    created = event(api, world, start=at(DAY), end=end)
    assert created["ext"]["end_t"] == str(expected_end)
    assert created["ext"]["end"]["kind"] == end["kind"]
    if end["kind"] == "unknown":
        assert created["ext"]["display"]["end"] == "?"


def test_anchor_kinds(api: LinkApi, world: dict[str, Any]) -> None:
    calendar = world["calendar"]
    a_year = {"kind": "calendar", "calendar_id": calendar["id"], "amounts": {"year": "1"},
              "sign": 1}  # fmt: skip
    end = {"kind": "duration", "duration": a_year}
    dated = event(api, world, "Dated", start=in_year(calendar, 3), end=end)
    assert (dated["ext"]["start_t"], dated["ext"]["end_t"]) == (str(2 * YEAR), str(3 * YEAR))
    relative = event(api, world, "Later", start=after(dated, DAY, "end"))
    assert relative["ext"]["start_t"] == str(3 * YEAR + DAY)


def test_category_and_importance(api: LinkApi, world: dict[str, Any]) -> None:
    created = event(api, world, importance=5, category="battle")
    assert (created["ext"]["importance"], created["ext"]["category"]) == (5, "battle")
    updated = api.patch(created, ext={"importance": 1, "category": None}).json()["entity"]
    assert (updated["ext"]["importance"], updated["ext"]["category"]) == (1, None)
    bad: dict[str, Any]
    for bad in ({"importance": 0}, {"importance": 6}, {"category": ""}, {"recurrence": {}}):
        assert invalid(api.patch(updated, ext=bad))[0].startswith("ext.")


def test_invalid_specs(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    assert invalid(api.create("event", **home, ext={})) == ["ext.start"]
    assert invalid(api.create("event", **home, ext={"start": {"anchor": {}}}))[0].startswith(
        "ext.start"
    )
    beyond = problem(api.create("event", **home, ext={"start": at(10**12 + 1)}), 422,
                     "validation_error")  # fmt: skip
    assert beyond["errors"][0] == {**beyond["errors"][0], "path": "ext.start",
                                   "code": "out_of_bounds"}  # fmt: skip
    day_999 = {"anchor": {"kind": "calendar", "calendar_id": world["calendar"]["id"],
                          "fields": {"year": "1", "day": "999"}}, "precision": "day"}  # fmt: skip
    bad_date = api.create("event", **home, ext={"start": day_999})
    assert problem(bad_date, 422, "invalid_date")["errors"][0]["path"].startswith("ext.start")
    early_end = api.create(
        "event", **home, ext={"start": at(DAY), "end": {"kind": "time_point",
                                                        "time_point": at(0)}}
    )  # fmt: skip
    problem(early_end, 422, "time_constraint")
    other = api.make("dimension", "Other")
    api.calendar(other["id"])
    elsewhere = api.create(
        "event", **home, ext={"start": at(0), "timeline_id": prime_of(api, other)}
    )
    assert invalid(elsewhere) == ["ext.timeline_id"]


def test_patch_rules(api: LinkApi, world: dict[str, Any]) -> None:
    created = event(api, world, start=at(DAY))
    for member in ("start", "end", "importance"):
        assert invalid(api.patch(created, ext={member: None})) == [f"ext.{member}"]
    assert invalid(api.patch(created, ext={"timeline_id": world["calendar"]["id"]})) == [
        "ext.timeline_id"
    ]
    same = api.patch(created, ext={"timeline_id": world["prime"], "end": lasting(DAY)})
    assert same.status_code == 200, same.json()
    assert same.json()["entity"]["ext"]["end_t"] == str(2 * DAY)


def test_dimension_needs_a_live_calendar(api: LinkApi) -> None:
    """R-DIM-5 (decided 2026-10-06: a calendar in the trash doesn't count)."""
    dimension = api.make("dimension")
    home = {"dimension_id": dimension["id"], "ext": {"start": at(0)}}
    body = problem(api.create("event", **home), 422, "dimension_has_no_calendar")
    assert body["errors"][0]["path"] == "dimension_id"
    calendar = api.calendar(dimension["id"])
    assert api.create("event", **home).status_code == 201
    assert api.delete(calendar["id"]).status_code == 200
    problem(api.create("event", **home), 422, "dimension_has_no_calendar")


# --- propagation -----------------------------------------------------------------------------


def test_moving_an_anchor_event_moves_its_dependents(api: LinkApi, world: dict[str, Any]) -> None:
    battle = event(api, world, "Battle", start=at(10 * DAY), end=lasting(3 * DAY))
    funeral = event(api, world, "Funeral", start=after(battle, 3 * DAY, "end"), end=lasting(DAY))
    wake = event(api, world, "Wake", start=after(funeral, 0, "end"))
    assert times(api, funeral, wake) == [(str(16 * DAY), str(17 * DAY)), (str(17 * DAY),) * 2]
    moved = api.patch(battle, ext={"start": at(20 * DAY)})
    assert moved.status_code == 200, moved.json()
    assert times(api, funeral, wake) == [(str(26 * DAY), str(27 * DAY)), (str(27 * DAY),) * 2]
    longer = api.patch(fresh(api, battle), ext={"end": lasting(10 * DAY)})
    assert longer.status_code == 200, longer.json()
    assert times(api, wake) == [(str(34 * DAY),) * 2]


def test_cycles_are_refused(api: LinkApi, world: dict[str, Any]) -> None:
    a = event(api, world, "A", start=at(DAY))
    b = event(api, world, "B", start=after(a, DAY))
    body = problem(api.patch(a, ext={"start": after(b, DAY)}), 409, "time_cycle")
    assert len(body["context"]["path"]) == 3
    own = problem(api.patch(fresh(api, b), ext={"start": after(b, 0, "end")}), 409, "time_cycle")
    assert own["context"]["path"][0].startswith("event")


def test_moves_that_break_dependents_are_refused(api: LinkApi, world: dict[str, Any]) -> None:
    a = event(api, world, "A", start=at(DAY))
    event(api, world, "B", start=after(a, -DAY))
    body = problem(api.patch(a, ext={"start": at(0)}), 422, "time_constraint")
    assert body["context"]["records"][0]["code"] == "out_of_bounds"
    assert ext_of(api, a)["start_t"] == str(DAY)


def test_trash_and_purge_of_an_anchor_event(api: LinkApi, world: dict[str, Any]) -> None:
    a = event(api, world, "A", start=at(DAY))
    b = event(api, world, "B", start=after(a, DAY))
    api.delete(a["id"])
    assert ext_of(api, b)["time_status"] == "trashed_ref"
    api.restore(a["id"])
    assert ext_of(api, b)["time_status"] == "ok"
    api.delete(a["id"])
    assert api.delete(a["id"], purge=True).status_code == 200
    frozen = ext_of(api, b)
    assert (frozen["start"]["anchor"], frozen["start_t"], frozen["time_status"]) == (
        {"kind": "absolute", "t": str(2 * DAY)}, str(2 * DAY), "ok"
    )  # fmt: skip
    assert frozen["start"]["frozen_from"]["anchor"]["kind"] == "relative"


# --- sub-events, causes and participants ------------------------------------------------------


def test_parents(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    war = event(api, world, "War", start=at(0), end=lasting(YEAR))
    battle = event(api, world, "Battle", parent_id=war["id"])
    assert battle["parent_id"] == war["id"]
    folder = api.make("misc", **home)
    filed = event(api, world, "Filed", parent_id=folder["id"])
    assert filed["parent_id"] == folder["id"]
    gadget = api.make("gadget", **home)
    problem(api.patch(battle, parent_id=gadget["id"]), 422, "parent_not_allowed")
    moved = api.patch(battle, parent_id=filed["id"])
    assert moved.status_code == 200, moved.json()


def test_causes(api: LinkApi, world: dict[str, Any]) -> None:
    cause, effect = event(api, world, "Cause"), event(api, world, "Effect")
    link = api.made_link("core.causes", cause, effect, data={"description": "it led to it"})
    assert link["data"] == {"description": "it led to it"}
    problem(api.link("core.causes", cause, effect), 409, "conflict")  # one per pair
    assert api.link("core.causes", effect, cause).status_code == 201
    assert invalid(api.link("core.causes", cause, effect, data={"why": "x"}))[0].startswith("data")
    gadget = api.make("gadget", dimension_id=world["dimension"]["id"])
    problem(api.link("core.causes", cause, gadget), 422, "link_type_not_allowed")
    problem(api.link("core.causes", cause, cause), 422, "validation_error")


def test_participants(api: LinkApi, world: dict[str, Any]) -> None:
    battle = event(api, world, "Battle")
    gadget = api.make("gadget", dimension_id=world["dimension"]["id"])
    beast = api.make("beast", dimension_id=world["dimension"]["id"])
    first = api.made_link("core.participant", battle, gadget, role="attacker")
    assert first["role"] == "attacker"
    assert api.link("core.participant", battle, gadget, role="witness").status_code == 201
    api.made_link("core.participant", battle, beast, data={"segment_id": "s1"})
    assert invalid(api.link("core.participant", battle, beast, data={"rank": 1}))[0].startswith(
        "data"
    )
    problem(api.link("core.participant", gadget, battle), 422, "link_type_not_allowed")
    problem(
        api.link("core.participant", battle, beast, valid_from=at(0), timeline_id=world["prime"]),
        422,
        "validation_error",
    )


# --- the event tree --------------------------------------------------------------------------


def tree(api: LinkApi, timeline: str, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/timelines/{timeline}/event-tree", params=params)
    assert response.status_code == 200, response.json()
    found: dict[str, Any] = response.json()
    return found


def names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


def test_event_tree(api: LinkApi, world: dict[str, Any]) -> None:
    prime = world["prime"]
    home = {"dimension_id": world["dimension"]["id"]}
    war = event(api, world, "War", start=at(10), end=lasting(100))
    event(api, world, "Battle 10", start=at(20), parent_id=war["id"])
    event(api, world, "Battle 2", start=at(20), parent_id=war["id"])
    event(api, world, "Siege", start=at(20), end=lasting(5), parent_id=war["id"])
    event(api, world, "Treaty", start=at(5))
    event(api, world, "Peace", start=at(10), end=lasting(500))  # same start, longer: first
    folder = api.make("misc", **home)
    event(api, world, "Filed", start=at(1), parent_id=folder["id"])  # a root
    gone = event(api, world, "Gone", start=at(2))
    event(api, world, "Orphan", start=at(3), parent_id=gone["id"])
    api.delete(gone["id"])  # its child becomes a root

    roots = tree(api, prime)
    assert names(roots) == ["Filed", "Orphan", "Treaty", "Peace", "War"]
    assert [i["has_children"] for i in roots["items"]] == [False, False, False, False, True]
    war_node = roots["items"][-1]
    assert (war_node["start_t"], war_node["end_t"], war_node["importance"]) == ("10", "110", 3)
    assert war_node["display"]["calendar_id"] == world["calendar"]["id"]
    # Same start: the longer first, then by name (numbers by value).
    assert names(tree(api, prime, parent=war["id"])) == ["Siege", "Battle 2", "Battle 10"]

    pages, cursor = [], None
    while True:
        page = tree(api, prime, limit=2, **({"cursor": cursor} if cursor else {}))
        pages.append(names(page))
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == [["Filed", "Orphan"], ["Treaty", "Peace"], ["War"]]

    bad = api.client.get(f"{api.base}/timelines/{prime}/event-tree", params={"cursor": "x!"})
    assert invalid(bad) == ["cursor"]
    for not_found in (
        f"{api.base}/timelines/{war['id']}/event-tree",
        f"{api.base}/timelines/{world['dimension']['id']}/event-tree",
    ):
        problem(api.client.get(not_found), 404, "not_found")
    problem(
        api.client.get(f"{api.base}/timelines/{prime}/event-tree", params={"parent": folder["id"]}),
        404,
        "not_found",
    )


def test_event_tree_for_readers_hides_private_events(api: LinkApi, world: dict[str, Any]) -> None:
    plot = event(api, world, "Plot", start=at(1), visibility="private")
    event(api, world, "Aftermath", start=at(2), parent_id=plot["id"])
    url = f"{api.base}/timelines/{world['prime']}/event-tree"
    page = api.client.get(url, params={"as_reader": "true"}).json()
    assert [(i["name"], i["parent_id"]) for i in page["items"]] == [("Aftermath", None)]
    assert names(tree(api, world["prime"])) == ["Plot"]


# --- history ---------------------------------------------------------------------------------


def changes(api: LinkApi, limit: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = api.client.get(
        f"{api.base}/changes", params={"limit": limit}
    ).json()["items"]
    return items


def test_changesets_and_undo(api: LinkApi, world: dict[str, Any]) -> None:
    a = event(api, world, "A", start=at(DAY))
    detail = api.client.get(f"{api.base}/changes/{changes(api)[0]['id']}").json()
    assert {c["table_name"] for c in detail["changes"]} == {"entities", "events"}
    b = event(api, world, "B", start=after(a, DAY))
    api.patch(a, ext={"start": at(5 * DAY)})
    moved = api.client.get(f"{api.base}/changes/{changes(api)[0]['id']}").json()
    assert sorted(e["name"] for e in moved["entities"]) == ["A", "B"]  # the dependent too
    undone = api.client.post(f"{api.base}/changes/{changes(api)[0]['id']}/revert")
    assert undone.status_code == 200, undone.json()
    assert times(api, a, b) == [(str(DAY),) * 2, (str(2 * DAY),) * 2]
    created = changes(api, 4)[-1]
    assert api.client.post(f"{api.base}/changes/{created['id']}/revert").status_code == 409
