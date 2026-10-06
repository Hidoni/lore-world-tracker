"""Anchor resolution (``time-model.md`` §5.2-§5.5, §6, §8) and the ``/time`` routes."""

import copy
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from lore.chronology.calendar import format_date
from lore.chronology.schema import EndSpec, TimePoint
from lore.core.errors import InvalidInputError
from lore.core.history import recorder
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.core.modules.spec import VaultContext
from lore.core.time import SlotDef, SlotProvider
from lore.core.time.redact import ReaderTimes
from lore.core.time.resolve import (
    ReformAmbiguousError,
    ReformGapError,
    Resolution,
    Resolver,
    TimeInvalidError,
    TimeNotSupportedError,
    require,
)
from lore.core.time.slots import SlotKey, SlotMoment, SlotUpdate, SlotValue
from lore.core.time.specs import parse_end_spec, parse_time_point
from lore.core.time.status import TimeStatus
from lore.core.vaults import VaultManager
from lore.core.visibility import AUTHOR, READER, VisibilityPolicy
from tests.entity_api import Api, make_client, problem
from tests.entity_modules import ENTITY_MODULES
from tests.time.test_calendars import SECOND, YEARS

DAY = 86_400
ORIGIN = 10**12  # 1 January AD 1, 00:00
D = 10**14

# --- a dummy module whose records have time slots, kept in memory --------------------------------


class PinBase(DeclarativeBase):
    pass


class Pin(PinBase):
    __tablename__ = "pin_pins"  # never created: the loader keeps pins in memory

    id: Mapped[str] = mapped_column(String, primary_key=True)


# (id, slot) -> (spec, stored t, trashed)
PINS: dict[tuple[str, str], tuple[Any, int | None, bool]] = {}


def _load(_session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    found: dict[SlotKey, SlotValue] = {}
    for key in keys:
        if (key.id, key.slot) in PINS:
            spec, t, trashed = PINS[key.id, key.slot]
            found[key] = SlotValue(spec, t, TimeStatus.OK, trashed)
    return found


def _write(_session: Session, _updates: Sequence[SlotUpdate]) -> None:
    raise AssertionError("resolution never writes")


def _beyond(_session: Session, _dimension_id: str, _bound: int) -> list[SlotMoment]:
    return []


PIN = ModuleSpec(
    id="pin",
    name="Pins",
    description="Records with time slots (tests).",
    models=(Pin,),
    history_tables=(HistoryTable.of(Pin, derived=True),),
    slot_providers=(
        SlotProvider(
            "pin.pin",
            Pin,
            (
                SlotDef("start", referenceable=True),
                SlotDef("end", spec="end", referenceable=True),
                SlotDef("secret"),
            ),
            load=_load,
            write=_write,
            beyond=_beyond,
        ),
    ),
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    PINS.clear()
    with make_client(tmp_path, modules=(*ENTITY_MODULES, PIN)) as client:
        yield Api(client)


def gregorian_t(year: int, month: int, day: int) -> int:
    """The start of a (proleptic) Gregorian day, by Python's ``date``."""
    return ORIGIN + (date(year, month, day).toordinal() - 1) * DAY


def _definition(api: Api, preset: str) -> dict[str, Any]:
    body = {
        "time_spec": {"base_unit": SECOND, "duration": str(D)},
        "source": {"preset": {"id": preset, "origin": str(ORIGIN)}},
    }
    result = api.client.post(f"{api.base}/calendars/preview", json=body).json()
    assert result["ok"], result
    definition: dict[str, Any] = result["definition"]
    return definition


@pytest.fixture
def world(api: Api) -> dict[str, Any]:
    """A dimension with a Gregorian default calendar (``ORIGIN`` is 1 January AD 1), a
    Julian-Gregorian one and a calendar with a backward reform."""
    created = api.client.post(
        f"{api.base}/dimensions",
        json={
            "name": "Earth",
            "ext": {"base_unit": SECOND, "duration": str(D)},
            "calendar": {
                "name": "Gregorian",
                "source": {"preset": {"id": "gregorian", "origin": str(ORIGIN)}},
            },
        },
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    home = {"dimension_id": body["dimension"]["id"]}
    reform = api.make(
        "calendar", "Reform", ext={"definition": _definition(api, "julian-gregorian")}, **home
    )
    repeat = api.make("calendar", "Repeat", ext={"definition": repeating_years()}, **home)
    return {
        "dimension": body["dimension"]["id"],
        "gregorian": body["calendar"]["id"],
        "reform": reform["id"],
        "repeat": repeat["id"],
    }


YEAR = 365 * DAY


def repeating_years() -> dict[str, Any]:
    """Years of 365 days; regime ``new`` (from the start of old year 3) counts year 2 again."""
    definition = copy.deepcopy(YEARS)
    old = definition["regimes"][0]
    old["id"] = "old"
    new = copy.deepcopy(old)
    new["id"], new["name"] = "new", "New"
    new["alignment"]["at"]["anchor"]["t"] = str(YEAR)  # new year 1 starts at old year 2
    new["starts_at"] = {"anchor": {"kind": "absolute", "t": str(2 * YEAR)}, "precision": "base"}
    definition["regimes"].append(new)
    return definition


def _manager(api: Api) -> VaultManager:
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    return manager


@contextmanager
def resolving(
    api: Api, world: dict[str, Any], policy: VisibilityPolicy = AUTHOR
) -> Iterator[Resolver]:
    """A resolver in its own session (it sees what was committed before it started)."""
    opened = _manager(api).open(api.vault)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]
    with opened.sessions() as session:
        yield Resolver(VaultContext(opened, session, registry), world["dimension"], policy=policy)


@pytest.fixture
def resolver(api: Api, world: dict[str, Any]) -> Iterator[Resolver]:
    with resolving(api, world) as made:
        yield made


def point(anchor: dict[str, Any], precision: str = "base", **extra: Any) -> TimePoint:
    return parse_time_point({"anchor": anchor, "precision": precision, **extra})


def absolute(t: int, precision: str = "base") -> TimePoint:
    return point({"kind": "absolute", "t": str(t)}, precision)


def cal(calendar_id: str, precision: str, era: str | None = None, **fields: str) -> TimePoint:
    anchor: dict[str, Any] = {"kind": "calendar", "calendar_id": calendar_id, "fields": fields}
    if era is not None:
        anchor["era"] = era
    return point(anchor, precision)


def months(calendar_id: str, n: int, **amounts: str) -> dict[str, Any]:
    return {
        "kind": "calendar",
        "calendar_id": calendar_id,
        "amounts": {"month": str(abs(n)), **amounts},
        "sign": 1 if n >= 0 else -1,
    }


def base(units: int) -> dict[str, Any]:
    return {"kind": "base", "units": str(units)}


def relative(pin: str, offset: dict[str, Any], precision: str, slot: str = "start") -> TimePoint:
    ref = {"type": "pin.pin", "id": pin, "slot": slot}
    return point({"kind": "relative", "ref": ref, "offset": offset}, precision)


def pin(pin_id: str, spec: TimePoint | None, t: int | None, *, slot: str = "start") -> None:
    PINS[pin_id, slot] = (spec, t, False)


def stored(resolver: Resolver, pin_id: str, spec: TimePoint, slot: str = "start") -> Resolution:
    """Store a pin slot with its spec resolved now."""
    result = resolver.resolve(spec)
    pin(pin_id, spec, result.t, slot=slot)
    return result


def shape(result: Resolution) -> tuple[Any, ...]:
    return (result.t, result.status, result.extent, result.precision)


def problem_of(result: Resolution) -> tuple[Any, ...]:
    assert result.problem is not None
    return (result.status, result.problem.code, result.problem.path)


# --- absolute -----------------------------------------------------------------------------------


def test_absolute_anchors(resolver: Resolver) -> None:
    assert shape(resolver.resolve(absolute(42))) == (42, TimeStatus.OK, (42, 43), "base")
    # A calendar level: the extent is computed in the default calendar, from t to the unit's end.
    noon = gregorian_t(2024, 3, 12) + DAY // 2
    day = resolver.resolve(absolute(noon, "day"))
    assert shape(day) == (noon, TimeStatus.OK, (noon, gregorian_t(2024, 3, 13)), "day")
    assert day.calendar_id is not None
    assert problem_of(resolver.resolve(absolute(noon, "fortnight"))) == (
        TimeStatus.INVALID_DATE,
        "invalid_date",
        "precision",
    )
    assert resolver.resolve(absolute(D)).status == TimeStatus.OK
    late = resolver.resolve(absolute(D + 1))
    assert problem_of(late) == (TimeStatus.OUT_OF_BOUNDS, "out_of_bounds", "")
    assert late.t == D + 1  # out of bounds is a status: the moment is still there


# --- calendar -----------------------------------------------------------------------------------


def test_calendar_anchors_resolve_to_the_start_of_the_unit(
    resolver: Resolver, world: dict[str, Any]
) -> None:
    g = world["gregorian"]
    day = resolver.resolve(cal(g, "day", year="2024", month="mar", day="12"))
    start = gregorian_t(2024, 3, 12)
    assert shape(day) == (start, TimeStatus.OK, (start, start + DAY), "day")
    feb = resolver.resolve(cal(g, "month", year="2024", month="feb"))
    assert shape(feb) == (
        gregorian_t(2024, 2, 1),
        TimeStatus.OK,
        (gregorian_t(2024, 2, 1), gregorian_t(2024, 3, 1)),  # a leap February: 29 days
        "month",
    )
    year = resolver.resolve(cal(g, "year", year="2023"))
    assert year.extent == (gregorian_t(2023, 1, 1), gregorian_t(2024, 1, 1))
    hour = resolver.resolve(cal(g, "hour", year="2024", month="2", day="29", hour="13"))
    assert hour.extent == (
        gregorian_t(2024, 2, 29) + 13 * 3600,
        gregorian_t(2024, 2, 29) + 14 * 3600,
    )
    assert resolver.resolve(cal(g, "day", year="2024", month="mar", day="12")).approximate is False
    circa = point(
        {"kind": "calendar", "calendar_id": g, "fields": {"year": "2024"}}, "year", approximate=True
    )
    assert resolver.resolve(circa).approximate is True


def test_invalid_calendar_dates(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    cases = [
        (cal(g, "day", year="2023", month="feb", day="29"), "anchor.fields.day"),
        (cal(g, "month", year="2023", month="thermidor"), "anchor.fields.month"),
        (cal(g, "month", year="2023", month="feb", day="1"), "anchor.fields.day"),  # below
        (cal(g, "day", year="2023", day="1"), "anchor.fields"),  # the month is missing
        (cal(g, "fortnight", year="2023"), "precision"),
    ]
    for spec, path in cases:
        result = resolver.resolve(spec)
        assert result.t is None
        assert problem_of(result) == (TimeStatus.INVALID_DATE, "invalid_date", path), path


def test_era_relative_input(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    ad = resolver.resolve(cal(g, "year", era="ad", year="2024"))
    assert ad.t == gregorian_t(2024, 1, 1)
    # 1 BC is the (leap) year before AD 1: astronomical year 0.
    bc = resolver.resolve(cal(g, "day", era="bc", year="1", month="mar", day="1"))
    assert bc.t == ORIGIN - 306 * DAY
    assert bc.status == TimeStatus.OK
    nowhere = resolver.resolve(cal(g, "year", era="xx", year="1"))
    assert nowhere.status == TimeStatus.INVALID_DATE


def test_dates_before_the_inception_are_out_of_bounds(api: Api, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    with resolving(api, world) as resolver:
        early = resolver.resolve(cal(g, "year", era="bc", year="1000000"))
        assert early.status == TimeStatus.OUT_OF_BOUNDS
        assert early.t is not None
        assert early.t < 0
        assert early.problem is not None
        assert "before the inception" in early.problem.message


def test_reform_gaps_and_ambiguous_dates(resolver: Resolver, world: dict[str, Any]) -> None:
    r = world["reform"]
    julian = resolver.resolve(cal(r, "day", year="1582", month="oct", day="4"))
    gregorian = resolver.resolve(cal(r, "day", year="1582", month="oct", day="15"))
    assert julian.t is not None
    assert gregorian.t == julian.t + DAY  # the day after 4 October (Julian) is 15 October
    gap = resolver.resolve(cal(r, "day", year="1582", month="oct", day="10"))
    assert problem_of(gap) == (TimeStatus.INVALID_DATE, "reform_gap", "anchor.fields")
    forced = point(
        {
            "kind": "calendar",
            "calendar_id": r,
            "fields": {"year": "1582", "month": "oct", "day": "10"},
            "regime": "julian",
        },
        "day",
    )
    assert resolver.resolve(forced).t == julian.t + 6 * DAY

    repeat = world["repeat"]
    twice = resolver.resolve(cal(repeat, "year", year="2"))
    assert problem_of(twice) == (TimeStatus.INVALID_DATE, "reform_ambiguous", "anchor.fields")
    chosen = point(
        {"kind": "calendar", "calendar_id": repeat, "fields": {"year": "2"}, "regime": "new"},
        "year",
    )
    assert resolver.resolve(chosen).t == 2 * YEAR


def test_calendar_problems(api: Api, resolver: Resolver, world: dict[str, Any]) -> None:
    elsewhere = api.make("dimension")
    foreign = api.make(
        "calendar", "Foreign", ext={"definition": YEARS}, dimension_id=elsewhere["id"]
    )
    assert problem_of(resolver.resolve(cal(foreign["id"], "year", year="1"))) == (
        TimeStatus.UNRESOLVED_REF,
        "unresolved_ref",
        "anchor.calendar_id",
    )
    assert problem_of(resolver.resolve(cal("absolute", "year", year="1"))) == (
        None,
        "invalid_date",
        "anchor.calendar_id",
    )
    assert api.delete(world["repeat"]).status_code == 200
    with resolving(api, world) as after:
        trashed = after.resolve(cal(world["repeat"], "year", year="1"))
        assert (trashed.t, trashed.status) == (0, TimeStatus.TRASHED_REF)


# --- relative -----------------------------------------------------------------------------------


def test_relative_anchors_with_base_offsets(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    target = stored(resolver, "a", cal(g, "day", year="2024", month="mar", day="12"))
    assert target.t is not None
    later = resolver.resolve(relative("a", base(3 * DAY), "day"))
    # The default precision is the target's (a base offset has no coarser unit): its extent moves.
    assert shape(later) == (
        target.t + 3 * DAY,
        TimeStatus.OK,
        (target.t + 3 * DAY, target.t + 4 * DAY),
        "day",
    )
    before = resolver.resolve(relative("a", base(-DAY // 2), "base"))
    assert shape(before) == (target.t - DAY // 2, TimeStatus.OK, (target.t - DAY // 2,
                                                                     target.t - DAY // 2 + 1),
                             "base")  # fmt: skip
    # An explicit coarser precision: from t to the end of its unit (in the default calendar).
    month = resolver.resolve(relative("a", base(0), "month"))
    assert month.extent == (target.t, gregorian_t(2024, 4, 1))


def test_calendar_offsets_across_month_ends(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    stored(resolver, "jan31", cal(g, "day", year="2024", month="jan", day="31"))
    plus = resolver.resolve(relative("jan31", months(g, 1), "month"))
    # 31 January + 1 month is constrained to the last day of February (a leap year).
    assert plus.t == gregorian_t(2024, 2, 29)
    # The default precision is the coarser unit (month); the extent is the target's day, moved.
    assert shape(plus) == (
        gregorian_t(2024, 2, 29),
        TimeStatus.OK,
        (gregorian_t(2024, 2, 29), gregorian_t(2024, 3, 1)),
        "month",
    )
    assert plus.calendar_id == g
    common = resolver.resolve(relative("jan31", months(g, 13), "month"))
    assert common.t == gregorian_t(2025, 2, 28)
    explicit = resolver.resolve(relative("jan31", months(g, 1), "year"))
    assert explicit.extent == (gregorian_t(2024, 2, 29), gregorian_t(2025, 1, 1))

    stored(resolver, "mar31", cal(g, "day", year="2024", month="mar", day="31"))
    minus = resolver.resolve(relative("mar31", months(g, -1), "month"))
    assert minus.t == gregorian_t(2024, 2, 29)
    mixed = resolver.resolve(relative("mar31", months(g, 1, day="2"), "day"))
    assert mixed.t == gregorian_t(2024, 5, 2)  # 30 April + 2 days
    assert mixed.precision == "day"  # the explicit precision is kept
    assert mixed.extent == (gregorian_t(2024, 5, 2), gregorian_t(2024, 5, 3))

    # A coarse target with a fine offset: the target's precision (year) is the default.
    stored(resolver, "y", cal(g, "year", year="2024"))
    shifted = resolver.resolve(relative("y", {**months(g, 0), "amounts": {"day": "3"}}, "year"))
    assert shape(shifted) == (
        gregorian_t(2024, 1, 4),
        TimeStatus.OK,
        (gregorian_t(2024, 1, 4), gregorian_t(2025, 1, 4)),
        "year",
    )
    unknown = resolver.resolve(relative("y", {**months(g, 1), "amounts": {"week": "1"}}, "day"))
    assert problem_of(unknown) == (
        TimeStatus.INVALID_DATE,
        "invalid_date",
        "anchor.offset.amounts.week",
    )


def test_relative_chains_take_the_stored_moment(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    stored(resolver, "a", cal(g, "month", year="2024", month="jan"))
    stored(resolver, "b", relative("a", base(DAY), "month"))
    chained = resolver.resolve(relative("b", base(DAY), "month"))
    assert shape(chained) == (
        gregorian_t(2024, 1, 3),
        TimeStatus.OK,
        (gregorian_t(2024, 1, 3), gregorian_t(2024, 2, 3)),
        "month",
    )
    # The stored (last good) moment counts, not a fresh resolution of the target; the extent
    # keeps the width of the target's (31 days from 2 January).
    PINS["b", "start"] = (PINS["b", "start"][0], gregorian_t(2024, 6, 1), False)
    assert resolver.resolve(relative("b", base(0), "month")).extent == (
        gregorian_t(2024, 6, 1),
        gregorian_t(2024, 7, 2),
    )


def test_relative_anchor_problems(resolver: Resolver, world: dict[str, Any]) -> None:
    def ref(**changes: Any) -> TimePoint:
        reference = {"type": "pin.pin", "id": "a", "slot": "start", **changes}
        return point({"kind": "relative", "ref": reference, "offset": base(0)})

    assert problem_of(resolver.resolve(ref())) == (
        TimeStatus.UNRESOLVED_REF,
        "unresolved_ref",
        "anchor.ref",
    )
    pin("a", None, None)  # a slot without a moment
    assert resolver.resolve(ref()).status == TimeStatus.UNRESOLVED_REF
    pin("a", None, 500)  # no spec (e.g. set by a module): exact
    assert shape(resolver.resolve(ref())) == (500, TimeStatus.OK, (500, 501), "base")
    PINS["a", "start"] = (None, 500, True)
    trashed = resolver.resolve(ref())
    assert (trashed.t, trashed.status) == (500, TimeStatus.TRASHED_REF)
    assert problem_of(resolver.resolve(ref(slot="secret"))) == (
        None,
        "slot_not_referenceable",
        "anchor.ref",
    )
    assert problem_of(resolver.resolve(ref(slot="nope"))) == (None, "unknown_slot", "anchor.ref")
    assert problem_of(resolver.resolve(ref(type="event"))) == (None, "unknown_slot", "anchor.ref")
    assert problem_of(resolver.resolve(ref(occurrence="3"))) == (
        None,
        "not_supported",
        "anchor.ref.occurrence",
    )
    # Cycles: c → d → c.
    pin("c", relative("d", base(1), "base"), 10)
    pin("d", relative("c", base(1), "base"), 11)
    looped = resolver.resolve(relative("c", base(0), "base"))
    assert (looped.status, looped.t) == (TimeStatus.CYCLE, None)
    beyond = resolver.resolve(relative("a", base(D), "base"))
    assert problem_of(beyond) == (TimeStatus.OUT_OF_BOUNDS, "out_of_bounds", "")


def test_trashed_calendars_in_offsets(api: Api, world: dict[str, Any]) -> None:
    pin("a", None, 0)
    repeat = world["repeat"]
    assert api.delete(repeat).status_code == 200
    offset = {"kind": "calendar", "calendar_id": repeat, "amounts": {"year": "1"}, "sign": 1}
    with resolving(api, world) as resolver:
        moved = resolver.resolve(relative("a", offset, "year"))
        assert (moved.t, moved.status) == (YEAR, TimeStatus.TRASHED_REF)


# --- ends ---------------------------------------------------------------------------------------


def end(document: dict[str, Any]) -> EndSpec:
    return parse_end_spec(document)


def test_end_specs(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    start = resolver.resolve(cal(g, "day", year="2024", month="jan", day="31"))
    assert start.t is not None
    month = resolver.resolve_end(end({"kind": "duration", "duration": months(g, 1)}), start)
    assert shape(month) == (
        gregorian_t(2024, 2, 29),
        TimeStatus.OK,
        (gregorian_t(2024, 2, 29), gregorian_t(2024, 3, 1)),
        "month",  # the coarser of the start's precision and the duration's finest unit
    )
    hours = resolver.resolve_end(end({"kind": "duration", "duration": base(3600)}), start)
    assert (hours.t, hours.precision) == (start.t + 3600, "day")
    assert resolver.resolve_end(end({"kind": "instant"}), start) == start
    assert resolver.resolve_end(end({"kind": "unknown"}), start) == start
    assert shape(resolver.resolve_end(end({"kind": "end_of_time"}), start)) == (
        D,
        TimeStatus.OK,
        (D, D + 1),
        "base",
    )
    explicit = resolver.resolve_end(
        end({"kind": "time_point", "time_point": absolute(5).model_dump()}), start
    )
    assert explicit.t == 5
    bad = resolver.resolve_end(
        end({"kind": "time_point", "time_point": cal(g, "day", year="2023", month="feb",
                                                      day="30").model_dump()}),
        start,
    )  # fmt: skip
    assert problem_of(bad) == (
        TimeStatus.INVALID_DATE,
        "invalid_date",
        "time_point.anchor.fields.day",
    )
    failed = resolver.resolve(cal(g, "day", year="2023", month="feb", day="30"))
    assert resolver.resolve_end(end({"kind": "duration", "duration": base(1)}), failed) == failed
    beyond = resolver.resolve_end(end({"kind": "duration", "duration": base(D)}), start)
    assert beyond.status == TimeStatus.OUT_OF_BOUNDS


def test_anchors_to_ends(resolver: Resolver, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    start = stored(resolver, "e", cal(g, "day", year="2024", month="jan", day="31"))
    spec = end({"kind": "duration", "duration": months(g, 1)})
    finish = resolver.resolve_end(spec, start)
    PINS["e", "end"] = (spec, finish.t, False)
    after = resolver.resolve(relative("e", base(DAY), "month", slot="end"))
    assert shape(after) == (
        gregorian_t(2024, 3, 1),
        TimeStatus.OK,
        (gregorian_t(2024, 3, 1), gregorian_t(2024, 3, 2)),
        "month",
    )


# --- require: problem+json ----------------------------------------------------------------------


def test_require_maps_problems_to_errors(resolver: Resolver, world: dict[str, Any]) -> None:
    g, r, repeat = world["gregorian"], world["reform"], world["repeat"]
    assert require(resolver.resolve(absolute(7))) == 7
    cases: list[tuple[TimePoint, type[InvalidInputError], str]] = [
        (cal(g, "day", year="2023", month="feb", day="29"), TimeInvalidError, "invalid_date"),
        (cal(r, "day", year="1582", month="oct", day="10"), ReformGapError, "reform_gap"),
        (cal(repeat, "year", year="2"), ReformAmbiguousError, "reform_ambiguous"),
        (absolute(D + 1), TimeInvalidError, "invalid_date"),
    ]
    for spec, error_class, code in cases:
        with pytest.raises(error_class) as raised:
            require(resolver.resolve(spec), "ext.when")
        assert raised.value.code == code
        assert raised.value.errors is not None
        assert raised.value.errors[0]["path"].startswith("ext.when")
    occurrence = point({"kind": "relative", "offset": base(0),
                        "ref": {"type": "pin.pin", "id": "a", "slot": "start",
                                "occurrence": "1"}})  # fmt: skip
    with pytest.raises(TimeNotSupportedError):
        require(resolver.resolve(occurrence))
    pin("a", None, 3)
    PINS["a", "start"] = (None, 3, True)
    trashed = resolver.resolve(relative("a", base(0), "base"))
    assert require(trashed) == 3
    with pytest.raises(TimeInvalidError):
        require(trashed, trashed=False)


# --- readers ------------------------------------------------------------------------------------


def test_readers_resolve_only_through_what_they_see(api: Api, world: dict[str, Any]) -> None:
    hidden = api.make(
        "calendar",
        "Hidden",
        visibility="private",
        ext={"definition": YEARS},
        dimension_id=world["dimension"],
    )
    pin("a", None, 5)
    with resolving(api, world, READER) as reader:
        assert reader.resolve(cal(hidden["id"], "year", year="1")).status == (
            TimeStatus.UNRESOLVED_REF
        )
        assert reader.resolve(cal(world["gregorian"], "year", year="1")).t == ORIGIN
        # Pins have no entity: only the author resolves through them.
        assert reader.resolve(relative("a", base(0), "base")).status == TimeStatus.UNRESOLVED_REF
    with resolving(api, world) as author:
        assert author.resolve(relative("a", base(0), "base")).t == 5
        assert author.resolve(cal(hidden["id"], "year", year="1")).t == 0


# --- the present moment -------------------------------------------------------------------------


def test_the_present_can_be_a_calendar_date(api: Api, world: dict[str, Any]) -> None:
    def present(calendar_id: str, year: str, month: str, day: str) -> dict[str, Any]:
        fields = {"year": year, "month": month, "day": day}
        anchor = {"kind": "calendar", "calendar_id": calendar_id, "fields": fields}
        return {"present": {"anchor": anchor, "precision": "day"}}

    dimension = api.get(world["dimension"]).json()
    moved = api.patch(dimension, ext=present(world["gregorian"], "2024", "mar", "12"))
    assert moved.status_code == 200, moved.json()
    dimension = moved.json()["entity"]
    ext = dimension["ext"]
    assert (ext["present_t"], ext["time_status"]) == (str(gregorian_t(2024, 3, 12)), "ok")
    invalid = api.patch(dimension, ext=present(world["gregorian"], "2023", "feb", "29"))
    assert [(e["path"], e["code"]) for e in problem(invalid, 422, "invalid_date")["errors"]] == [
        ("ext.present.anchor.fields.day", "invalid_date")
    ]
    gap = api.patch(dimension, ext=present(world["reform"], "1582", "oct", "10"))
    problem(gap, 422, "reform_gap")


# --- the routes ---------------------------------------------------------------------------------


def _resolve(api: Api, **body: Any) -> Any:
    return api.client.post(f"{api.base}/time/resolve", json=body)


def _convert(api: Api, **body: Any) -> Any:
    return api.client.post(f"{api.base}/time/convert", json=body)


def dump(spec: TimePoint) -> dict[str, Any]:
    return spec.model_dump(mode="json", by_alias=True)


def test_resolve_route(api: Api, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    items = [
        {"time_point": dump(cal(g, "day", year="2024", month="mar", day="12"))},
        {
            "time_point": dump(cal(g, "day", year="2024", month="jan", day="31")),
            "end": {"kind": "duration", "duration": months(g, 1)},
        },
        {"time_point": dump(absolute(ORIGIN)), "end": {"kind": "unknown"}},
        {"time_point": dump(cal(g, "day", year="2023", month="feb", day="29"))},
        {"time_point": dump(absolute(D + 1))},
    ]
    response = _resolve(api, dimension_id=world["dimension"], items=items)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["calendar_id"] == g
    first, month, open_end, invalid, late = body["items"]
    start = gregorian_t(2024, 3, 12)
    assert first["start"] == {
        "t": str(start),
        "status": "ok",
        "extent": {"lo": str(start), "hi": str(start + DAY)},
        "precision": "day",
        "approximate": False,
        "display": "12 March AD 2024",
        "error": None,
    }
    assert first["end"] is None
    assert month["end"]["t"] == str(gregorian_t(2024, 2, 29))
    assert month["end"]["display"] == "February AD 2024"
    assert open_end["end"]["display"] == "?"
    assert open_end["start"]["display"] == "1 January AD 1, 00:00:00"
    assert invalid["start"]["t"] is None
    assert invalid["start"]["status"] == "invalid_date"
    assert invalid["start"]["error"]["path"] == "anchor.fields.day"
    assert invalid["start"]["display"] is None
    assert (late["start"]["status"], late["start"]["t"]) == ("out_of_bounds", str(D + 1))

    raw = _resolve(api, dimension_id=world["dimension"], calendar_id="absolute",
                   items=items[:1]).json()  # fmt: skip
    assert raw["items"][0]["start"]["display"].startswith("t = ")
    other = _resolve(api, dimension_id=world["dimension"], calendar_id=world["repeat"],
                     items=items[:1]).json()  # fmt: skip
    # No month level there: the coarsest level that fits in the extent (a day).
    assert other["items"][0]["start"]["display"] is not None

    problem(_resolve(api, dimension_id=api.make("misc")["id"], items=[]), 404, "not_found")
    problem(
        _resolve(api, dimension_id=world["dimension"], calendar_id=str(uuid.uuid7()), items=[]),
        404,
        "not_found",
    )
    malformed = _resolve(api, dimension_id=world["dimension"], items=[{"time_point": {}}])
    problem(malformed, 422, "validation_error")


def test_resolve_route_for_readers(api: Api, world: dict[str, Any]) -> None:
    hidden = api.make(
        "calendar",
        "Hidden",
        visibility="private",
        ext={"definition": YEARS},
        dimension_id=world["dimension"],
    )
    params = {"as_reader": "true"}
    body = {
        "dimension_id": world["dimension"],
        "items": [{"time_point": dump(cal(hidden["id"], "year", year="1"))}],
    }
    response = api.client.post(f"{api.base}/time/resolve", json=body, params=params)
    assert response.status_code == 200, response.json()
    assert response.json()["items"][0]["start"]["status"] == "unresolved_ref"
    as_display = api.client.post(
        f"{api.base}/time/resolve", json={**body, "calendar_id": hidden["id"]}, params=params
    )
    problem(as_display, 404, "not_found")
    secret = api.make("dimension", visibility="private")
    hidden_dimension = {"dimension_id": secret["id"], "items": []}
    problem(
        api.client.post(f"{api.base}/time/resolve", json=hidden_dimension, params=params),
        404,
        "not_found",
    )
    problem(
        api.client.post(
            f"{api.base}/time/convert",
            json={
                "dimension_id": world["dimension"],
                "moments": ["0"],
                "calendars": [hidden["id"]],
            },
            params=params,
        ),
        404,
        "not_found",
    )


def test_convert_route(api: Api, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    t = gregorian_t(2024, 3, 12) + 3600
    response = _convert(
        api,
        dimension_id=world["dimension"],
        moments=[str(t), str(D + 1)],
        calendars=[g, "absolute", world["repeat"]],
    )
    assert response.status_code == 200, response.json()
    first, late = response.json()["items"]
    gregorian, raw, repeat = first["results"]
    assert gregorian["calendar_id"] == g
    assert gregorian["display"] == "12 March AD 2024, 01:00:00"
    assert gregorian["fields"]["levels"]["month"]["id"] == "mar"
    assert gregorian["fields"]["era"]["id"] == "ad"
    assert (raw["calendar_id"], raw["fields"], raw["error"]) == ("absolute", None, None)
    assert raw["display"].startswith("t = ")
    assert repeat["fields"]["regime"] == "new"
    assert [r["error"]["code"] for r in late["results"]] == ["out_of_bounds"] * 3

    by_day = _convert(api, dimension_id=world["dimension"], moments=[str(t)], calendars=[g],
                      precision="day").json()  # fmt: skip
    assert by_day["items"][0]["results"][0]["display"] == "12 March AD 2024"
    unknown = _convert(api, dimension_id=world["dimension"], moments=[str(t)],
                       calendars=[world["repeat"]], precision="month").json()  # fmt: skip
    assert unknown["items"][0]["results"][0]["error"]["code"] == "invalid_date"
    problem(
        _convert(api, dimension_id=world["dimension"], moments=["-1"], calendars=[g]),
        422,
        "validation_error",
    )
    problem(
        _convert(api, dimension_id=world["dimension"], moments=["1"], calendars=[]),
        422,
        "validation_error",
    )


def test_stored_points_shown_to_readers(api: Api, world: dict[str, Any]) -> None:
    annum = copy.deepcopy(YEARS)
    annum["levels"][1]["id"] = "annum"
    annum["regimes"][0]["templates"]["year"]["level"] = "annum"
    annum["regimes"][0]["alignment"]["fields"] = {"annum": "1"}
    hidden = api.make(
        "calendar",
        "Hidden",
        visibility="private",
        ext={"definition": annum},
        dimension_id=world["dimension"],
    )["id"]
    pin("a", None, ORIGIN + 5)
    dimension = world["dimension"]
    opened = _manager(api).open(api.vault)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]
    with opened.sessions() as session:
        context = VaultContext(opened, session, registry)
        times = ReaderTimes(context, READER)

        def shown(spec: TimePoint, dimension_id: str | None = dimension) -> Any:
            return times.point(dump(spec), dimension_id)

        def moment(t: int, precision: str = "base") -> dict[str, Any]:
            return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision,
                    "approximate": False}  # fmt: skip

        visible = cal(world["gregorian"], "year", year="2024")
        assert shown(visible) == dump(visible)
        assert shown(absolute(3)) == dump(absolute(3))
        # A hidden calendar: the moment; its level isn't one of the default calendar's.
        assert shown(cal(hidden, "annum", annum="2")) == moment(YEAR, "base")
        assert shown(cal(hidden, "annum", annum="2"), None) == moment(YEAR, "base")
        assert shown(cal(hidden, "day", annum="2", day="2")) == moment(YEAR + DAY, "day")
        assert shown(cal(hidden, "day", annum="2", day="400")) is None  # doesn't resolve
        # A slot of a record without an entity: hidden; the dimension comes from the caller.
        assert shown(relative("a", base(1), "base")) == moment(ORIGIN + 6)
        assert shown(relative("a", base(1), "base"), None) is None
        offset = {"kind": "calendar", "calendar_id": hidden, "amounts": {"annum": "1"}, "sign": 1}
        assert shown(point({"kind": "absolute", "t": "0"})) == moment(0)
        through = point(
            {"kind": "relative", "ref": {"type": "pin.pin", "id": "a", "slot": "start"},
             "offset": offset}, "base")  # fmt: skip
        assert shown(through, None) == moment(ORIGIN + 5 + YEAR)
        unknown = point({"kind": "relative", "ref": {"type": "nope", "id": "a", "slot": "start"},
                         "offset": base(0)})  # fmt: skip
        assert shown(unknown) is None
        assert times.point(None, dimension) is None
        assert times.point({"anchor": {"kind": "nope"}}, dimension) is None
        assert ReaderTimes(context, AUTHOR).point(dump(through), None) == dump(through)
        assert ReaderTimes(context, READER).point(dump(through), world["gregorian"]) == moment(
            ORIGIN + 5 + YEAR
        )
        assert times.point(dump(relative("a", base(1), "base")), world["gregorian"]) is None


def test_displays_fall_back_to_a_level_that_fits(api: Api, world: dict[str, Any]) -> None:
    g = world["gregorian"]
    body = {
        "dimension_id": world["dimension"],
        "calendar_id": world["repeat"],  # levels: day, year
        "items": [
            {"time_point": dump(cal(g, "month", year="2024", month="feb"))},
            {"time_point": dump(cal(g, "hour", year="2024", month="feb", day="1", hour="3"))},
        ],
    }
    month, hour = _resolve(api, **body).json()["items"]
    with resolving(api, world) as resolver:
        repeat = resolver.calendars.get(world["repeat"], "")
        assert not isinstance(repeat, Resolution)
        t = gregorian_t(2024, 2, 1)
        assert month["start"]["display"] == format_date(repeat, t, "day")  # a month holds days
        assert hour["start"]["display"] == format_date(repeat, t + 3 * 3600, "day")
