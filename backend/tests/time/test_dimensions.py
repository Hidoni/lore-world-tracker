"""Dimensions and prime timelines (``time-model.md`` §3, §4.1; R-DIM-1…4, R-TL-1)."""

from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from lore.core.history import recorder
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.core.time import DependencyIndex, DimensionNode, SlotDef, SlotNode, SlotProvider
from lore.core.time.slots import SlotKey, SlotMoment, SlotUpdate, SlotValue
from lore.core.vaults import VaultManager
from tests.entity_api import DIMENSION_EXT, Api, invalid, make_client, problem
from tests.entity_modules import ENTITY_MODULES

# --- a dummy module whose records have time slots, kept in memory -----------------------------


class ClockBase(DeclarativeBase):
    pass


class ClockTick(ClockBase):
    __tablename__ = "clock_ticks"  # never created: the loader and writer keep ticks in memory

    id: Mapped[str] = mapped_column(String, primary_key=True)


TICKS: dict[tuple[str, str], tuple[str, int]] = {}  # (id, slot) -> (dimension id, t)


def _load(_session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    return {
        key: SlotValue(None, TICKS[key.id, key.slot][1], None)
        for key in keys
        if (key.id, key.slot) in TICKS
    }


def _write(_session: Session, updates: Sequence[SlotUpdate]) -> None:
    for update in updates:
        dimension, _t = TICKS[update.key.id, update.key.slot]
        assert update.t is not None
        TICKS[update.key.id, update.key.slot] = (dimension, update.t)


def _beyond(_session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
    return [
        SlotMoment("clock.tick", tick_id, slot, t)
        for (tick_id, slot), (dimension, t) in TICKS.items()
        if dimension == dimension_id and t > bound
    ]


CLOCK = ModuleSpec(
    id="clock",
    name="Clock",
    description="Ticks with time slots (tests).",
    models=(ClockTick,),
    history_tables=(HistoryTable.of(ClockTick, derived=True),),
    slot_providers=(
        SlotProvider(
            "clock.tick",
            ClockTick,
            (SlotDef("at", referenceable=True), SlotDef("end", spec="end")),
            load=_load,
            write=_write,
            beyond=_beyond,
        ),
    ),
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    TICKS.clear()
    with make_client(tmp_path, modules=(*ENTITY_MODULES, CLOCK)) as client:
        yield Api(client)


def spec(duration: int | str, **more: Any) -> dict[str, Any]:
    return {**DIMENSION_EXT, "duration": str(duration), **more}


def absolute(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def prime_of(api: Api, dimension: dict[str, Any]) -> dict[str, Any]:
    response = api.get(dimension["ext"]["prime_timeline_id"])
    assert response.status_code == 200, response.json()
    prime: dict[str, Any] = response.json()
    return prime


def fresh(api: Api, entity: dict[str, Any]) -> dict[str, Any]:
    response = api.get(entity["id"])
    assert response.status_code == 200, response.json()
    current: dict[str, Any] = response.json()
    return current


def tree(api: Api, dimension_id: str, **params: Any) -> Any:
    return api.client.get(f"{api.base}/dimensions/{dimension_id}/timelines", params=params)


# --- creation -----------------------------------------------------------------------------------


def test_creating_a_dimension_creates_its_prime_timeline(api: Api) -> None:
    dimension = api.make("dimension", "Aetheria", visibility="spoiler", ext=spec(10**110))
    assert dimension["ext"] == {
        "base_unit": DIMENSION_EXT["base_unit"],
        "duration": str(10**110),
        "default_calendar_id": None,
        "present": None,
        "present_t": None,
        "time_status": None,
        "prime_timeline_id": dimension["ext"]["prime_timeline_id"],
    }
    prime = prime_of(api, dimension)
    assert (prime["kind"], prime["name"], prime["dimension_id"]) == (
        "timeline", "Prime", dimension["id"]
    )  # fmt: skip
    assert prime["visibility"] == "spoiler"  # the dimension's
    assert prime["ext"] == {
        "dimension_id": dimension["id"],
        "parent_timeline_id": None,
        "is_prime": True,
        "branch_point": None,
        "branch_t": None,
        "time_status": None,
    }

    response = tree(api, dimension["id"])
    assert response.status_code == 200, response.json()
    assert response.json() == {
        "dimension_id": dimension["id"],
        "items": [
            {
                "id": prime["id"],
                "name": "Prime",
                "visibility": "spoiler",
                "is_prime": True,
                "parent_timeline_id": None,
                "branch_point": None,
                "branch_t": None,
                "time_status": None,
                "trashed": False,
                "children": [],
            }
        ],
    }


def test_time_spec_validation(api: Api) -> None:
    assert invalid(api.create("dimension", ext=None)) == ["ext.base_unit", "ext.duration"]
    assert invalid(api.create("dimension", ext={"duration": "5"})) == ["ext.base_unit"]
    assert invalid(api.create("dimension", ext=spec(0))) == ["ext.duration"]
    assert invalid(api.create("dimension", ext=spec("-5"))) == ["ext.duration"]
    assert invalid(api.create("dimension", ext=spec("007"))) == ["ext.duration"]
    assert invalid(api.create("dimension", ext=spec(10, color="red"))) == ["ext.color"]
    unnamed = {**DIMENSION_EXT["base_unit"], "singular": ""}  # type: ignore[dict-item]
    assert invalid(api.create("dimension", ext=spec(10, base_unit=unnamed))) == [
        "ext.base_unit.singular"
    ]

    huge = "9" * 1000  # 1000 digits, the most D may have
    assert api.make("dimension", ext=spec(huge))["ext"]["duration"] == huge
    assert invalid(api.create("dimension", ext=spec("1" + "0" * 1000))) == ["ext.duration"]


def test_timelines_cant_be_created_or_configured_directly(api: Api) -> None:
    dimension = api.make("dimension")
    assert invalid(api.create("timeline", dimension_id=dimension["id"])) == ["kind"]
    prime = prime_of(api, dimension)
    assert invalid(api.patch(prime, ext={"is_prime": False})) == ["ext"]
    renamed = api.patch(prime, name="The Long Now", summary="What happened.")
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["entity"]["name"] == "The Long Now"


# --- the present moment -------------------------------------------------------------------------


def test_present_moment(api: Api) -> None:
    dimension = api.make("dimension", ext=spec(1000, present=absolute(42)))
    assert dimension["ext"]["present"] == {**absolute(42), "approximate": False}
    assert (dimension["ext"]["present_t"], dimension["ext"]["time_status"]) == ("42", "ok")

    moved = api.patch(dimension, ext={"present": absolute(1000)})
    assert moved.status_code == 200, moved.json()
    dimension = moved.json()["entity"]
    assert dimension["ext"]["present_t"] == "1000"
    assert dimension["ext"]["duration"] == "1000"  # untouched members stay

    late = problem(api.patch(dimension, ext={"present": absolute(1001)}), 422, "validation_error")
    assert [(e["path"], e["code"]) for e in late["errors"]] == [("ext.present", "out_of_bounds")]
    calendar = {
        "anchor": {"kind": "calendar", "calendar_id": "c", "fields": {"year": "1"}},
        "precision": "year",
    }
    unknown = problem(api.patch(dimension, ext={"present": calendar}), 422, "invalid_date")
    assert [(e["path"], e["code"]) for e in unknown["errors"]] == [
        ("ext.present.anchor.calendar_id", "unresolved_ref")
    ]
    relative = {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "timeline", "id": dimension["ext"]["prime_timeline_id"],
                    "slot": "branch_point"},
            "offset": {"kind": "base", "units": "0"},
        },
        "precision": "base",
    }  # fmt: skip
    anchored = problem(api.patch(dimension, ext={"present": relative}), 422, "validation_error")
    assert [(e["path"], e["code"]) for e in anchored["errors"]] == [
        ("ext.present.anchor", "not_supported")
    ]

    cleared = api.patch(dimension, ext={"present": None}).json()["entity"]
    assert (cleared["ext"]["present"], cleared["ext"]["present_t"]) == (None, None)
    assert invalid(api.patch(cleared, ext={"duration": None})) == ["ext.duration"]
    assert invalid(api.patch(cleared, ext={"base_unit": None})) == ["ext.base_unit"]


# --- duration changes (R-DIM-3) -----------------------------------------------------------------


def test_the_duration_can_shrink_only_above_every_moment(api: Api) -> None:
    dimension = api.make("dimension", ext=spec(10**30, present=absolute(500)))
    other = api.make("dimension", ext=spec(10**30))
    TICKS.update(
        {
            ("a", "at"): (dimension["id"], 700),
            ("b", "at"): (dimension["id"], 10**20),
            ("c", "at"): (other["id"], 10**25),
        }
    )

    refused = problem(api.patch(dimension, ext={"duration": "600"}), 422, "time_constraint")
    assert refused["context"]["records"] == [
        {"record_type": "clock.tick", "id": "a", "slot": "at", "t": "700"},
        {"record_type": "clock.tick", "id": "b", "slot": "at", "t": str(10**20)},
    ]
    assert {e["path"] for e in refused["errors"]} == {"ext.duration"}
    refused = problem(api.patch(dimension, ext={"duration": "499"}), 422, "time_constraint")
    assert [r["record_type"] for r in refused["context"]["records"]] == [
        "clock.tick",
        "clock.tick",
        "dimension",
    ]  # fmt: skip  (the present moment too)
    assert fresh(api, dimension)["ext"]["duration"] == str(10**30)  # nothing changed

    shrunk = api.patch(dimension, ext={"duration": str(10**20)})
    assert shrunk.status_code == 200, shrunk.json()
    grown = api.patch(shrunk.json()["entity"], ext={"duration": str(10**900)})
    assert grown.status_code == 200, grown.json()
    # moving the present along with the duration is checked against the new duration
    both = api.patch(grown.json()["entity"], ext={"duration": "800", "present": absolute(800)})
    assert problem(both, 422, "time_constraint")["context"]["records"] == [
        {"record_type": "clock.tick", "id": "b", "slot": "at", "t": str(10**20)}
    ]


def test_end_of_time_slots_follow_the_duration(api: Api, tmp_path: Path) -> None:
    dimension = api.make("dimension", ext=spec(1000))
    TICKS.update({("a", "end"): (dimension["id"], 1000), ("b", "at"): (dimension["id"], 10)})
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    with manager.open(api.vault).write_sessions.begin() as session:
        DependencyIndex(session).replace_edges(
            SlotNode("clock.tick", "a", "end"), [DimensionNode(dimension["id"])]
        )

    shrunk = api.patch(dimension, ext={"duration": "100"})  # "a" ends at the end of time
    assert shrunk.status_code == 200, shrunk.json()
    assert TICKS["a", "end"] == (dimension["id"], 100)
    assert TICKS["b", "at"] == (dimension["id"], 10)
    api.patch(shrunk.json()["entity"], ext={"duration": str(10**50)})
    assert TICKS["a", "end"] == (dimension["id"], 10**50)


# --- the prime follows its dimension ------------------------------------------------------------


def test_the_prime_has_its_dimensions_visibility(api: Api) -> None:
    dimension = api.make("dimension", visibility="private")
    prime = prime_of(api, dimension)
    assert prime["visibility"] == "private"
    published = api.patch(dimension, visibility="public")
    assert published.status_code == 200, published.json()
    assert fresh(api, prime)["visibility"] == "public"
    assert invalid(api.patch(fresh(api, prime), visibility="spoiler")) == ["visibility"]
    same = api.patch(fresh(api, prime), visibility="public", summary="Still public.")
    assert same.status_code == 200, same.json()


def test_trash_and_restore_follow_the_dimension(api: Api) -> None:
    dimension = api.make("dimension")
    prime = prime_of(api, dimension)
    problem(api.delete(prime["id"]), 409, "conflict")

    assert api.delete(dimension["id"]).status_code == 200
    assert fresh(api, prime)["deleted_at"] is not None
    problem(api.restore(prime["id"]), 409, "conflict")
    trashed_tree = tree(api, dimension["id"]).json()["items"]
    assert [(n["name"], n["trashed"]) for n in trashed_tree] == [("Prime", True)]

    assert api.restore(dimension["id"]).status_code == 200
    assert fresh(api, prime)["deleted_at"] is None


def test_purge_takes_the_prime_along(api: Api) -> None:
    dimension = api.make("dimension")
    prime = prime_of(api, dimension)
    gadget = api.make("gadget", dimension_id=dimension["id"])
    api.delete(dimension["id"])

    problem(api.delete(prime["id"], purge=True), 409, "conflict")
    refused = problem(api.delete(dimension["id"], purge=True), 409, "conflict")
    assert refused["context"]["references"] == {"entities in this dimension": 1}
    assert api.get(prime["id"]).status_code == 200  # rolled back with the refusal

    api.delete(gadget["id"])
    assert api.delete(gadget["id"], purge=True).status_code == 200
    assert api.delete(dimension["id"], purge=True).status_code == 200
    assert api.get(prime["id"]).status_code == 404
    assert api.get(dimension["id"]).status_code == 404


# --- undo ---------------------------------------------------------------------------------------


def _last_changeset(api: Api) -> str:
    items = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"]
    changeset_id: str = items[0]["id"]
    return changeset_id


def _revert(api: Api, changeset_id: str) -> Any:
    return api.client.post(f"{api.base}/changes/{changeset_id}/revert")


def test_undo_keeps_the_time_rules(api: Api) -> None:
    dimension = api.make("dimension", ext=spec(1000))
    created = _last_changeset(api)
    api.patch(dimension, ext={"duration": "2000"})
    growth = _last_changeset(api)
    TICKS["late", "at"] = (dimension["id"], 1500)  # added after the growth

    conflict = problem(_revert(api, growth), 409, "revert_conflict")
    messages = [p["message"] for p in conflict["context"]["problems"]]
    assert messages == ["Thing: 1 time slot resolves after the end of the dimension."]

    del TICKS["late", "at"]
    assert _revert(api, growth).status_code == 200
    assert fresh(api, dimension)["ext"]["duration"] == "1000"
    api.patch(fresh(api, dimension), visibility="private")
    assert prime_of(api, fresh(api, dimension))["visibility"] == "private"
    assert _revert(api, _last_changeset(api)).status_code == 200
    assert prime_of(api, fresh(api, dimension))["visibility"] == "public"
    assert _revert(api, created).status_code == 200
    assert api.get(dimension["id"]).status_code == 404


# --- the timeline tree --------------------------------------------------------------------------


def test_timeline_tree_visibility(api: Api) -> None:
    public = api.make("dimension")
    hidden = api.make("dimension", visibility="private")
    gadget = api.make("gadget", dimension_id=public["id"])

    assert tree(api, hidden["id"]).status_code == 200  # the author sees everything
    problem(tree(api, hidden["id"], as_reader="true"), 404, "not_found")
    problem(tree(api, gadget["id"]), 404, "not_found")
    problem(tree(api, "01a10d5f-0000-7000-8000-000000000000"), 404, "not_found")
    reader = tree(api, public["id"], as_reader="true").json()
    assert [n["name"] for n in reader["items"]] == ["Prime"]
