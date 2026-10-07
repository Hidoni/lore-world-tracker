"""The timeline window (``api.md`` §2, ``frontend.md`` §9.2): overlap semantics, LOD, density
buckets, filters, visibility and the cache (decisions of 2026-10-06/07 in
``lore.core.time.window``)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.core.history import recorder
from lore.core.time.cache import WINDOWS
from lore.core.time.window import bucket_bounds
from tests.entity_api import LinkApi, invalid, make_client, problem


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


def at(t: int, precision: str = "base", approximate: bool = False) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision,
            "approximate": approximate}  # fmt: skip


def event(
    api: LinkApi, world: dict[str, Any], name: str, start: int, end: int | None = None, **body: Any
) -> dict[str, Any]:
    ext: dict[str, Any] = {"start": at(start), **body.pop("ext", {})}
    if end is not None:
        ext["end"] = {"kind": "time_point", "time_point": at(end)}
    return api.make("event", name, dimension_id=world["dimension"]["id"], ext=ext, **body)


def window(api: LinkApi, world: dict[str, Any], start: int, end: int, px: int = 1000,
           **params: Any) -> dict[str, Any]:  # fmt: skip
    response = api.client.get(
        f"{api.base}/timelines/{world['prime']}/window",
        params={"from": str(start), "to": str(end), "px": px, **params},
    )
    assert response.status_code == 200, response.json()
    found: dict[str, Any] = response.json()
    return found


def names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


def test_overlap_is_half_open(api: LinkApi, world: dict[str, Any]) -> None:
    event(api, world, "Instant at from", 100)
    event(api, world, "Instant at to", 200)
    event(api, world, "Ends at from", 50, 100)
    event(api, world, "Starts at to", 200, 300)
    event(api, world, "Spans it", 0, 1000)
    event(api, world, "Inside", 120, 130)
    event(api, world, "Starts before", 90, 101)
    page = window(api, world, 100, 200)
    assert names(page) == ["Spans it", "Starts before", "Instant at from", "Inside"]
    assert (page["total"], page["culled"], page["buckets"]) == (4, 0, [])
    assert names(window(api, world, 200, 201)) == ["Spans it", "Starts at to", "Instant at to"]


def test_items(api: LinkApi, world: dict[str, Any]) -> None:
    calendar = world["calendar"]
    war = event(api, world, "War", 0, 100, ext={"importance": 5, "category": "war"})
    event(api, world, "Battle", 10, parent_id=war["id"])
    anchor = {"kind": "calendar", "calendar_id": calendar["id"], "fields": {"year": "1"}}
    dated = {"anchor": anchor, "precision": "year", "approximate": True}
    api.make("event", "Era", dimension_id=world["dimension"]["id"],
             ext={"start": dated, "end": {"kind": "unknown"}})  # fmt: skip
    items = {item["name"]: item for item in window(api, world, 0, 1000)["items"]}
    assert items["War"] == {
        **items["War"],
        "entity_id": war["id"],
        "start_t": "0",
        "end_t": "100",
        "importance": 5,
        "category": "war",
        "has_children": True,
        "parent_id": None,
        "start_precision": "base",
        "end_kind": "time_point",
        "end_precision": "base",
        "time_status": "ok",
    }
    assert items["War"]["row_id"] != war["id"]
    assert (items["Battle"]["parent_id"], items["Battle"]["end_kind"]) == (war["id"], "instant")
    era = items["Era"]
    assert (era["start_precision"], era["start_approximate"], era["end_kind"]) == (
        "year", True, "unknown"
    )  # fmt: skip
    assert era["end_precision"] is None


def test_lod_keeps_importance_then_duration_then_start(api: LinkApi, world: dict[str, Any]) -> None:
    def make(name: str, importance: int, start: int, end: int) -> None:
        event(api, world, name, start, end, ext={"importance": importance})

    make("Minor long", 1, 0, 900)
    make("Major short", 5, 500, 501)
    make("Mid long", 3, 100, 400)
    make("Mid short", 3, 50, 60)
    make("Mid short later", 3, 70, 80)
    assert names(window(api, world, 0, 1000, px=1)) == ["Major short"]
    assert names(window(api, world, 0, 1000, px=2)) == ["Mid long", "Major short"]
    # Equal importance and duration: the earlier start first.
    three = window(api, world, 0, 1000, px=3)
    assert names(three) == ["Mid short", "Mid long", "Major short"]
    assert (three["total"], three["culled"]) == (5, 2)
    assert len(window(api, world, 0, 1000, px=10_000)["items"]) == 5


def test_buckets(api: LinkApi, world: dict[str, Any]) -> None:
    """starts: each culled event once, by its start clamped to the window; active: every bucket
    it covers (decided 2026-10-07)."""
    assert bucket_bounds(0, 100, 8) == [0, 50, 100]
    assert bucket_bounds(0, 3, 4000) == [0, 1, 2, 3]  # at most one bucket per base unit
    for i in range(12):  # px 12 keeps 12 items: these
        event(api, world, f"Kept {i:02d}", 350 + i, ext={"importance": 5})
    event(api, world, "Old era", 0, 300)  # began before the window, lasts into bucket 2
    event(api, world, "Early", 110, 120)
    event(api, world, "Late instant", 399)
    event(api, world, "Ends at a bound", 150, 200)  # active in bucket 1 only
    # Window [100, 400), px 12: 3 buckets of 100.
    page = window(api, world, 100, 400, px=12)
    assert names(page) == [f"Kept {i:02d}" for i in range(12)]
    assert page["buckets"] == [
        {"from": "100", "to": "200", "starts": 3, "active": 3},
        {"from": "200", "to": "300", "starts": 0, "active": 1},
        {"from": "300", "to": "400", "starts": 1, "active": 1},
    ]
    assert sum(b["starts"] for b in page["buckets"]) == page["culled"] == 4


def test_filters(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    war = event(api, world, "War", 0, 500, ext={"importance": 4, "category": "war"},
                tags=["Canon", "Big"])  # fmt: skip
    battle = event(api, world, "Battle", 10, 20, parent_id=war["id"], ext={"category": "battle"},
                   tags=["Canon"])  # fmt: skip
    event(api, world, "Skirmish", 12, 13, parent_id=battle["id"])
    event(api, world, "Feast", 30, 40, ext={"category": "feast"})
    ana, bob = api.make("gadget", "Ana", **home), api.make("gadget", "Bob", **home)
    api.made_link("core.participant", battle, ana)
    api.made_link("core.participant", war, bob)

    def filtered(**params: Any) -> list[str]:
        return names(window(api, world, 0, 1000, **params))

    assert filtered(min_importance=4) == ["War"]
    assert filtered(category=["battle", "feast"]) == ["Battle", "Feast"]
    tags = {t["name"]: t["id"] for t in api.get(war["id"]).json()["tags"]}
    assert filtered(tag=[tags["Canon"]]) == ["War", "Battle"]
    assert filtered(tag=[tags["Canon"], tags["Big"]]) == ["War"]  # all required
    assert filtered(participant=[ana["id"], bob["id"]]) == ["War", "Battle"]  # any
    assert filtered(participant=[ana["id"]]) == ["Battle"]
    assert filtered(parent=war["id"]) == ["Battle", "Skirmish"]  # every depth
    assert filtered(parent=battle["id"]) == ["Skirmish"]


def test_readers(api: LinkApi, world: dict[str, Any]) -> None:
    home = {"dimension_id": world["dimension"]["id"]}
    plot = event(api, world, "Plot", 0, 100, visibility="private")
    event(api, world, "Aftermath", 10, parent_id=plot["id"])
    spy = api.make("gadget", "Spy", visibility="private", **home)
    open_event = event(api, world, "Open", 20)
    api.made_link("core.participant", open_event, spy)
    reader: dict[str, Any] = {"as_reader": "true"}
    page = window(api, world, 0, 1000, **reader)
    assert [(i["name"], i["parent_id"]) for i in page["items"]] == [
        ("Aftermath", None),
        ("Open", None),
    ]
    assert page["total"] == 2
    assert names(window(api, world, 0, 1000, participant=[spy["id"]], **reader)) == []
    assert names(window(api, world, 0, 1000, participant=[spy["id"]])) == ["Open"]
    url = f"{api.base}/timelines/{world['prime']}/window"
    hidden_parent = api.client.get(
        url, params={"from": "0", "to": "10", "px": 10, "parent": plot["id"], **reader}
    )
    problem(hidden_parent, 404, "not_found")


def test_bad_requests(api: LinkApi, world: dict[str, Any]) -> None:
    url = f"{api.base}/timelines/{world['prime']}/window"
    assert invalid(api.client.get(url, params={"from": "5", "to": "5", "px": 10})) == ["to"]
    bad: list[dict[str, Any]] = [
        {"from": "-1", "to": "5", "px": 10},
        {"from": "0", "to": "5", "px": 0},
        {"from": "0", "to": "5", "px": 10, "min_importance": 6},
    ]
    for params in bad:
        problem(api.client.get(url, params=params), 422, "validation_error")
    calendar = world["calendar"]["id"]
    problem(
        api.client.get(f"{api.base}/timelines/{calendar}/window",
                       params={"from": "0", "to": "5", "px": 10}),
        404,
        "not_found",
    )  # fmt: skip


def test_writes_invalidate_the_cache(api: LinkApi, world: dict[str, Any]) -> None:
    first = event(api, world, "First", 10)
    assert names(window(api, world, 0, 100)) == ["First"]
    hits = WINDOWS.hits
    assert names(window(api, world, 0, 100)) == ["First"]
    assert WINDOWS.hits == hits + 1
    api.patch(first, ext={"start": at(500)})
    assert names(window(api, world, 0, 100)) == []
    event(api, world, "Second", 20)
    assert names(window(api, world, 0, 100)) == ["Second"]
    api.delete(first["id"])
    assert names(window(api, world, 0, 1000)) == ["Second"]
