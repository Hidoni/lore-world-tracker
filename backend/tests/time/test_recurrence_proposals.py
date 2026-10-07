"""Recurrence-rule proposals (``recurrence.md`` §8, ``time-model.md`` §7.5, R-REC-6): statuses of
materialized occurrences under a rule change and every status/strategy pair, rekey conflicts,
stale proposals, undo, and direct edits that would orphan occurrences."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.history import recorder
from tests.entity_api import LinkApi, make_client, problem
from tests.time.test_occurrences import DAY, at, daily, ext_of, make_event, materialize, patch


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path) as client:
        yield LinkApi(client)


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    return {"dimension": dimension, "calendar": api.calendar(dimension["id"])}


# Every other day, 50 occurrences: key k starts at 2k days (the daily series' keys k at k days).
EVERY_OTHER = {"kind": "interval", "every": str(2 * DAY), "limit": {"kind": "count", "count": "50"}}


def propose(api: LinkApi, series: dict[str, Any], status: int = 201, **body: Any) -> Any:
    body.setdefault("rule", EVERY_OTHER)
    response = api.client.post(f"{api.base}/events/{series['id']}/recurrence/proposals", json=body)
    assert response.status_code == status, response.json()
    return response.json()


def apply(api: LinkApi, series: dict[str, Any], proposal: dict[str, Any], **strategies: str) -> Any:
    return api.client.post(
        f"{api.base}/events/{series['id']}/recurrence/proposals/{proposal['id']}/apply",
        json={"strategies": strategies},
    )


def by_key(proposal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in proposal["items"]}


def occurrences(api: LinkApi, world: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """Key → entity id of the materialized occurrences (not in the trash) of a series."""
    window = {"from": "0", "to": str(200 * DAY), "limit": "1000"}
    response = api.client.get(f"{api.base}/events/{series['id']}/occurrences", params=window)
    assert response.status_code == 200, response.json()
    return {i["key"]: i["entity_id"] for i in response.json()["items"] if i["entity_id"]}


def scenario(api: LinkApi, world: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """The daily series with materialized occurrences 0 (unchanged under ``EVERY_OTHER``), 4
    (moved; rekey → 2), 3 (moved, no rekey: nothing starts at day 3), 60 (orphaned; rekey → 30)
    and 99 (orphaned, no later occurrence)."""
    series = daily(api, world)
    ids = {
        key: materialize(api, series, key)["entity"]["id"] for key in ("0", "3", "4", "60", "99")
    }
    return series, ids


def test_statuses(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    proposal = propose(api, series)
    assert proposal["summary"] == {"unchanged": 1, "moved": 2, "orphaned": 2}
    found = by_key(proposal)
    assert [i["key"] for i in proposal["items"]] == ["0", "3", "4", "60", "99"]
    assert (found["0"]["status"], found["0"]["strategies"], found["0"]["default_strategy"]) == (
        "unchanged", [], None
    )  # fmt: skip
    moved = found["4"]
    assert (moved["entity_id"], moved["state"], moved["status"]) == (
        ids["4"],
        "referenced",
        "moved",
    )
    assert (moved["original_start_t"], moved["start_t"], moved["new_start_t"]) == (
        str(4 * DAY), str(4 * DAY), str(8 * DAY)
    )  # fmt: skip
    assert (moved["rekey_key"], moved["rekey_start_t"], moved["rekey_held_by"]) == (
        "2", str(4 * DAY), None
    )  # fmt: skip
    assert (moved["strategies"], moved["default_strategy"]) == (
        ["keep_key", "rekey", "detach"], "keep_key"
    )  # fmt: skip
    assert found["3"]["strategies"] == ["keep_key", "detach"]  # no occurrence at day 3
    orphan = found["60"]
    assert (orphan["status"], orphan["new_start_t"], orphan["rekey_key"]) == (
        "orphaned",
        None,
        "30",
    )
    assert (orphan["strategies"], orphan["default_strategy"]) == (
        ["rekey", "detach", "trash"], "detach"
    )  # fmt: skip
    assert found["99"]["strategies"] == ["detach", "trash"]
    # A preview changes nothing.
    assert ext_of(api, series["id"])["recurrence"]["every"] == str(DAY)


def test_every_status_and_strategy(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    proposal = propose(api, series)
    result = apply(api, series, proposal, **{ids["4"]: "rekey", ids["3"]: "detach",
                                            ids["60"]: "rekey", ids["99"]: "trash"})  # fmt: skip
    assert result.status_code == 200, result.json()
    body = result.json()
    assert (body["kept"], body["rekeyed"], body["detached"], body["trashed"]) == (0, 2, 1, 1)
    assert body["event"]["ext"]["recurrence"]["every"] == str(2 * DAY)
    assert set(body["affected"]["entities"]) == {series["id"], *ids.values()}
    # unchanged
    assert ext_of(api, ids["0"])["occurrence_key"] == "0"
    # moved + rekey: the occurrence at its original time
    rekeyed = ext_of(api, ids["4"])
    assert (rekeyed["occurrence_key"], rekeyed["start_t"], rekeyed["original_start_t"]) == (
        "2", str(4 * DAY), str(4 * DAY)
    )  # fmt: skip
    assert rekeyed["start"]["anchor"]["ref"]["occurrence"] == "2"
    assert rekeyed["occurrence_state"] == "referenced"
    # orphaned + rekey: the next occurrence
    later = ext_of(api, ids["60"])
    assert (later["occurrence_key"], later["start_t"], later["original_start_t"]) == (
        "30", str(60 * DAY), str(60 * DAY)
    )  # fmt: skip
    # moved + detach: a standalone event where it was
    detached = ext_of(api, ids["3"])
    assert (detached["series_id"], detached["occurrence_key"], detached["start_t"]) == (
        None, None, str(3 * DAY)
    )  # fmt: skip
    assert detached["start"]["anchor"] == {"kind": "absolute", "t": str(3 * DAY)}
    assert detached["end"]["time_point"]["anchor"] == {"kind": "absolute", "t": str(3 * DAY + 3600)}
    # orphaned + trash
    trashed = api.get(ids["99"]).json()
    assert trashed["deleted_at"] is not None
    assert trashed["ext"]["start"]["anchor"]["kind"] == "absolute"
    assert occurrences(api, world, series) == {"0": ids["0"], "2": ids["4"], "30": ids["60"]}


def test_defaults_keep_keys_and_detach_orphans(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    result = apply(api, series, propose(api, series))
    assert result.status_code == 200, result.json()
    body = result.json()
    assert (body["kept"], body["rekeyed"], body["detached"], body["trashed"]) == (2, 0, 2, 0)
    moved = ext_of(api, ids["4"])
    assert (moved["occurrence_key"], moved["start_t"]) == ("4", str(8 * DAY))  # moved with the rule
    assert moved["original_start_t"] == str(4 * DAY)
    assert ext_of(api, ids["60"])["series_id"] is None
    assert ext_of(api, ids["60"])["start_t"] == str(60 * DAY)


def test_modified_and_cancelled_occurrences(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    modified = materialize(api, series, "4")["entity"]
    assert patch(api, modified["id"], start=at(4 * DAY + 600)).status_code == 200
    cancelled = materialize(api, series, "60")["entity"]
    assert patch(api, cancelled["id"], cancelled=True).status_code == 200
    proposal = propose(api, series)
    found = by_key(proposal)
    assert (found["4"]["state"], found["4"]["status"]) == ("modified", "moved")
    assert (found["60"]["state"], found["60"]["status"]) == ("cancelled", "orphaned")
    result = apply(api, series, proposal, **{modified["id"]: "keep_key", cancelled["id"]: "rekey"})
    assert result.status_code == 200, result.json()
    assert ext_of(api, modified["id"])["start_t"] == str(4 * DAY + 600)  # its own time
    rekeyed = ext_of(api, cancelled["id"])
    assert (rekeyed["occurrence_key"], rekeyed["occurrence_state"]) == ("30", "cancelled")


def test_rekey_conflicts(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    four = materialize(api, series, "4")["entity"]
    two = materialize(api, series, "2")["entity"]  # moved to day 4 by the new rule
    proposal = propose(api, series)
    assert by_key(proposal)["4"]["rekey_held_by"] == two["id"]
    body = problem(apply(api, series, proposal, **{four["id"]: "rekey"}), 409, "rekey_conflict")
    holders = sorted([four["id"], two["id"]])
    assert body["context"]["conflicts"] == [{"key": "2", "entity_ids": holders}]
    # Freeing the key first works: 2 is detached, 4 takes its key.
    result = apply(api, series, proposal, **{four["id"]: "rekey", two["id"]: "detach"})
    assert result.status_code == 200, result.json()
    assert ext_of(api, four["id"])["occurrence_key"] == "2"
    # A key held by an occurrence in the trash counts too.
    series = daily(api, world, "Dusk")
    four = materialize(api, series, "4")["entity"]
    two = materialize(api, series, "2")["entity"]
    assert api.delete(two["id"]).status_code == 200
    proposal = propose(api, series)
    problem(apply(api, series, proposal, **{four["id"]: "rekey"}), 409, "rekey_conflict")


def test_strategy_errors(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    proposal = propose(api, series)
    wrong = problem(apply(api, series, proposal, **{ids["0"]: "detach"}), 422, "validation_error")
    assert wrong["errors"][0]["path"] == f"strategies.{ids['0']}"
    problem(apply(api, series, proposal, **{ids["3"]: "rekey"}), 422, "validation_error")
    problem(apply(api, series, proposal, **{ids["4"]: "trash"}), 422, "validation_error")
    unknown = problem(apply(api, series, proposal, **{series["id"]: "detach"}), 422,
                      "validation_error")  # fmt: skip
    assert unknown["errors"][0]["code"] == "unknown_record"


def test_trash_needs_occurrences_without_sub_events(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    orphan = materialize(api, series, "99")["entity"]
    make_event(api, world, "Toast", parent_id=orphan["id"], start=at(99 * DAY))
    proposal = propose(api, series)
    problem(apply(api, series, proposal, **{orphan["id"]: "trash"}), 409,
            "occurrence_has_sub_events")  # fmt: skip
    assert apply(api, series, proposal, **{orphan["id"]: "detach"}).status_code == 200


def test_stale_proposals(api: LinkApi, world: dict[str, Any]) -> None:
    series, _ids = scenario(api, world)
    proposal = propose(api, series)
    materialize(api, series, "7")
    problem(apply(api, series, proposal), 409, "proposal_stale")
    proposal = propose(api, series)
    assert patch(api, series["id"], importance=5).status_code == 200  # the series row changed
    problem(apply(api, series, proposal), 409, "proposal_stale")


def test_the_change_is_checked_like_a_patch(api: LinkApi, world: dict[str, Any]) -> None:
    series = daily(api, world)
    bad = propose(api, series, status=422, rule={"kind": "interval", "every": "0",
                                                 "limit": {"kind": "never"}})  # fmt: skip
    assert bad["errors"][0]["path"].startswith("rule")
    late = propose(api, series, status=422, start=at(10**13))
    assert late["errors"][0]["path"] == "start"
    occurrence = materialize(api, series, "1")["entity"]
    problem(api.client.post(f"{api.base}/events/{occurrence['id']}/recurrence/proposals",
                            json={"rule": EVERY_OTHER}), 422, "validation_error")  # fmt: skip
    # A new start moves the occurrences too.
    moved = propose(api, series, rule=None, start=at(3600))
    assert by_key(moved)["1"]["status"] == "orphaned"  # null stops the recurrence
    shifted = propose(api, series, rule={"kind": "interval", "every": str(DAY),
                                         "limit": {"kind": "never"}}, start=at(3600))  # fmt: skip
    assert (by_key(shifted)["1"]["status"], by_key(shifted)["1"]["new_start_t"]) == (
        "moved", str(DAY + 3600)
    )  # fmt: skip
    assert apply(api, series, shifted).status_code == 200
    assert ext_of(api, series["id"])["start_t"] == "3600"
    assert ext_of(api, occurrence["id"])["start_t"] == str(DAY + 3600)


def test_direct_edits_may_not_orphan_occurrences(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    body = problem(patch(api, series["id"], recurrence=EVERY_OTHER), 409, "conflict")
    assert sorted(body["context"]["orphaned"]) == sorted([ids["60"], ids["99"]])
    assert body["context"]["proposals"] == f"/events/{series['id']}/recurrence/proposals"
    problem(patch(api, series["id"], recurrence=None), 409, "conflict")
    # Moving them is fine: they keep their keys.
    never = {"kind": "interval", "every": str(2 * DAY), "limit": {"kind": "never"}}
    assert patch(api, series["id"], recurrence=never).status_code == 200
    assert ext_of(api, ids["4"])["start_t"] == str(8 * DAY)


def test_undo_restores_the_series_and_its_occurrences(api: LinkApi, world: dict[str, Any]) -> None:
    series, ids = scenario(api, world)
    before = {i: ext_of(api, i) for i in ids.values()}
    proposal = propose(api, series)
    result = apply(api, series, proposal, **{ids["4"]: "rekey", ids["99"]: "trash"})
    assert result.status_code == 200, result.json()
    changes = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"]
    revert = api.client.post(f"{api.base}/changes/{changes[0]['id']}/revert")
    assert revert.status_code == 200, revert.json()
    assert ext_of(api, series["id"])["recurrence"]["every"] == str(DAY)
    for entity_id, ext in before.items():
        after = ext_of(api, entity_id)
        assert {k: after[k] for k in ("occurrence_key", "series_id", "start", "start_t")} == {
            k: ext[k] for k in ("occurrence_key", "series_id", "start", "start_t")
        }
    assert api.get(ids["99"]).json()["deleted_at"] is None
