"""Slot storage (``lore.core.time.specs``) and the slot registry (``time-model.md`` §6)."""

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import JSON, String, create_engine, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from lore.chronology.schema import AbsoluteAnchor, InstantEnd, SlotRef, TimePoint, UnknownEnd
from lore.core.db.base import SoftDeleteMixin
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError
from lore.core.time import (
    EndSpecColumn,
    SlotDef,
    SlotError,
    SlotKey,
    SlotProvider,
    SlotRegistry,
    SlotUpdate,
    SlotValue,
    SpecError,
    TimeStatus,
    moment_column,
    spec_column,
    status_column,
)
from lore.core.time.slots import SlotMoment, validate_providers


class SlotsBase(DeclarativeBase):
    pass


class Happening(SoftDeleteMixin, SlotsBase):
    """Like ``events``: a start time point, an end spec and a shared status."""

    __tablename__ = "happenings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dimension_id: Mapped[str | None] = mapped_column(String)
    start_spec: Mapped[TimePoint | None] = spec_column()
    start_t: Mapped[int | None] = moment_column()
    end_spec: Mapped[Any] = spec_column(EndSpecColumn)
    end_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()


class Rule(SlotsBase):
    """Slots inside a JSON document: needs its own loader and writer."""

    __tablename__ = "x_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    exclusions: Mapped[Any] = mapped_column(JSON)


HAPPENING = SlotProvider(
    "happening",
    Happening,
    (
        SlotDef("start", referenceable=True),
        SlotDef("end", spec="end", referenceable=True),
        SlotDef("note_time", spec_column="start_spec", resolved_column="start_t"),
    ),
    dimension_column="dimension_id",
)


def _load_rules(_session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    return {key: SlotValue(None, 7, TimeStatus.OK) for key in keys}


def _write_rules(_session: Session, updates: Sequence[SlotUpdate]) -> None:
    WRITTEN.extend(updates)


def NOTHING_BEYOND(_session: Session, _dimension: str, _bound: int) -> list[SlotMoment]:  # noqa: N802
    return []


WRITTEN: list[SlotUpdate] = []
RULE = SlotProvider(
    "x.rule",
    Rule,
    (SlotDef("until"), SlotDef("exclusion:*"), SlotDef("*", referenceable=True)),
    load=_load_rules,
    write=_write_rules,
    beyond=NOTHING_BEYOND,
)
REGISTRY = SlotRegistry((HAPPENING, RULE))


def point(t: str) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": t}, "precision": "base"}


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SlotsBase.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


# --- spec columns -----------------------------------------------------------------------------


def test_spec_columns_validate_and_round_trip(session: Session) -> None:
    session.add(Happening(id="h", start_spec=point("10" * 400), end_spec={"kind": "instant"}))
    session.flush()
    session.expire_all()
    row = session.get_one(Happening, "h")
    assert row.start_spec == TimePoint(
        anchor=AbsoluteAnchor(kind="absolute", t="10" * 400), precision="base"
    )
    assert row.end_spec == InstantEnd(kind="instant")
    stored = session.execute(text("SELECT start_spec, end_spec FROM happenings")).one()
    assert '"approximate": false' in stored[0]  # defaults are stored explicitly
    assert stored[1] == '{"kind": "instant"}'


@pytest.mark.parametrize(
    ("column", "document"),
    [
        ("start_spec", {"anchor": {"kind": "absolute", "t": "-1"}, "precision": "base"}),
        ("start_spec", {**point("1"), "range": {}}),  # reserved for post-MVP
        ("start_spec", {"kind": "instant"}),
        ("end_spec", {"kind": "sometime"}),
        ("end_spec", point("1")),
    ],
)
def test_invalid_specs_are_refused(session: Session, column: str, document: Any) -> None:
    session.add(Happening(id="h", **{column: document}))
    with pytest.raises(StatementError) as caught:
        session.flush()
    assert isinstance(caught.value.orig, SpecError)


def test_moment_columns_refuse_negative_values(session: Session) -> None:
    session.add(Happening(id="h", start_t=-1))
    with pytest.raises(StatementError, match="cannot store"):
        session.flush()


# --- lookups ----------------------------------------------------------------------------------


def test_slot_lookup_and_families() -> None:
    assert REGISTRY.slot("happening", "end")[1].spec == "end"
    assert REGISTRY.slot("x.rule", "until")[1].name == "until"
    assert REGISTRY.slot("x.rule", "exclusion:0.from")[1].name == "exclusion:*"
    assert REGISTRY.slot("x.rule", "anything")[1].name == "*"
    assert not SlotDef("exclusion:*").matches("exclusion:")
    assert REGISTRY.record_types() == ["happening", "x.rule"]


def test_unknown_slots_and_record_types() -> None:
    with pytest.raises(SlotError, match="unknown record type 'ghost'") as caught:
        REGISTRY.slot("ghost", "start")
    assert caught.value.code == "unknown_slot"
    with pytest.raises(SlotError, match="happening has no time slot 'middle'") as caught:
        REGISTRY.slot("happening", "middle")
    assert caught.value.code == "unknown_slot"


def test_check_ref() -> None:
    assert REGISTRY.check_ref(SlotRef(type="happening", id="h", slot="end")).name == "end"
    assert REGISTRY.check_ref(SlotRef(type="x.rule", id="r", slot="other")).name == "*"
    for slot in ("note_time", "until", "exclusion:1.to"):
        record_type = "happening" if slot == "note_time" else "x.rule"
        with pytest.raises(SlotError, match="cannot be referenced") as caught:
            REGISTRY.check_ref(SlotRef(type=record_type, id="r", slot=slot))
        assert caught.value.code == "slot_not_referenceable"
    with pytest.raises(SlotError) as caught:
        REGISTRY.check_ref(SlotRef(type="happening", id="h", slot="middle"))
    assert caught.value.code == "unknown_slot"


# --- loading and writing ----------------------------------------------------------------------


def test_default_loader_and_writer(session: Session) -> None:
    session.add_all(
        [
            Happening(id="a", start_spec=point("5"), start_t=5, time_status="ok"),
            Happening(id="b", end_spec={"kind": "unknown"}, deleted_at=datetime.now(UTC)),
        ]
    )
    session.flush()
    keys = [SlotKey("a", "start"), SlotKey("b", "end"), SlotKey("purged", "start")]
    loaded = REGISTRY.load(session, "happening", keys)
    assert loaded == {
        keys[0]: SlotValue(TimePoint.model_validate(point("5")), 5, TimeStatus.OK),
        keys[1]: SlotValue(UnknownEnd(kind="unknown"), None, None, trashed=True),
    }

    REGISTRY.write(
        session,
        "happening",
        [
            SlotUpdate(SlotKey("a", "start"), 5, TimeStatus.CYCLE),  # keeps the last good t
            SlotUpdate(SlotKey("b", "end"), 10**300, TimeStatus.OK),
            SlotUpdate(SlotKey("a", "note_time"), 6, TimeStatus.OK),  # custom column names
        ],
    )
    session.flush()
    session.expire_all()
    a, b = session.get_one(Happening, "a"), session.get_one(Happening, "b")
    assert (a.start_t, a.time_status) == (6, "ok")
    assert (b.end_t, b.time_status) == (10**300, "ok")

    with pytest.raises(SlotError, match="not found"):
        REGISTRY.write(session, "happening", [SlotUpdate(SlotKey("x", "end"), 1, TimeStatus.OK)])
    with pytest.raises(SlotError, match="no time slot"):
        REGISTRY.load(session, "happening", [SlotKey("a", "middle")])


def test_custom_loader_and_writer(session: Session) -> None:
    key = SlotKey("r", "exclusion:0.from")
    assert REGISTRY.load(session, "x.rule", [key]) == {key: SlotValue(None, 7, TimeStatus.OK)}
    WRITTEN.clear()
    REGISTRY.write(session, "x.rule", [SlotUpdate(key, 8, TimeStatus.OK)])
    assert list(WRITTEN) == [SlotUpdate(key, 8, TimeStatus.OK)]
    with pytest.raises(SlotError, match="unknown record type"):
        REGISTRY.write(session, "ghost", [])


# --- registry validation ----------------------------------------------------------------------


def spec(module_id: str, *providers: object, models: tuple[type, ...] = ()) -> ModuleSpec:
    return ModuleSpec(
        id=module_id,
        name=module_id,
        description="",
        models=models,
        history_tables=tuple(HistoryTable.of(m) for m in models),
        slot_providers=providers,  # type: ignore[arg-type]
    )


def problems(*modules: ModuleSpec) -> list[str]:
    with pytest.raises(RegistryError) as caught:
        ModuleRegistry(modules)
    return caught.value.problems


def test_modules_register_slot_providers() -> None:
    registry = ModuleRegistry([spec("x", RULE, models=(Rule,))])
    assert registry.slot_registry().get("x.rule") is RULE


def test_slot_provider_errors() -> None:
    def provider(record_type: str, *slots: SlotDef, **values: Any) -> SlotProvider:
        values.setdefault("beyond", NOTHING_BEYOND)
        return SlotProvider(record_type, Rule, slots or (SlotDef("until"),), **values)

    custom: dict[str, Any] = {"load": _load_rules, "write": _write_rules}
    assert problems(
        spec(
            "x",
            "not a provider",
            provider("rule", **custom),
            provider("x.Bad", **custom),
            provider("x.one"),
            provider("x.two", SlotDef("Bad"), SlotDef("a"), SlotDef("a"), load=_load_rules),
            provider("x.three", SlotDef("fam:*"), id_column="uid"),
            SlotProvider("x.four", Rule, (), beyond=NOTHING_BEYOND, **custom),
            RULE,
            models=(Rule,),
        ),
        spec("y", provider("y.rule", **custom), RULE),
    ) == [
        "x: slot providers must be SlotProvider",
        "x: slot provider 'rule': record types must be named 'x.<type>'",
        "x: slot provider 'x.Bad': record types must match "
        r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?",
        "x: slot provider 'x.one': slot 'until' has no column 'until_spec'",
        "x: slot provider 'x.one': slot 'until' has no column 'until_t'",
        "x: slot provider 'x.one': slot 'until' has no column 'time_status'",
        "x: slot provider 'x.two': give both a loader and a writer, or neither",
        "x: slot provider 'x.two': slot 'Bad' must be a name, 'name:*' or '*'",
        "x: slot provider 'x.two': slot 'Bad' has no column 'Bad_spec'",
        "x: slot provider 'x.two': slot 'Bad' has no column 'Bad_t'",
        "x: slot provider 'x.two': slot 'Bad' has no column 'time_status'",
        "x: slot provider 'x.two': slot 'a' has no column 'a_spec'",
        "x: slot provider 'x.two': slot 'a' has no column 'a_t'",
        "x: slot provider 'x.two': slot 'a' has no column 'time_status'",
        "x: slot provider 'x.two': duplicate slot 'a'",
        "x: slot provider 'x.two': slot 'a' has no column 'a_spec'",
        "x: slot provider 'x.two': slot 'a' has no column 'a_t'",
        "x: slot provider 'x.two': slot 'a' has no column 'time_status'",
        "x: slot provider 'x.three': no id column 'uid'",
        "x: slot provider 'x.three': slot family 'fam:*' needs a loader and a writer",
        "x: slot provider 'x.four': declares no slots",
        "y: slot provider 'y.rule': the model isn't one of the module's models",
        "y: slot provider 'x.rule': record types must be named 'y.<type>'",
        "y: slot provider 'x.rule': the model isn't one of the module's models",
        "y: slot provider 'x.rule' is already registered by x",
    ]


def test_core_providers_are_unprefixed_and_need_mapped_models() -> None:
    rule = SlotProvider("x.rule", Rule, (SlotDef("a"),), beyond=NOTHING_BEYOND)
    assert validate_providers("core", [rule], ()) == [
        "core: slot provider 'x.rule': core record types are unprefixed",
        "core: slot provider 'x.rule': slot 'a' has no column 'a_spec'",
        "core: slot provider 'x.rule': slot 'a' has no column 'a_t'",
        "core: slot provider 'x.rule': slot 'a' has no column 'time_status'",
    ]
    thing = SlotProvider("thing", str, (SlotDef("a"),), beyond=NOTHING_BEYOND)
    assert validate_providers("core", [thing], ()) == [
        "core: slot provider 'thing': str is not a mapped table model"
    ]


def test_dimension_lookup_errors() -> None:
    def where(**values: Any) -> list[str]:
        provider = SlotProvider("happening", Happening, (SlotDef("start"),), **values)
        return validate_providers("core", [provider], ())

    assert where() == [
        "core: slot provider 'happening': give one of dimension_column and timeline_column, "
        "or a beyond query"
    ]
    assert where(dimension_column="dimension_id", timeline_column="dimension_id") == [
        "core: slot provider 'happening': give one of dimension_column and timeline_column, "
        "or a beyond query"
    ]
    assert where(dimension_column="dim", entity_column="owner", timeline_column=None) == [
        "core: slot provider 'happening': no entity column 'owner'",
        "core: slot provider 'happening': no dimension column 'dim'",
    ]
    assert where(timeline_column="tl") == [
        "core: slot provider 'happening': no timeline column 'tl'"
    ]
    family = SlotProvider(
        "x.rule", Rule, (SlotDef("a:*"),), load=_load_rules, write=_write_rules,
        dimension_column="id",
    )  # fmt: skip
    assert validate_providers("x", [family], (Rule,)) == [
        "x: slot provider 'x.rule': slot families need a beyond query"
    ]


def test_moments_beyond_by_dimension_column(session: Session) -> None:
    session.add_all(
        [
            Happening(id="a", dimension_id="d", start_t=5, end_t=50),
            Happening(id="b", dimension_id="d", start_t=10**200),
            Happening(id="c", dimension_id="other", start_t=10**300),
        ]
    )
    session.flush()
    assert REGISTRY.moments_beyond(session, "d", 6) == [
        SlotMoment("happening", "a", "end", 50),
        SlotMoment("happening", "b", "note_time", 10**200),
        SlotMoment("happening", "b", "start", 10**200),
    ]
    assert REGISTRY.moments_beyond(session, "d", 10**200) == []
