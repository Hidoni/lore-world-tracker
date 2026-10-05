"""Edge extraction for every anchor, duration and end-spec kind, and ``DependencyIndex``
(``time-model.md`` §7.1)."""

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lore.chronology.schema import DefinitionTimePoint, EndSpec
from lore.core.time import (
    CalendarNode,
    DependencyIndex,
    DimensionNode,
    SlotNode,
    end_targets,
    time_point_targets,
)
from lore.core.time.dependencies import MissingContextError
from lore.core.time.models import TimeDependency
from lore.core.time.specs import parse_end_spec, parse_time_point

CAL = "cal-1"
OTHER_CAL = "cal-2"
START = SlotNode("event", "ev-1", "start")


def absolute(t: str = "5") -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": t}, "precision": "base"}


def calendar(calendar_id: str = CAL) -> dict[str, Any]:
    fields = {"year": "1023", "month": "frostfall"}
    return {
        "anchor": {"kind": "calendar", "calendar_id": calendar_id, "fields": fields},
        "precision": "month",
    }


def base(units: str = "86400") -> dict[str, Any]:
    return {"kind": "base", "units": units}


def months(calendar_id: str = OTHER_CAL) -> dict[str, Any]:
    return {"kind": "calendar", "calendar_id": calendar_id, "amounts": {"month": "3"}, "sign": -1}


def relative(offset: dict[str, Any], **ref: str) -> dict[str, Any]:
    target = {"type": "event", "id": "ev-9", "slot": "end", **ref}
    return {"anchor": {"kind": "relative", "ref": target, "offset": offset}, "precision": "day"}


# --- anchors ----------------------------------------------------------------------------------


def test_absolute_anchors_depend_on_nothing() -> None:
    assert time_point_targets(parse_time_point(absolute())) == set()


def test_calendar_anchors_depend_on_their_calendar() -> None:
    assert time_point_targets(parse_time_point(calendar())) == {CalendarNode(CAL)}


def test_the_virtual_absolute_calendar_is_no_dependency() -> None:
    assert time_point_targets(parse_time_point(calendar("absolute"))) == set()


def test_relative_anchors_depend_on_the_slot_and_a_calendar_offset() -> None:
    target = SlotNode("event", "ev-9", "end")
    assert time_point_targets(parse_time_point(relative(base()))) == {target}
    assert time_point_targets(parse_time_point(relative(base("-1")))) == {target}
    assert time_point_targets(parse_time_point(relative(months()))) == {
        target,
        CalendarNode(OTHER_CAL),
    }


def test_occurrence_refs_depend_on_the_series_slot() -> None:
    point = parse_time_point(relative(base("0"), slot="start", occurrence="57"))
    assert time_point_targets(point) == {SlotNode("event", "ev-9", "start")}


def test_definition_time_points() -> None:
    local = {"anchor": {"kind": "local", "fields": {"year": "1"}}, "precision": "year"}
    adapter = TypeAdapter(DefinitionTimePoint)
    assert time_point_targets(adapter.validate_python(local)) == set()
    assert time_point_targets(adapter.validate_python(calendar(OTHER_CAL))) == {
        CalendarNode(OTHER_CAL)
    }
    assert time_point_targets(adapter.validate_python(relative(base()))) == {
        SlotNode("event", "ev-9", "end")
    }


# --- end specs --------------------------------------------------------------------------------


def end(document: dict[str, Any]) -> EndSpec:
    return parse_end_spec(document)


def test_time_point_ends_use_the_time_point() -> None:
    assert end_targets(end({"kind": "time_point", "time_point": absolute()})) == set()
    assert end_targets(end({"kind": "time_point", "time_point": calendar()}), start=START) == {
        CalendarNode(CAL)
    }
    assert end_targets(end({"kind": "time_point", "time_point": relative(months())})) == {
        SlotNode("event", "ev-9", "end"),
        CalendarNode(OTHER_CAL),
    }


def test_duration_ends_depend_on_the_own_start() -> None:
    assert end_targets(end({"kind": "duration", "duration": base()}), start=START) == {START}
    assert end_targets(end({"kind": "duration", "duration": months(CAL)}), start=START) == {
        START,
        CalendarNode(CAL),
    }


@pytest.mark.parametrize("kind", ["instant", "unknown"])
def test_instant_and_unknown_ends_depend_on_the_own_start(kind: str) -> None:
    assert end_targets(end({"kind": kind}), start=START) == {START}


def test_end_of_time_depends_on_the_dimension() -> None:
    assert end_targets(end({"kind": "end_of_time"}), dimension_id="dim-1") == {
        DimensionNode("dim-1")
    }


@pytest.mark.parametrize(
    ("document", "missing"),
    [
        ({"kind": "duration", "duration": {"kind": "base", "units": "1"}}, "start"),
        ({"kind": "instant"}, "start"),
        ({"kind": "unknown"}, "start"),
        ({"kind": "end_of_time"}, "dimension_id"),
    ],
)
def test_ends_without_their_context_are_refused(document: dict[str, Any], missing: str) -> None:
    with pytest.raises(MissingContextError, match=missing):
        end_targets(end(document))


# --- the index --------------------------------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    TimeDependency.metadata.create_all(engine, tables=[TimeDependency.__table__])  # type: ignore[list-item]
    with Session(engine) as session:
        yield session
    engine.dispose()


FUNERAL = SlotNode("event", "funeral", "start")
WAKE = SlotNode("event", "wake", "start")
DEATH_END = SlotNode("event", "death", "end")
DEATH_START = SlotNode("event", "death", "start")


def test_replace_edges_and_reverse_lookups(session: Session) -> None:
    index = DependencyIndex(session)
    index.replace_edges(FUNERAL, [DEATH_END, CalendarNode(CAL), DEATH_END, DimensionNode("d")])
    index.replace_edges(WAKE, [DEATH_START, CalendarNode(CAL)])

    assert index.edges_of(FUNERAL) == [DEATH_END, CalendarNode(CAL), DimensionNode("d")]
    assert index.dependents_of(DEATH_END) == [FUNERAL]
    assert index.dependents_of(CalendarNode(CAL)) == [FUNERAL, WAKE]
    assert index.dependents_of(DimensionNode("d")) == [FUNERAL]
    assert index.dependents_of(DimensionNode("other")) == []
    assert index.dependents_of_record("event", "death") == [FUNERAL, WAKE]
    assert session.query(TimeDependency).count() == 5  # duplicates dropped

    index.replace_edges(FUNERAL, [DEATH_START])  # rewriting drops the old edges
    assert index.edges_of(FUNERAL) == [DEATH_START]
    assert index.dependents_of(DEATH_END) == []
    assert index.dependents_of(CalendarNode(CAL)) == [WAKE]

    index.replace_edges(WAKE, [])
    assert index.edges_of(WAKE) == []


def test_a_slot_target_never_matches_a_dimension_of_the_same_id(session: Session) -> None:
    index = DependencyIndex(session)
    index.replace_edges(FUNERAL, [SlotNode("dimension", "d", "present")])
    assert index.dependents_of(DimensionNode("d")) == []
    assert index.dependents_of(SlotNode("dimension", "d", "present")) == [FUNERAL]


def test_drop_record_removes_every_outgoing_edge_of_the_record(session: Session) -> None:
    index = DependencyIndex(session)
    index.replace_edges(SlotNode("event", "funeral", "start"), [DEATH_END])
    index.replace_edges(SlotNode("event", "funeral", "end"), [FUNERAL])
    index.replace_edges(WAKE, [FUNERAL])
    index.drop_record("event", "funeral")
    assert index.dependents_of(DEATH_END) == []
    assert index.edges_of(WAKE) == [FUNERAL]  # incoming edges stay (dependents get frozen)
