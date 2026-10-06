"""Dependency propagation (``time-model.md`` §7, ADR-0007): edges, cycles, the affected set,
topological re-resolution, hard checks, trash and purge (anchor freezing), undo and the time
checker of ``lore vault check``."""

import copy
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import String, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lore.chronology.schema import EndSpec, TimePoint
from lore.core.history import recorder
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.core.modules.spec import VaultContext
from lore.core.time import (
    CalendarNode,
    DependencyIndex,
    EndSpecColumn,
    SlotDef,
    SlotNode,
    SlotProvider,
    moment_column,
    spec_column,
    status_column,
)
from lore.core.time.check import rebuild_time, verify_time
from lore.core.time.models import TimeDependency
from lore.core.time.propagate import TimeConstraintError, TimeCycleError, TimeWriter
from lore.core.time.specs import parse_end_spec, parse_time_point
from lore.core.vaults import OpenVault, VaultManager
from tests.entity_api import Api, make_client, problem
from tests.entity_modules import ENTITY_MODULES
from tests.time.test_calendars import YEARS

DAY = 86_400
YEAR = 365 * DAY
D = 10**12

# --- a module whose records have a start and an end, in a real table ----------------------------


class TlBase(DeclarativeBase):
    pass


class Happening(TlBase):
    """Like ``events``; ``id`` is the id of the entity it belongs to (or any id)."""

    __tablename__ = "tl_happenings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dimension_id: Mapped[str] = mapped_column(String)
    start_spec: Mapped[TimePoint | None] = spec_column()
    start_t: Mapped[int | None] = moment_column()
    end_spec: Mapped[Any] = spec_column(EndSpecColumn)
    end_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()


HAPPENING = "tl.happening"
TL = ModuleSpec(
    id="tl",
    name="Happenings",
    description="Records with a start and an end (tests).",
    models=(Happening,),
    history_tables=(HistoryTable.of(Happening),),
    slot_providers=(
        SlotProvider(
            HAPPENING,
            Happening,
            (
                SlotDef("start", referenceable=True),
                SlotDef("end", spec="end", referenceable=True),
            ),
            entity_column="id",
            dimension_column="dimension_id",
        ),
    ),
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path, modules=(*ENTITY_MODULES, TL)) as client:
        made = Api(client)
        TlBase.metadata.create_all(_opened(made).engine)
        yield made


def _opened(api: Api) -> OpenVault:
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    return manager.open(api.vault)


@pytest.fixture
def world(api: Api) -> dict[str, str]:
    dimension = api.make("dimension", ext={**_ext(), "duration": str(D)})
    calendar = api.make(
        "calendar", "Years", ext={"definition": YEARS}, dimension_id=dimension["id"]
    )
    return {"dimension": dimension["id"], "calendar": calendar["id"]}


def _ext() -> dict[str, Any]:
    return {"base_unit": {"singular": "second", "plural": "seconds", "abbr": "s"}}


@contextmanager
def service(api: Api) -> Iterator[TimeWriter]:
    """A write transaction acting as a service: yields a writer; propagates and commits."""
    opened = _opened(api)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]
    with opened.write_sessions.begin() as session:
        writer = TimeWriter(VaultContext(opened, session, registry))
        yield writer
        writer.propagate()


def put(
    writer: TimeWriter,
    record_id: str,
    dimension_id: str,
    start: TimePoint | None = None,
    end: EndSpec | None = None,
) -> None:
    """Create or change a happening's specs (as a service would)."""
    session = writer.session
    row = session.get(Happening, record_id)
    if row is None:
        row = Happening(id=record_id, dimension_id=dimension_id)
        session.add(row)
    if start is not None:
        row.start_spec = start
        session.flush()
        writer.set_spec(HAPPENING, record_id, "start", start)
    if end is not None:
        row.end_spec = end
        session.flush()
        writer.set_spec(HAPPENING, record_id, "end", end, dimension_id=dimension_id)


def at(t: int, precision: str = "base") -> TimePoint:
    return parse_time_point({"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision})


def after(record_id: str, units: int, slot: str = "start", precision: str = "base") -> TimePoint:
    return parse_time_point(
        {
            "anchor": {
                "kind": "relative",
                "ref": {"type": HAPPENING, "id": record_id, "slot": slot},
                "offset": {"kind": "base", "units": str(units)},
            },
            "precision": precision,
        }
    )


def in_year(calendar_id: str, year: int) -> TimePoint:
    anchor = {"kind": "calendar", "calendar_id": calendar_id, "fields": {"year": str(year)}}
    return parse_time_point({"anchor": anchor, "precision": "year"})


def end(document: dict[str, Any]) -> EndSpec:
    return parse_end_spec(document)


def rows(api: Api) -> dict[str, Happening]:
    with _opened(api).sessions() as session:
        return {row.id: row for row in session.scalars(select(Happening))}


def moments(api: Api, *ids: str) -> list[int | None]:
    found = rows(api)
    return [found[i].start_t for i in ids]


def edges(api: Api, record_id: str, slot: str = "start") -> list[Any]:
    with _opened(api).sessions() as session:
        return DependencyIndex(session).edges_of(SlotNode(HAPPENING, record_id, slot))


# --- propagation --------------------------------------------------------------------------------


def test_chains_follow_their_anchors(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
        put(writer, "b", dim, after("a", 10))
        put(writer, "c", dim, after("b", 10))
    assert moments(api, "a", "b", "c") == [100, 110, 120]
    assert edges(api, "c") == [SlotNode(HAPPENING, "b", "start")]
    with service(api) as writer:
        put(writer, "a", dim, at(1000))
    assert moments(api, "a", "b", "c") == [1000, 1010, 1020]
    assert {row.time_status for row in rows(api).values()} == {"ok"}


def test_diamonds_and_ends(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
        put(writer, "b", dim, after("a", 1))
        put(writer, "c", dim, after("a", 2))
        # d starts after b and ends 5 after c; e lasts 50 from its start.
        put(
            writer,
            "d",
            dim,
            after("b", 0),
            end({"kind": "time_point", "time_point": after("c", 5).model_dump()}),
        )
        put(
            writer,
            "e",
            dim,
            after("d", 0),
            end({"kind": "duration", "duration": {"kind": "base", "units": "50"}}),
        )
        put(writer, "f", dim, at(0), end({"kind": "end_of_time"}))
    found = rows(api)
    assert (found["d"].start_t, found["d"].end_t) == (101, 107)
    assert (found["e"].start_t, found["e"].end_t) == (101, 151)
    assert found["f"].end_t == D
    with service(api) as writer:
        put(writer, "a", dim, at(200))
    found = rows(api)
    assert (found["d"].start_t, found["d"].end_t) == (201, 207)
    assert (found["e"].start_t, found["e"].end_t) == (201, 251)
    # The end of time follows the dimension's duration.
    dimension = api.get(dim).json()
    assert api.patch(dimension, ext={"duration": str(D * 10)}).status_code == 200
    assert rows(api)["f"].end_t == D * 10


def test_anchors_into_calendars(api: Api, world: dict[str, str]) -> None:
    """A calendar anchored to a happening: moving the happening compiles the calendar again and
    moves the dates typed in it."""
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "epoch", dim, at(1000))
    linked = copy.deepcopy(YEARS)
    linked["regimes"][0]["alignment"]["at"] = after("epoch", 0).model_dump()
    calendar = api.make("calendar", "Linked", ext={"definition": linked}, dimension_id=dim)
    assert calendar["ext"]["resolved_anchors"] == {"/regimes/0/alignment/at": "1000"}
    with service(api) as writer:
        put(writer, "dated", dim, in_year(calendar["id"], 3))
    assert moments(api, "dated") == [1000 + 2 * YEAR]
    with service(api) as writer:
        put(writer, "epoch", dim, at(5000))
    assert moments(api, "dated") == [5000 + 2 * YEAR]
    stored = api.get(calendar["id"]).json()["ext"]
    assert stored["resolved_anchors"] == {"/regimes/0/alignment/at": "5000"}
    assert stored["compile_status"] == "ok"


def test_the_present_follows_its_anchor(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "now", dim, at(70))
    dimension = api.get(dim).json()
    moved = api.patch(dimension, ext={"present": after("now", 30).model_dump()})
    assert moved.status_code == 200, moved.json()
    assert moved.json()["entity"]["ext"]["present_t"] == "100"
    with service(api) as writer:
        put(writer, "now", dim, at(900))
    assert api.get(dim).json()["ext"]["present_t"] == "930"


# --- cycles -------------------------------------------------------------------------------------


def test_cycles_are_rejected(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(1))
        put(writer, "b", dim, after("a", 1))
    with pytest.raises(TimeCycleError) as direct, service(api) as writer:
        put(writer, "a", dim, after("a", 1))
    assert direct.value.context == {"path": [f"{HAPPENING} a start", f"{HAPPENING} a start"]}
    with pytest.raises(TimeCycleError) as indirect, service(api) as writer:
        put(writer, "a", dim, after("b", 1))
    assert indirect.value.context is not None
    assert indirect.value.context["path"] == [
        f"{HAPPENING} a start",
        f"{HAPPENING} b start",
        f"{HAPPENING} a start",
    ]
    assert moments(api, "a", "b") == [1, 2]  # nothing changed
    assert edges(api, "a") == []


def test_cycles_through_calendars(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(10))
    linked = copy.deepcopy(YEARS)
    linked["regimes"][0]["alignment"]["at"] = after("a", 0).model_dump()
    calendar = api.make("calendar", "Linked", ext={"definition": linked}, dimension_id=dim)
    # a → the calendar → its alignment → a
    with pytest.raises(TimeCycleError) as raised, service(api) as writer:
        put(writer, "a", dim, in_year(calendar["id"], 2))
    assert raised.value.context is not None
    assert f"calendar {calendar['id']}" in raised.value.context["path"]
    # The same cycle written from the calendar's side (an anchor to a happening dated in it).
    with service(api) as writer:
        put(writer, "z", dim, in_year(world["calendar"], 2))
    looped = copy.deepcopy(YEARS)
    looped["regimes"][0]["alignment"]["at"] = after("z", 0).model_dump()
    other = api.make("calendar", "Other", ext={"definition": YEARS}, dimension_id=dim)
    with service(api) as writer:
        put(writer, "z", dim, in_year(other["id"], 2))
    refused = api.patch(api.get(other["id"]).json(), ext={"definition": looped})
    problem(refused, 409, "conflict")  # it has dependents: edits go through proposals
    fresh = api.make("calendar", "Fresh", ext={"definition": YEARS}, dimension_id=dim)
    with service(api) as writer:
        put(writer, "y", dim, at(0))
    looped["regimes"][0]["alignment"]["at"] = after("y", 0).model_dump()
    assert api.patch(api.get(fresh["id"]).json(), ext={"definition": looped}).status_code == 200


# --- hard checks --------------------------------------------------------------------------------


def test_hard_checks_reject_the_whole_write(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
        put(writer, "b", dim, after("a", 10))
        put(writer, "late", dim, after("b", D - 200))  # at D - 90
        put(
            writer,
            "span",
            dim,
            at(500),
            end({"kind": "time_point", "time_point": at(600).model_dump()}),
        )
    before = {row.id: (row.start_t, row.time_status) for row in rows(api).values()}
    with pytest.raises(TimeConstraintError) as raised, service(api) as writer:
        put(writer, "a", dim, at(1000))  # late would be at D + 810
    assert raised.value.context == {
        "records": [
            {"record_type": HAPPENING, "id": "late", "slot": "start", "code": "out_of_bounds",
             "t": str(D + 810)}
        ]
    }  # fmt: skip
    assert {row.id: (row.start_t, row.time_status) for row in rows(api).values()} == before
    with pytest.raises(TimeConstraintError) as backwards, service(api) as writer:
        put(writer, "span", dim, at(700))
    assert backwards.value.errors is not None
    assert backwards.value.errors[0]["code"] == "end_before_start"
    with pytest.raises(TimeConstraintError), service(api) as writer:
        put(writer, "bad", dim, in_year(world["calendar"], 10**9))  # after the end
    assert "bad" not in rows(api)


def test_lenient_runs_keep_the_last_good_moment(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
        put(writer, "b", dim, after("a", D - 150))
    opened = _opened(api)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]
    with opened.write_sessions.begin() as session:
        writer = TimeWriter(VaultContext(opened, session, registry))
        put(writer, "a", dim, at(200))
        result = writer.propagate(strict=False)
    assert [v.code for v in result.violations] == ["out_of_bounds"]
    found = rows(api)
    assert (found["b"].start_t, found["b"].time_status) == (D - 50, "out_of_bounds")


# --- trash, purge, undo -------------------------------------------------------------------------


def test_trash_restore_purge_and_undo(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    owner = api.make("gadget", "Owner", dimension_id=dim)
    with service(api) as writer:
        put(writer, owner["id"], dim, at(500))
        put(writer, "x", dim, after(owner["id"], 5, precision="year"))
    assert api.delete(owner["id"]).status_code == 200
    assert (rows(api)["x"].start_t, rows(api)["x"].time_status) == (505, "trashed_ref")
    assert api.restore(owner["id"]).status_code == 200
    assert rows(api)["x"].time_status == "ok"

    api.delete(owner["id"])
    assert api.delete(owner["id"], purge=True).status_code == 200
    frozen = rows(api)["x"]
    assert (frozen.start_t, frozen.time_status) == (505, "ok")
    assert frozen.start_spec is not None
    assert frozen.start_spec.model_dump(mode="json") == {
        "anchor": {"kind": "absolute", "t": "505"},
        "precision": "year",  # the default calendar has years
        "approximate": False,
        "frozen_from": after(owner["id"], 5, precision="year").model_dump(mode="json"),
    }
    assert edges(api, "x") == []

    purge = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    undone = api.client.post(f"{api.base}/changes/{purge['id']}/revert")
    assert undone.status_code == 200, undone.json()
    restored = rows(api)["x"]
    assert restored.start_spec == after(owner["id"], 5, precision="year")
    assert edges(api, "x") == [SlotNode(HAPPENING, owner["id"], "start")]


def test_purging_a_calendar_freezes_its_dates(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    other = api.make("calendar", "Other", ext={"definition": YEARS}, dimension_id=dim)
    with service(api) as writer:
        put(writer, "dated", dim, in_year(other["id"], 3))
    assert api.delete(other["id"]).status_code == 200
    assert rows(api)["dated"].time_status == "trashed_ref"
    assert api.delete(other["id"], purge=True).status_code == 200
    dated = rows(api)["dated"]
    assert dated.start_spec is not None
    assert dated.start_spec.anchor.model_dump() == {"kind": "absolute", "t": str(2 * YEAR)}
    assert dated.start_spec.frozen_from == in_year(other["id"], 3).model_dump(mode="json")
    assert (dated.start_t, dated.time_status) == (2 * YEAR, "ok")


def test_undo_that_would_break_time_rules_is_refused(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
    with service(api) as writer:
        put(writer, "b", dim, after("a", 1))
    with service(api) as writer:
        put(writer, "b", dim, at(7))
    with service(api) as writer:
        put(writer, "a", dim, after("b", 1))
    # Undoing "b := 7" would make b relative to a again, and a is relative to b.
    changes = api.client.get(f"{api.base}/changes", params={"limit": 5}).json()["items"]
    refused = api.client.post(f"{api.base}/changes/{changes[1]['id']}/revert")
    body = problem(refused, 409, "revert_conflict")
    assert "time" in body["detail"]


# --- lore vault check ---------------------------------------------------------------------------


def test_the_time_checker(api: Api, world: dict[str, str]) -> None:
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "a", dim, at(100))
        put(writer, "b", dim, after("a", 10))
    opened = _opened(api)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]

    def problems() -> list[str]:
        with opened.sessions() as session:
            return [p.code for p in verify_time(VaultContext(opened, session, registry))]

    assert problems() == []
    with opened.write_sessions.begin() as session:
        session.execute(update(Happening).where(Happening.id == "b").values(start_t=999))
        DependencyIndex(session).replace_edges(
            SlotNode(HAPPENING, "a", "start"), [CalendarNode("c")]
        )
        DependencyIndex(session).replace_edges(
            SlotNode(HAPPENING, "gone", "start"), [CalendarNode("c")]
        )
    assert sorted(problems()) == ["time_edges_orphaned", "time_edges_stale", "time_moment_stale"]
    with opened.write_sessions.begin() as session:
        assert rebuild_time(VaultContext(opened, session, registry)) >= 3
    assert problems() == []
    assert moments(api, "b") == [110]
    with opened.sessions() as session:
        assert (
            session.scalar(select(TimeDependency.id).where(TimeDependency.dependent_id == "gone"))
            is None
        )


# --- performance --------------------------------------------------------------------------------


@pytest.mark.perf
def test_large_fan_out(api: Api, world: dict[str, str]) -> None:
    """10,000 slots anchored to one: moving it re-resolves them all within the budget."""
    dim = world["dimension"]
    with service(api) as writer:
        put(writer, "hub", dim, at(0))
        for i in range(10_000):
            put(writer, f"spoke-{i:05d}", dim, after("hub", i))
    started = time.perf_counter()
    with service(api) as writer:
        put(writer, "hub", dim, at(1000))
    elapsed = time.perf_counter() - started
    found = rows(api)
    assert found["spoke-09999"].start_t == 1000 + 9999
    assert elapsed < 5, f"propagation to 10,000 dependents took {elapsed:.2f} s"
