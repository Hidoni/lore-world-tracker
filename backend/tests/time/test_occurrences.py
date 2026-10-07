"""Materialized occurrences (``recurrence.md`` §3, §7; ``time-model.md`` §5.2; R-REC-5, R-EVT-2):
get-or-create, modify, cancel, revert, occurrence anchors, sub-events of occurrences, and merging
with the computed occurrences in the window and the occurrences list."""

from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.history import recorder
from lore.core.time.cache import WINDOWS
from tests.entity_api import YEARS, LinkApi, make_client, problem

DAY = 86_400
YEAR = 365 * DAY


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    WINDOWS.clear()
    with make_client(tmp_path) as client:
        yield LinkApi(client)


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    calendar = api.calendar(dimension["id"])
    prime = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    return {"dimension": dimension, "calendar": calendar, "prime": prime}


def at(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def to_occurrence(series: dict[str, Any], key: str, units: int = 0,
                  slot: str = "start") -> dict[str, Any]:  # fmt: skip
    return {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": series["id"], "slot": slot, "occurrence": key},
            "offset": {"kind": "base", "units": str(units)},
        },
        "precision": "base",
    }


def make_event(api: LinkApi, world: dict[str, Any], name: str, **ext: Any) -> dict[str, Any]:
    body = {k: ext.pop(k) for k in ("parent_id",) if k in ext}
    ext.setdefault("start", at(0))
    return api.make("event", name, dimension_id=world["dimension"]["id"], ext=ext, **body)


def daily(api: LinkApi, world: dict[str, Any], name: str = "Dawn", **ext: Any) -> dict[str, Any]:
    """Every day from 0 (100 occurrences), lasting an hour."""
    rule = {"kind": "interval", "every": str(DAY), "limit": {"kind": "count", "count": "100"}}
    ext.setdefault("end", {"kind": "duration", "duration": {"kind": "base", "units": "3600"}})
    return make_event(api, world, name, recurrence=rule, **ext)


def materialize(api: LinkApi, series: dict[str, Any], key: str, status: int = 201) -> Any:
    response = api.client.post(f"{api.base}/events/{series['id']}/occurrences/{key}")
    assert response.status_code == status, response.json()
    return response.json()


def ext_of(api: LinkApi, entity_id: str) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity_id).json()["ext"]
    return found


def patch(api: LinkApi, entity_id: str, **ext: Any) -> Any:
    return api.patch(api.get(entity_id).json(), ext=ext)


def listed(api: LinkApi, series: dict[str, Any], start: int, end: int, **params: Any) -> Any:
    response = api.client.get(
        f"{api.base}/events/{series['id']}/occurrences",
        params={"from": str(start), "to": str(end), **params},
    )
    assert response.status_code == 200, response.json()
    return response.json()["items"]


def window(api: LinkApi, world: dict[str, Any], start: int, end: int,
           **params: Any) -> list[tuple[str, str | None, str]]:  # fmt: skip
    response = api.client.get(
        f"{api.base}/timelines/{world['prime']}/window",
        params={"from": str(start), "to": str(end), "px": 1000, **params},
    )
    assert response.status_code == 200, response.json()
    return [(i["name"], i["occurrence_key"], i["start_t"]) for i in response.json()["items"]]


def test_materialize_is_get_or_create(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world, importance=4, category="sky")
    created = materialize(api, series, "3")["entity"]
    assert created["name"] == "Dawn (4 1)"
    ext = created["ext"]
    assert (ext["series_id"], ext["occurrence_key"], ext["occurrence_state"]) == (
        series["id"], "3", "referenced"
    )  # fmt: skip
    assert (ext["start_t"], ext["end_t"], ext["original_start_t"]) == (
        str(3 * DAY), str(3 * DAY + 3600), str(3 * DAY)
    )  # fmt: skip
    assert (ext["occurrence_number"], ext["importance"], ext["category"]) == (4, 4, "sky")
    assert ext["start"]["anchor"]["ref"] == {"type": "event", "id": series["id"],
                                             "slot": "start", "occurrence": "3"}  # fmt: skip
    again = materialize(api, series, "3", status=200)
    assert again["entity"]["id"] == created["id"]
    problem(api.client.post(f"{api.base}/events/{series['id']}/occurrences/100"), 404,
            "occurrence_not_found")  # fmt: skip
    problem(api.client.post(f"{api.base}/events/{series['id']}/occurrences/03"), 422,
            "validation_error")  # fmt: skip
    plain = make_event(api, world, "Plain")
    problem(api.client.post(f"{api.base}/events/{plain['id']}/occurrences/0"), 409,
            "not_a_series")  # fmt: skip
    # Through the entity API too, but only once per key.
    duplicate = api.create("event", dimension_id=world["dimension"]["id"],
                           ext={"series_id": series["id"], "occurrence_key": "3"})  # fmt: skip
    assert problem(duplicate, 409, "occurrence_exists")["context"]["entity_id"] == created["id"]
    recurring = patch(api, created["id"], recurrence={"kind": "interval", "every": "5",
                                                      "limit": {"kind": "never"}})  # fmt: skip
    assert recurring.status_code == 422
    assert patch(api, created["id"], occurrence_key="4").status_code == 422


def test_window_and_list_merge_materialized_occurrences(
    api: LinkApi, world: dict[str, Any]
) -> None:
    series = daily(api, world)
    first = materialize(api, series, "1")["entity"]
    assert window(api, world, 0, 3 * DAY) == [
        ("Dawn", "0", "0"), ("Dawn (2 1)", "1", str(DAY)), ("Dawn", "2", str(2 * DAY))
    ]  # fmt: skip
    items = listed(api, series, 0, 3 * DAY)
    assert [(i["key"], i["number"], i["entity_id"], i["state"]) for i in items] == [
        ("0", 1, None, None), ("1", 2, first["id"], "referenced"), ("2", 3, None, None)
    ]  # fmt: skip
    # Modified: drawn at its own time, moving out of its window and into another.
    hour = {"kind": "duration", "duration": {"kind": "base", "units": "3600"}}
    assert patch(api, first["id"], start=at(10 * DAY), end=hour).status_code == 200
    assert ext_of(api, first["id"])["occurrence_state"] == "modified"
    assert [key for _n, key, _t in window(api, world, 0, 3 * DAY)] == ["0", "2"]
    assert window(api, world, 10 * DAY, 10 * DAY + 1) == [
        ("Dawn", "10", str(10 * DAY)), ("Dawn (2 1)", "1", str(10 * DAY))
    ]  # fmt: skip
    assert [i["key"] for i in listed(api, series, 0, 3 * DAY)] == ["0", "2"]
    assert [(i["key"], i["state"]) for i in listed(api, series, 10 * DAY, 11 * DAY)] == [
        ("1", "modified"), ("10", None)  # equal spans: by key
    ]  # fmt: skip
    # Cancelled: hidden unless asked for.
    second = materialize(api, series, "2")["entity"]
    assert patch(api, second["id"], cancelled=True).status_code == 200
    assert [key for _n, key, _t in window(api, world, 0, 3 * DAY)] == ["0"]
    assert [key for _n, key, _t in window(api, world, 0, 3 * DAY, include_cancelled=True)] == [
        "0", "2"
    ]  # fmt: skip
    cancelled = listed(api, series, 0, 3 * DAY, include_cancelled=True)
    assert [(i["key"], i["state"]) for i in cancelled] == [("0", None), ("2", "cancelled")]
    assert patch(api, second["id"], cancelled=False).status_code == 200
    assert ext_of(api, second["id"])["occurrence_state"] == "referenced"
    assert problem(patch(api, series["id"], cancelled=True), 422, "validation_error")
    # Reverting the modified one: the computed occurrence is back.
    assert api.delete(first["id"]).status_code == 200
    assert [key for _n, key, _t in window(api, world, 0, 3 * DAY)] == ["0", "1", "2"]


def test_series_edits_move_referenced_occurrences(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    third = materialize(api, series, "3")["entity"]
    assert patch(api, series["id"], start=at(500)).status_code == 200
    assert ext_of(api, third["id"])["start_t"] == str(3 * DAY + 500)
    rule = {"kind": "interval", "every": str(2 * DAY), "limit": {"kind": "never"}}
    assert patch(api, series["id"], recurrence=rule).status_code == 200
    assert ext_of(api, third["id"])["start_t"] == str(6 * DAY + 500)
    # A rule without that occurrence any more orphans it: that goes through a recurrence
    # proposal (test_recurrence_proposals.py).
    short = {"kind": "interval", "every": str(DAY), "limit": {"kind": "count", "count": "2"}}
    body = problem(patch(api, series["id"], recurrence=short), 409, "conflict")
    assert body["context"]["orphaned"] == [third["id"]]


def test_occurrence_anchors(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    feast = make_event(api, world, "Feast", start=to_occurrence(series, "5", 60),
                       end={"kind": "time_point",
                            "time_point": to_occurrence(series, "5", slot="end")})  # fmt: skip
    assert (ext_of(api, feast["id"])["start_t"], ext_of(api, feast["id"])["end_t"]) == (
        str(5 * DAY + 60), str(5 * DAY + 3600)
    )  # fmt: skip
    # A modified materialized occurrence moves what is anchored to the occurrence.
    fifth = materialize(api, series, "5")["entity"]
    two_hours = {"kind": "duration", "duration": {"kind": "base", "units": "7200"}}
    assert patch(api, fifth["id"], start=at(50 * DAY), end=two_hours).status_code == 200
    assert (ext_of(api, feast["id"])["start_t"], ext_of(api, feast["id"])["end_t"]) == (
        str(50 * DAY + 60), str(50 * DAY + 7200)
    )  # fmt: skip
    # Trashing it reverts to the computed occurrence; restoring brings the change back.
    assert api.delete(fifth["id"]).status_code == 200
    assert ext_of(api, feast["id"])["start_t"] == str(5 * DAY + 60)
    assert api.restore(fifth["id"]).status_code == 200
    assert ext_of(api, feast["id"])["start_t"] == str(50 * DAY + 60)
    # Moving the series moves computed occurrences and their anchors.
    assert api.delete(fifth["id"]).status_code == 200
    assert patch(api, series["id"], start=at(1000)).status_code == 200
    assert ext_of(api, feast["id"])["start_t"] == str(5 * DAY + 1060)
    # Keys without an occurrence don't resolve.
    missing = api.create("event", dimension_id=world["dimension"]["id"],
                         ext={"start": to_occurrence(series, "100")})  # fmt: skip
    assert problem(missing, 422, "invalid_date")["errors"][0]["code"] == "unresolved_ref"


def test_occurrence_anchors_follow_calendar_changes(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    epoch = make_event(api, world, "Epoch")
    aligned = deepcopy(YEARS)
    aligned["regimes"][0]["alignment"]["at"] = {
        "anchor": {"kind": "relative", "ref": {"type": "event", "id": epoch["id"],
                                               "slot": "start"},
                   "offset": {"kind": "base", "units": "0"}}, "precision": "base"}  # fmt: skip
    calendar = api.make("calendar", "Aligned", **home, ext={"definition": aligned})
    rule = {"kind": "calendar", "calendar_id": calendar["id"], "freq": {"level": "year"},
            "select": {"path": [{"level": "day", "values": ["1"]}]},
            "limit": {"kind": "never"}}  # fmt: skip
    series = make_event(api, world, "New Year", start=at(0), recurrence=rule)
    toast = make_event(api, world, "Toast", start=to_occurrence(series, "2"))
    assert ext_of(api, toast["id"])["start_t"] == str(2 * YEAR)
    # The calendar moves with its anchor: the occurrence (and the toast) move with it, although
    # nothing the toast is anchored to changed its own moment.
    assert patch(api, epoch["id"], start=at(DAY)).status_code == 200
    # (Year 0 now starts the series: key 2 is year 2, one year after the old year 1's start.)
    assert ext_of(api, toast["id"])["start_t"] == str(YEAR + DAY)


def test_sub_events_of_occurrences(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    fourth = materialize(api, series, "4")["entity"]
    toast = make_event(api, world, "Toast", start=at(4 * DAY + 60), parent_id=fourth["id"])
    assert api.get(toast["id"]).json()["parent_id"] == fourth["id"]
    url = f"{api.base}/events/{series['id']}/occurrences/4"
    refused = problem(api.client.delete(url), 409, "occurrence_has_sub_events")
    assert refused["context"]["sub_events"] == [toast["id"]]
    problem(api.delete(fourth["id"]), 409, "occurrence_has_sub_events")
    deleted = api.client.delete(url, params={"trash_sub_events": "true"})
    assert deleted.status_code == 200, deleted.json()
    assert api.get(toast["id"]).json()["deleted_at"] is not None
    assert api.get(fourth["id"]).json()["deleted_at"] is not None
    assert [key for _n, key, _t in window(api, world, 4 * DAY, 5 * DAY)] == ["4"]
    assert api.client.delete(url).status_code == 404
    problem(api.client.post(url), 409, "occurrence_in_trash")


def test_series_participants_are_shown(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    hero = api.make("misc", "Hero")
    api.made_link("core.participant", series, hero, role="host")
    occurrence = materialize(api, series, "0")["entity"]
    assert occurrence["ext"]["series_participants"] == [{"entity_id": hero["id"], "role": "host"}]
    plain = make_event(api, world, "Plain")
    assert ext_of(api, plain["id"])["series_participants"] == []
