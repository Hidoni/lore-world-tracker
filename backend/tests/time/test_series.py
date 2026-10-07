"""Recurring series (``recurrence.md`` §1, §2, §4, §5.5, §9; R-REC-1…4): the rule in an
event's ``ext``, its validation and time slots, the cached series bounds and their propagation,
occurrences in the timeline window and ``GET /events/{id}/occurrences``."""

import time
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.history import recorder
from lore.core.maintenance import check_vault, reindex_vault
from lore.core.time.cache import WINDOWS
from lore.core.vaults import VaultManager
from tests.entity_api import DIMENSION_EXT, YEARS, LinkApi, invalid, make_client, problem

DAY = 86_400
YEAR = 365 * DAY
MONTH = 30 * DAY
FAR = 10**100  # D of the far world, in seconds

# Days of 86,400 s, months of 30 days, years of 12 months; year 1 starts at t = 0.
MONTHS: dict[str, Any] = {
    "schema_version": 1,
    "levels": [
        {"id": "day", "label": "Day", "plural": "Days"},
        {"id": "month", "label": "Month", "plural": "Months"},
        {"id": "year", "label": "Year", "plural": "Years"},
    ],
    "regimes": [
        {
            "id": "default",
            "name": "Default",
            "templates": {
                "day": {"level": "day", "uniform": {"count": "86400"}},
                "month": {"level": "month", "uniform": {"count": "30", "template": "day"}},
                "year": {"level": "year", "uniform": {"count": "12", "template": "month"}},
            },
            "top": {"pattern": {"kind": "fixed", "template": "year"}},
            "alignment": {
                "fields": {"year": "1"},
                "at": {"anchor": {"kind": "absolute", "t": "0"}, "precision": "year"},
            },
        }
    ],
}


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    WINDOWS.clear()
    with make_client(tmp_path) as client:
        yield LinkApi(client)


def make_world(api: LinkApi, duration: int = 10**12, definition: Any = YEARS) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria", ext={**DIMENSION_EXT, "duration": str(duration)})
    calendar = api.make(
        "calendar", "Reckoning", dimension_id=dimension["id"], ext={"definition": definition}
    )
    prime = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    return {"dimension": dimension, "calendar": calendar, "prime": prime}


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    return make_world(api)


def at(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def after(event: dict[str, Any], units: int, slot: str = "start") -> dict[str, Any]:
    return {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": event["id"], "slot": slot},
            "offset": {"kind": "base", "units": str(units)},
        },
        "precision": "base",
    }


def lasting(units: int) -> dict[str, Any]:
    return {"kind": "duration", "duration": {"kind": "base", "units": str(units)}}


def never() -> dict[str, Any]:
    return {"kind": "never"}


def count(n: int) -> dict[str, Any]:
    return {"kind": "count", "count": str(n)}


def until(point: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "until", "until": point}


def every(units: int, limit: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    return {"kind": "interval", "every": str(units), "limit": limit or never(), **more}


def calendar_rule(
    world: dict[str, Any], level: str, limit: dict[str, Any] | None = None, **more: Any
) -> dict[str, Any]:
    return {"kind": "calendar", "calendar_id": world["calendar"]["id"],
            "freq": {"level": level}, "limit": limit or never(), **more}  # fmt: skip


def series(
    api: LinkApi, world: dict[str, Any], rule: dict[str, Any], name: str = "Festival", **ext: Any
) -> dict[str, Any]:
    ext.setdefault("start", at(0))
    return api.make(
        "event", name, dimension_id=world["dimension"]["id"], ext={**ext, "recurrence": rule}
    )


def ext_of(api: LinkApi, entity: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity["id"]).json()["ext"]
    return found


def bounds(api: LinkApi, entity: dict[str, Any]) -> tuple[str | None, str | None]:
    ext = ext_of(api, entity)
    return ext["series_start_t"], ext["series_end_t"]


def occurrences(api: LinkApi, entity: dict[str, Any], start: int, end: int,
                limit: int | None = None) -> Any:  # fmt: skip
    params: dict[str, Any] = {"from": str(start), "to": str(end)}
    if limit is not None:
        params["limit"] = limit
    return api.client.get(f"{api.base}/events/{entity['id']}/occurrences", params=params)


def starts(api: LinkApi, entity: dict[str, Any], start: int, end: int) -> list[int]:
    response = occurrences(api, entity, start, end)
    assert response.status_code == 200, response.json()
    return [int(item["start_t"]) for item in response.json()["items"]]


def window(api: LinkApi, world: dict[str, Any], start: int, end: int, px: int = 1000,
           **params: Any) -> dict[str, Any]:  # fmt: skip
    response = api.client.get(
        f"{api.base}/timelines/{world['prime']}/window",
        params={"from": str(start), "to": str(end), "px": px, **params},
    )
    assert response.status_code == 200, response.json()
    found: dict[str, Any] = response.json()
    return found


def patch(api: LinkApi, entity: dict[str, Any], **ext: Any) -> Any:
    return api.patch(api.get(entity["id"]).json(), ext=ext)


# --- the rule and its bounds -------------------------------------------------------------------


def test_series_reads_and_bounds(api: LinkApi, world: dict[str, Any]) -> None:
    plain = api.make("event", "Plain", dimension_id=world["dimension"]["id"],
                     ext={"start": at(5)})  # fmt: skip
    assert (ext_of(api, plain)["recurrence"], bounds(api, plain)) == (None, (None, None))
    comet = series(api, world, every(1000, count(3)), end=lasting(10), start=at(500))
    ext = ext_of(api, comet)
    assert ext["recurrence"] == {"schema_version": 1, "kind": "interval", "every": "1000",
                                 "limit": {"kind": "count", "count": "3"},
                                 "exclusions": []}  # fmt: skip
    assert bounds(api, comet) == ("500", "2510")  # the third occurrence ends at 2,510
    forever = series(api, world, every(DAY))
    assert bounds(api, forever) == ("0", str(10**12))  # never: up to D
    # Same position as the start in every year (its offset in the year included).
    late = series(api, world, calendar_rule(world, "year", count(2)), start=at(YEAR + 1))
    assert bounds(api, late) == (str(YEAR + 1), str(2 * YEAR + 1))
    # No occurrence at all: no bounds.
    none = series(api, world, every(10, count(1), exclusions=[{"from": at(0), "to": at(1)}]))
    assert bounds(api, none) == (None, None)


def test_rule_validation(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}

    def create(rule: Any, **ext: Any) -> Any:
        return api.create("event", **home, ext={"start": at(DAY), "recurrence": rule, **ext})

    assert invalid(create({"kind": "interval", "every": "0", "limit": never()})) == [
        "ext.recurrence.interval.every"
    ]
    end = {"kind": "time_point", "time_point": at(2 * DAY)}
    body = problem(create(every(DAY), end=end), 422, "validation_error")
    assert [(e["path"], e["code"]) for e in body["errors"]] == [
        ("ext.end", "rule.series_end_not_duration")
    ]
    foreign = make_world(api)["calendar"]["id"]
    unknown = {**calendar_rule(world, "year"), "calendar_id": foreign}
    assert problem(create(unknown), 422, "validation_error")["errors"][0]["path"] == (
        "ext.recurrence.calendar_id"
    )
    early = problem(create(every(DAY, until(at(0)))), 422, "validation_error")
    assert early["errors"][0] == {**early["errors"][0], "path": "ext.recurrence.limit.until",
                                  "code": "rule.until_before_start"}  # fmt: skip
    beyond = problem(create(every(DAY, until(at(10**12 + 1)))), 422, "validation_error")
    assert beyond["errors"][0]["path"] == "ext.recurrence.limit.until"
    backwards = every(DAY, exclusions=[{"from": at(5 * DAY), "to": at(4 * DAY)}])
    assert problem(create(backwards), 422, "validation_error")["errors"][0]["code"] == (
        "rule.bad_exclusion"
    )
    bad_level = calendar_rule(world, "month")
    assert problem(create(bad_level), 422, "validation_error")["errors"][0]["code"] == (
        "rule.bad_freq_level"
    )
    # A calendar duration of a calendar rule uses the rule's calendar.
    other = api.make("calendar", "Other", ext={"definition": YEARS}, **home)
    in_other = {"kind": "duration", "duration": {"kind": "calendar", "calendar_id": other["id"],
                                                 "amounts": {"day": "1"}, "sign": 1}}  # fmt: skip
    body = problem(create(calendar_rule(world, "year"), end=in_other), 422, "validation_error")
    assert body["errors"][0]["path"] == "ext.end.duration.calendar_id"
    # A warning (the start isn't an occurrence) doesn't refuse the rule.
    assert create(calendar_rule(world, "year")).status_code == 201
    # Patching the end of a series is validated against its rule.
    comet = series(api, world, every(DAY))
    assert invalid(patch(api, comet, end=end)) == ["ext.end"]


def test_changing_and_removing_the_rule(api: LinkApi, world: dict[str, Any]) -> None:
    anchor = api.make("event", "Anchor", dimension_id=world["dimension"]["id"],
                      ext={"start": at(10 * DAY)})  # fmt: skip
    comet = series(api, world, every(DAY, until(after(anchor, 0))))
    assert bounds(api, comet) == ("0", str(10 * DAY))
    assert patch(api, comet, recurrence=every(2 * DAY, count(2))).status_code == 200
    assert bounds(api, comet) == ("0", str(2 * DAY))
    # The old until slot is no longer anchored: moving the anchor changes nothing.
    assert patch(api, anchor, start=at(20 * DAY)).status_code == 200
    assert bounds(api, comet) == ("0", str(2 * DAY))
    assert patch(api, comet, recurrence=None).status_code == 200
    assert (ext_of(api, comet)["recurrence"], bounds(api, comet)) == (None, (None, None))
    assert occurrences(api, comet, 0, DAY).status_code == 409


# --- propagation -------------------------------------------------------------------------------


def test_bounds_follow_anchors(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    founding = api.make("event", "Founding", **home, ext={"start": at(YEAR)})
    fall = api.make("event", "Fall", **home, ext={"start": at(5 * YEAR)})
    gap = [{"from": after(founding, YEAR), "to": after(founding, 2 * YEAR)}]
    rule = calendar_rule(world, "year", until(after(fall, 0)), exclusions=gap)
    feast = series(api, world, rule, start=after(founding, 0), end=lasting(DAY))
    assert bounds(api, feast) == (str(YEAR), str(5 * YEAR + DAY))
    assert starts(api, feast, 0, 10 * YEAR) == [YEAR, 3 * YEAR, 4 * YEAR, 5 * YEAR]
    # Moving the until anchor moves the series' end; moving the start moves everything.
    assert patch(api, fall, start=at(7 * YEAR)).status_code == 200
    assert bounds(api, feast) == (str(YEAR), str(7 * YEAR + DAY))
    assert patch(api, founding, start=at(2 * YEAR)).status_code == 200
    assert bounds(api, feast) == (str(2 * YEAR), str(7 * YEAR + DAY))
    assert starts(api, feast, 0, 10 * YEAR) == [2 * YEAR, 4 * YEAR, 5 * YEAR, 6 * YEAR, 7 * YEAR]
    # A move that would put the until before the start is refused.
    refused = problem(patch(api, fall, start=at(YEAR)), 422, "time_constraint")
    assert [(r["id"], r["slot"], r["code"]) for r in refused["context"]["records"]] == [
        (feast["id"], "recurrence", "rule.until_before_start")
    ]
    assert bounds(api, feast) == (str(2 * YEAR), str(7 * YEAR + DAY))


def test_bounds_follow_calendar_and_duration_changes(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    epoch = api.make("event", "Epoch", **home, ext={"start": at(0)})
    aligned = deepcopy(YEARS)
    aligned["regimes"][0]["alignment"]["at"] = after(epoch, 0)
    calendar = api.make("calendar", "Aligned", **home, ext={"definition": aligned})
    first_day = {"path": [{"level": "day", "values": ["1"]}]}
    rule = {**calendar_rule(world, "year", count(3), select=first_day),
            "calendar_id": calendar["id"]}  # fmt: skip
    yearly = series(api, world, rule)
    forever = series(api, world, every(DAY), name="Dawn")
    assert bounds(api, yearly) == ("0", str(2 * YEAR))  # the third (instant) occurrence
    # Moving the calendar's alignment moves the occurrences it places: day 1 of each year now
    # starts at 100 + k·YEAR, and the start's time of day (86,300 s into its day) is kept.
    assert patch(api, epoch, start=at(100)).status_code == 200
    assert bounds(api, yearly) == (str(DAY), str(2 * YEAR + DAY))
    # A calendar a series uses is edited through proposals, like one dates are typed in.
    shorter = deepcopy(YEARS)
    shorter["regimes"][0]["templates"]["year"]["uniform"]["count"] = "360"
    edited = api.patch(api.get(calendar["id"]).json(), ext={"definition": shorter})
    assert problem(edited, 409, "conflict")["context"]["dependents"] == 1
    dimension = api.get(world["dimension"]["id"]).json()
    response = api.patch(dimension, ext={"duration": str(10**13)})
    assert response.status_code == 200, response.json()
    assert bounds(api, forever) == ("0", str(10**13))


def test_purging_an_anchor_freezes_the_rule(api: LinkApi, world: dict[str, Any]) -> None:
    fall = api.make("event", "Fall", dimension_id=world["dimension"]["id"],
                    ext={"start": at(5 * DAY)})  # fmt: skip
    gap = [{"from": after(fall, -2 * DAY), "to": after(fall, -DAY)}]
    comet = series(api, world, every(DAY, until(after(fall, 0)), exclusions=gap))
    api.delete(fall["id"])
    assert ext_of(api, comet)["time_status"] == "trashed_ref"
    assert api.delete(fall["id"], purge=True).status_code == 200
    limit = ext_of(api, comet)["recurrence"]["limit"]
    assert limit["until"]["anchor"] == {"kind": "absolute", "t": str(5 * DAY)}
    assert limit["until"]["frozen_from"]["anchor"]["kind"] == "relative"
    exclusion = ext_of(api, comet)["recurrence"]["exclusions"][0]
    assert (exclusion["from"]["anchor"]["t"], exclusion["to"]["anchor"]["t"]) == (
        str(3 * DAY), str(4 * DAY)
    )  # fmt: skip
    assert bounds(api, comet) == ("0", str(5 * DAY))
    assert starts(api, comet, 0, 10 * DAY) == [0, DAY, 2 * DAY, 4 * DAY, 5 * DAY]


def test_undo(api: LinkApi, world: dict[str, Any]) -> None:
    comet = series(api, world, every(DAY, count(3)))
    assert patch(api, comet, recurrence=every(DAY, count(10))).status_code == 200
    assert bounds(api, comet) == ("0", str(9 * DAY))
    latest = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    undone = api.client.post(f"{api.base}/changes/{latest['id']}/revert")
    assert undone.status_code == 200, undone.json()
    assert bounds(api, comet) == ("0", str(2 * DAY))
    assert ext_of(api, comet)["recurrence"]["limit"] == count(3)


def test_vault_check_and_reindex(api: LinkApi, world: dict[str, Any]) -> None:
    fall = api.make("event", "Fall", dimension_id=world["dimension"]["id"],
                    ext={"start": at(5 * DAY)})  # fmt: skip
    comet = series(api, world, every(DAY, until(after(fall, 0)),
                                     exclusions=[{"from": after(fall, -DAY),
                                                  "to": after(fall, 0)}]))  # fmt: skip
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    assert check_vault(manager, api.vault).problems == ()
    assert manager.module_registry is not None
    reindex_vault(manager.open(api.vault), manager.module_registry)
    assert check_vault(manager, api.vault).problems == ()
    assert bounds(api, comet) == ("0", str(5 * DAY))
    assert starts(api, comet, 0, 10 * DAY) == [0, DAY, 2 * DAY, 3 * DAY, 5 * DAY]


# --- occurrences -------------------------------------------------------------------------------


def test_limits_are_honored(api: LinkApi, world: dict[str, Any]) -> None:
    counted = series(api, world, every(DAY, count(3)))
    assert starts(api, counted, 0, 100 * DAY) == [0, DAY, 2 * DAY]
    inclusive = series(api, world, every(DAY, until(at(3 * DAY))))
    assert starts(api, inclusive, 0, 100 * DAY) == [0, DAY, 2 * DAY, 3 * DAY]
    gap = [{"from": at(DAY), "to": at(DAY + 1)}]
    excluded = series(api, world, every(DAY, count(3), exclusions=gap))
    assert starts(api, excluded, 0, 100 * DAY) == [0, 2 * DAY]  # excluded ones use up the count


def test_occurrences_endpoint(api: LinkApi, world: dict[str, Any]) -> None:
    comet = series(api, world, every(1000), end=lasting(10), start=at(500))
    page = occurrences(api, comet, 1000, 3600).json()
    assert page == {
        "items": [{"key": str(k), "start_t": str(k * 1000 + 500), "end_t": str(k * 1000 + 510),
                   "number": k + 1, "entity_id": None, "state": None} for k in (1, 2, 3)],
        "truncated": False,
        "estimated_count": None,
    }  # fmt: skip
    assert occurrences(api, comet, 0, 10**6, limit=10).json() == {
        "items": [], "truncated": True, "estimated_count": "1000"
    }  # fmt: skip
    assert invalid(occurrences(api, comet, 5, 5)) == ["to"]
    plain = api.make("event", "Plain", dimension_id=world["dimension"]["id"],
                     ext={"start": at(0)})  # fmt: skip
    problem(occurrences(api, plain, 0, 10), 409, "not_a_series")
    assert occurrences(api, world["calendar"], 0, 10).status_code == 404


def test_far_windows_are_fast(api: LinkApi) -> None:
    world = make_world(api, duration=FAR, definition=MONTHS)
    yearly = series(api, world, calendar_rule(world, "year"), name="Yearly")
    tenth = {"path": [{"level": "day", "values": ["10"]}]}
    monthly = series(api, world, calendar_rule(world, "month", select=tenth), name="Monthly")
    interval = series(api, world, every(7 * DAY), name="Weekly")
    year = 12 * MONTH
    far = 10**90 * year
    began = time.perf_counter()
    assert starts(api, yearly, far, far + 3 * year) == [far, far + year, far + 2 * year]
    assert starts(api, monthly, far, far + 2 * MONTH) == [far + 9 * DAY, far + MONTH + 9 * DAY]
    weekly = starts(api, interval, far, far + 14 * DAY)
    assert len(weekly) == 2
    assert all((t % (7 * DAY)) == 0 and far <= t < far + 14 * DAY for t in weekly)
    page = window(api, world, far, far + 3 * year)
    assert sorted(i["name"] for i in page["items"]).count("Yearly") == 3
    assert time.perf_counter() - began < 2  # no iteration from the series start
    near = starts(api, monthly, 0, 3 * MONTH)
    assert near == [9 * DAY, MONTH + 9 * DAY, 2 * MONTH + 9 * DAY]


# --- the window --------------------------------------------------------------------------------


def test_window_occurrences_are_items(api: LinkApi, world: dict[str, Any]) -> None:
    api.make("event", "Battle", dimension_id=world["dimension"]["id"],
             ext={"start": at(1500), "importance": 5})  # fmt: skip
    comet = series(api, world, every(1000, count(5)), end=lasting(10), name="Comet",
                   importance=2, category="sky")  # fmt: skip
    page = window(api, world, 900, 3100)
    assert [(i["name"], i["occurrence_key"], i["start_t"], i["end_t"]) for i in page["items"]] == [
        ("Comet", "1", "1000", "1010"),
        ("Battle", None, "1500", "1500"),
        ("Comet", "2", "2000", "2010"),
        ("Comet", "3", "3000", "3010"),
    ]
    occurrence = page["items"][0]
    assert (occurrence["entity_id"], occurrence["importance"], occurrence["category"],
            occurrence["end_kind"]) == (comet["id"], 2, "sky", "duration")  # fmt: skip
    assert (page["total"], page["culled"], page["series_bands"]) == (4, 0, [])
    # The series row itself isn't an item (its first occurrence is, when in the window).
    assert [i["occurrence_key"] for i in window(api, world, 0, 500)["items"]] == ["0"]
    # LOD: occurrences are ranked and culled like events.
    culled = window(api, world, 900, 3100, px=3)
    assert [i["occurrence_key"] for i in culled["items"]] == ["1", None, "2"]  # earliest first
    assert culled["culled"] == sum(b["starts"] for b in culled["buckets"]) == 1
    # More occurrences than the budget: a band.
    banded = window(api, world, 900, 3100, px=2)
    assert ([i["name"] for i in banded["items"]], banded["culled"]) == (["Battle"], 0)
    assert [(b["name"], b["estimated_count"]) for b in banded["series_bands"]] == [("Comet", "3")]
    # Filters and include_series.
    assert [i["name"] for i in window(api, world, 900, 3100, include_series=False)["items"]] == [
        "Battle"
    ]
    assert window(api, world, 900, 3100, category="sky")["total"] == 3
    assert window(api, world, 900, 3100, min_importance=3)["total"] == 1
    # Outside the series' bounds: no candidates.
    assert window(api, world, 5000, 9000)["total"] == 0


def test_dense_windows_become_bands(api: LinkApi, world: dict[str, Any]) -> None:
    daily = series(api, world, every(DAY), name="Dawn", start=at(10 * DAY))
    page = window(api, world, 0, 100_000 * DAY, px=100)
    assert (page["items"], page["total"]) == ([], 0)
    assert page["series_bands"] == [
        {"entity_id": daily["id"], "row_id": page["series_bands"][0]["row_id"], "name": "Dawn",
         "visibility": "public", "importance": 3, "category": None, "from": str(10 * DAY),
         "to": str(100_000 * DAY), "estimated_count": str(100_000 - 10)}
    ]  # fmt: skip
    yearly = series(api, world, calendar_rule(world, "year"), name="New Year")
    page = window(api, world, 0, 10**12, px=100)
    names = {band["name"]: int(band["estimated_count"]) for band in page["series_bands"]}
    assert names["New Year"] == 10**12 // YEAR + 1
    assert yearly["id"] in {band["entity_id"] for band in page["series_bands"]}
    # Zoomed in, the same series are occurrences.
    assert len(window(api, world, 0, 50 * DAY, px=1000)["items"]) == 41
