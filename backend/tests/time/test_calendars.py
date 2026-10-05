"""Calendars: storage, validation, the compile cache, presets, preview and the dimension wizard
(``chronology-engine.md`` §4, §13; ``time-model.md`` §3)."""

import copy
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lore.config import detect_spec_dir
from lore.core.history import recorder
from lore.core.modules import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.time import CalendarNode, DependencyIndex, SlotNode
from lore.core.time.cache import CALENDARS
from lore.core.time.calendars import AbsoluteLens, compiled_calendar, lens
from lore.core.time.slots import SlotKey, SlotUpdate
from lore.core.time.status import TimeStatus
from lore.core.vaults import VaultManager
from tests.entity_api import DIMENSION_EXT, Api, make_client, problem

SECOND = DIMENSION_EXT["base_unit"]
PRESETS = sorted(path.stem for path in (detect_spec_dir() or Path()).glob("chronology/presets/*"))

# Days of 86,400 s in years of 365 days, year 1 at t = 0 (the v0.1.0 backfill's calendar).
YEARS: dict[str, Any] = {
    "schema_version": 1,
    "levels": [
        {"id": "day", "label": "Day", "plural": "Days"},
        {"id": "year", "label": "Year", "plural": "Years"},
    ],
    "regimes": [
        {
            "id": "default",
            "name": "Default",
            "templates": {
                "day": {"level": "day", "uniform": {"count": "86400"}},
                "year": {"level": "year", "uniform": {"count": "365", "template": "day"}},
            },
            "top": {"pattern": {"kind": "fixed", "template": "year"}},
            "alignment": {
                "fields": {"year": "1"},
                "at": {"anchor": {"kind": "absolute", "t": "0"}, "precision": "year"},
            },
        }
    ],
}


def years(**changes: Any) -> dict[str, Any]:
    definition = copy.deepcopy(YEARS)
    definition["regimes"][0]["alignment"]["at"]["anchor"].update(changes)
    return definition


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path) as client:
        yield Api(client)


def wizard(api: Api, source: dict[str, Any], duration: int = 10**20, **body: Any) -> Any:
    return api.client.post(
        f"{api.base}/dimensions",
        json={
            "name": "Aetheria",
            "ext": {"base_unit": SECOND, "duration": str(duration)},
            "calendar": {"name": "Reckoning", "source": source},
            **body,
        },
    )


def calendar(api: Api, dimension: dict[str, Any], definition: Any, name: str = "Cal") -> Any:
    return api.create(
        "calendar", name, dimension_id=dimension["id"], ext={"definition": definition}
    )


def errors(response: Any) -> list[tuple[str, str]]:
    body = problem(response, 422, "calendar_invalid")
    return [(e["code"], e["path"]) for e in body["errors"]]


def fresh(api: Api, entity_id: str) -> dict[str, Any]:
    response = api.get(entity_id)
    assert response.status_code == 200, response.json()
    entity: dict[str, Any] = response.json()
    return entity


def changesets(api: Api) -> int:
    page = api.client.get(f"{api.base}/changes", params={"limit": 200}).json()
    return len(page["items"])


# --- the wizard ---------------------------------------------------------------------------------


def test_there_are_presets() -> None:
    assert "gregorian" in PRESETS
    assert len(PRESETS) >= 8


@pytest.mark.parametrize("preset", PRESETS)
def test_wizard_with_each_preset(api: Api, preset: str) -> None:
    before = changesets(api)
    response = wizard(api, {"preset": {"id": preset}}, visibility="spoiler")
    assert response.status_code == 201, response.json()
    created = response.json()
    dimension, prime, cal = created["dimension"], created["prime_timeline"], created["calendar"]
    assert dimension["ext"]["default_calendar_id"] == cal["id"]
    assert dimension["ext"]["prime_timeline_id"] == prime["id"]
    assert (prime["name"], prime["visibility"]) == ("Prime", "spoiler")
    assert cal["dimension_id"] == dimension["id"]
    assert cal["ext"]["compile_status"] == "ok"
    assert cal["ext"]["definition_revision"] == 1
    assert changesets(api) == before + 1  # one transaction, one changeset


def test_wizard_with_a_definition_and_a_coarser_base_unit(api: Api) -> None:
    created = wizard(api, {"definition": YEARS}).json()
    assert created["calendar"]["ext"]["definition"] == YEARS
    assert created["calendar"]["ext"]["resolved_anchors"] == {"/regimes/0/alignment/at": "0"}

    day = {"num": "86400", "den": "1"}
    days = wizard(api, {"preset": {"id": "gregorian", "seconds_per_base_unit": day, "origin": "5"}})
    assert days.status_code == 201, days.json()
    definition = days.json()["calendar"]["ext"]["definition"]
    assert definition["levels"][0]["id"] == "day"


def test_wizard_errors_change_nothing(api: Api) -> None:
    before = changesets(api)
    unknown = problem(wizard(api, {"preset": {"id": "nope"}}), 422, "validation_error")
    assert [e["path"] for e in unknown["errors"]] == ["calendar.source.preset.id"]
    odd = {"num": "7", "den": "1"}  # no Gregorian level lasts a whole number of 7 s units
    incompatible = wizard(api, {"preset": {"id": "gregorian", "seconds_per_base_unit": odd}})
    assert [
        (e["path"], e["code"]) for e in problem(incompatible, 422, "preset_incompatible")["errors"]
    ] == [("calendar.source.preset.seconds_per_base_unit", "preset.incompatible_base_unit")]
    both = wizard(api, {"definition": YEARS, "preset": {"id": "gregorian"}})
    assert [e["path"] for e in problem(both, 422, "validation_error")["errors"]] == [
        "calendar.source.source"
    ]
    assert errors(wizard(api, {"definition": years(t="11")}, duration=10)) == [
        ("anchor.out_of_bounds", "/regimes/0/alignment/at/anchor/t")
    ]
    bad_spec = problem(wizard(api, {"definition": YEARS}, duration=0), 422, "validation_error")
    assert [e["path"] for e in bad_spec["errors"]] == ["ext.duration"]
    assert changesets(api) == before
    entities = api.client.get(f"{api.base}/entities").json()["items"]
    assert entities == []


# --- validation ---------------------------------------------------------------------------------


def test_invalid_definitions_report_engine_errors_with_pointers(api: Api) -> None:
    dimension = api.make("dimension")
    broken = copy.deepcopy(YEARS)
    broken["regimes"][0]["templates"]["year"]["level"] = "month"
    assert errors(calendar(api, dimension, broken)) == [
        ("template.unknown_level", "/regimes/0/templates/year/level")
    ]
    schema = copy.deepcopy(YEARS)
    del schema["regimes"][0]["alignment"]
    assert errors(calendar(api, dimension, schema)) == [("schema.invalid", "/regimes/0/alignment")]
    zero = copy.deepcopy(YEARS)
    zero["regimes"][0]["templates"]["day"]["uniform"]["count"] = "0"
    assert errors(calendar(api, dimension, zero)) == [
        ("template.zero_length", "/regimes/0/templates/day/uniform/count")
    ]
    assert (
        problem(api.create("calendar", dimension_id=dimension["id"]), 422, "validation_error")[
            "errors"
        ][0]["path"]
        == "ext.definition"
    )


def test_anchors_must_be_absolute_and_within_the_dimension(api: Api) -> None:
    dimension = api.make("dimension")  # D = 10^12
    relative = copy.deepcopy(YEARS)
    relative["regimes"][0]["alignment"]["at"]["anchor"] = {
        "kind": "relative",
        "ref": {"type": "event", "id": "e1", "slot": "start"},
        "offset": {"kind": "base", "units": "0"},
    }
    assert errors(calendar(api, dimension, relative)) == [
        ("anchor.not_supported", "/regimes/0/alignment/at/anchor/kind")
    ]
    assert errors(calendar(api, dimension, years(t=str(10**12 + 1)))) == [
        ("anchor.out_of_bounds", "/regimes/0/alignment/at/anchor/t")
    ]
    assert calendar(api, dimension, years(t=str(10**12))).status_code == 201


# --- edits ----------------------------------------------------------------------------------------


def _manager(api: Api) -> VaultManager:
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    return manager


def test_definition_edits_and_dependents(api: Api) -> None:
    dimension = api.make("dimension")
    cal = calendar(api, dimension, YEARS).json()["entity"]
    same = api.patch(cal, ext={"definition": YEARS}).json()["entity"]
    assert same["ext"]["definition_revision"] == 1  # nothing changed
    moved = api.patch(same, ext={"definition": years(t="100")})
    assert moved.status_code == 200, moved.json()
    assert moved.json()["entity"]["ext"]["definition_revision"] == 2
    assert errors(api.patch(moved.json()["entity"], ext={"definition": {"levels": []}}))
    renamed = api.patch(moved.json()["entity"], name="Renamed")
    assert renamed.status_code == 200, renamed.json()

    with _manager(api).open(api.vault).write_sessions.begin() as session:
        DependencyIndex(session).replace_edges(
            SlotNode("event", "e1", "start"), [CalendarNode(cal["id"])]
        )
    refused = problem(api.patch(fresh(api, cal["id"]), ext={"definition": YEARS}), 409, "conflict")
    assert refused["context"] == {"dependents": 1, "proposals": f"/calendars/{cal['id']}/proposals"}
    api.delete(cal["id"])
    blocked = problem(api.delete(cal["id"], purge=True), 409, "conflict")
    assert "depend on this calendar" in blocked["detail"]


def test_compiled_calendars_are_cached(api: Api) -> None:
    dimension = api.make("dimension")
    cal = calendar(api, dimension, YEARS).json()["entity"]
    opened = _manager(api).open(api.vault)
    registry: ModuleRegistry = api.client.app.state.registry  # type: ignore[attr-defined]
    CALENDARS.clear()

    def compile_it() -> Any:
        with opened.sessions() as session:
            return compiled_calendar(VaultContext(opened, session, registry), cal["id"])

    first = compile_it()
    assert (CALENDARS.hits, CALENDARS.misses) == (0, 1)
    assert compile_it() is first
    assert (CALENDARS.hits, CALENDARS.misses) == (1, 1)
    api.patch(cal, ext={"definition": years(t="5")})  # a new revision misses
    assert compile_it() is not first
    assert CALENDARS.misses == 2
    api.patch(fresh(api, dimension["id"]), ext={"duration": str(10**13)})  # a new context too
    compile_it()
    assert CALENDARS.misses == 3
    CALENDARS.forget_vault(api.vault)
    compile_it()
    assert CALENDARS.misses == 4

    with opened.sessions() as session:
        context = VaultContext(opened, session, registry)
        assert lens(context, dimension["id"], "absolute") == AbsoluteLens(
            base_unit=compile_it().context.base_unit
        )
        assert lens(context, dimension["id"], cal["id"]) is compile_it()
        other = api.make("dimension")
        with pytest.raises(Exception, match="No calendar"):
            lens(context, other["id"], cal["id"])


# --- the default calendar -------------------------------------------------------------------------


def test_default_calendar_rules(api: Api) -> None:
    dimension = api.make("dimension")
    first = calendar(api, dimension, YEARS, "First").json()["entity"]
    second = calendar(api, dimension, YEARS, "Second").json()["entity"]
    assert fresh(api, dimension["id"])["ext"]["default_calendar_id"] == first["id"]  # the first

    problem(api.delete(first["id"]), 409, "conflict")
    other = api.make("dimension")
    foreign = calendar(api, other, YEARS).json()["entity"]
    for value in (foreign["id"], None, "nope"):
        response = api.patch(fresh(api, dimension["id"]), ext={"default_calendar_id": value})
        assert [e["path"] for e in problem(response, 422, "validation_error")["errors"]] == [
            "ext.default_calendar_id"
        ]
    api.delete(second["id"])
    trashed = api.patch(fresh(api, dimension["id"]), ext={"default_calendar_id": second["id"]})
    assert (
        problem(trashed, 422, "validation_error")["detail"]
        == "The default calendar is in the trash."
    )
    api.restore(second["id"])
    switched = api.patch(fresh(api, dimension["id"]), ext={"default_calendar_id": second["id"]})
    assert switched.status_code == 200, switched.json()

    assert api.delete(first["id"]).status_code == 200  # no longer the default
    assert api.delete(first["id"], purge=True).status_code == 200
    # the only calendar left: it can be trashed (the default stays) and purged (the default goes)
    assert api.delete(second["id"]).status_code == 200
    assert fresh(api, dimension["id"])["ext"]["default_calendar_id"] == second["id"]
    assert api.delete(second["id"], purge=True).status_code == 200
    assert fresh(api, dimension["id"])["ext"]["default_calendar_id"] is None


def test_calendar_anchors_count_for_the_dimension_duration(api: Api) -> None:
    dimension = api.make("dimension")  # D = 10^12
    cal = calendar(api, dimension, years(t="5000")).json()["entity"]
    refused = problem(api.patch(dimension, ext={"duration": "4999"}), 422, "time_constraint")
    assert refused["context"]["records"] == [
        {"record_type": "calendar", "id": cal["id"], "slot": "alignment:default", "t": "5000"}
    ]


def test_undo_the_wizard(api: Api) -> None:
    created = wizard(api, {"preset": {"id": "gregorian"}}).json()
    changeset = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    undone = api.client.post(f"{api.base}/changes/{changeset['id']}/revert")
    assert undone.status_code == 200, undone.json()
    for key in ("dimension", "prime_timeline", "calendar"):
        assert api.get(created[key]["id"]).status_code == 404


# --- presets and preview ------------------------------------------------------------------------


def test_presets(api: Api) -> None:
    response = api.client.get(f"{api.base}/calendars/presets")
    assert response.status_code == 200, response.json()
    items = response.json()["items"]
    assert [item["id"] for item in items] == PRESETS
    gregorian = next(item for item in items if item["id"] == "gregorian")
    assert gregorian["duration_seconds"] == "63089134500"  # its latest absolute anchor
    assert gregorian["definition"]["levels"][0]["id"] == "second"


def _preview(api: Api, **body: Any) -> Any:
    return api.client.post(f"{api.base}/calendars/preview", json=body)


def test_preview(api: Api) -> None:
    spec = {"base_unit": SECOND, "duration": str(10**20)}
    result = _preview(api, time_spec=spec, source={"preset": {"id": "gregorian"}})
    assert result.status_code == 200, result.json()
    body = result.json()
    assert (body["ok"], body["errors"]) == (True, [])
    assert [s["t"] for s in body["samples"]][:2] == ["0", str(365 * 86400)]
    assert body["samples"][0]["display"].startswith("1 January")
    assert body["samples"][0]["fields"]["levels"]["year"]["n"] == "1"
    assert len(body["samples"]) == 5

    dimension = api.make("dimension")
    invalid = _preview(api, dimension_id=dimension["id"], source={"definition": years(t="-1")})
    assert invalid.status_code == 200, invalid.json()
    assert invalid.json()["ok"] is False
    assert [e["path"] for e in invalid.json()["errors"]] == ["/regimes/0/alignment/at/anchor/t"]
    short = _preview(api, dimension_id=dimension["id"], source={"definition": years(t="10")})
    # from the alignment (year 1 starts at t = 10) on
    assert [s["t"] for s in short.json()["samples"]] == [
        str(10 + year * 365 * 86400) for year in range(5)
    ]

    neither = _preview(api, source={"definition": YEARS})
    assert [e["path"] for e in problem(neither, 422, "validation_error")["errors"]] == [
        "dimension_id"
    ]
    problem(
        _preview(api, dimension_id=api.make("misc")["id"], source={"definition": YEARS}),
        404,
        "not_found",
    )
    unknown = _preview(api, time_spec=spec, source={"preset": {"id": "nope"}})
    assert [e["path"] for e in problem(unknown, 422, "validation_error")["errors"]] == [
        "source.preset.id"
    ]


def test_calendar_anchors_are_slots(api: Api) -> None:
    dimension = api.make("dimension")
    cal = calendar(api, dimension, years(t="7")).json()["entity"]
    opened = _manager(api).open(api.vault)
    registry = api.client.app.state.registry.slot_registry()  # type: ignore[attr-defined]
    alignment = SlotKey(cal["id"], "alignment:default")
    with opened.write_sessions.begin() as session:
        loaded = registry.load(session, "calendar", [alignment, SlotKey(cal["id"], "era:none")])
        assert list(loaded) == [alignment]
        assert (loaded[alignment].t, loaded[alignment].status) == (7, TimeStatus.OK)
        assert loaded[alignment].spec is not None
        registry.write(session, "calendar", [SlotUpdate(alignment, 9, TimeStatus.OK)])
    assert fresh(api, cal["id"])["ext"]["resolved_anchors"] == {"/regimes/0/alignment/at": "9"}
    api.delete(cal["id"])
    with opened.sessions() as session:
        assert registry.load(session, "calendar", [alignment])[alignment].trashed is True
