"""Base-unit refinement (``time-model.md`` §3.1, #152; ``lore vault refine-base-unit``)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.chronology.refine import (
    RefineError,
    refine_definition,
    refine_json,
    refine_point,
    refine_rate,
    refine_rule,
)
from lore.core.history import recorder
from lore.core.maintenance import refine_dimension_base_unit
from lore.core.vaults import VaultManager
from tests.conftest import local_client
from tests.entity_api import HEADERS, YEARS, LinkApi, new_app, problem
from tests.history_utils import changesets

DAY = 86_400


def absolute(t: int, precision: str = "base") -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision}


def year(n: int, calendar_id: str) -> dict[str, Any]:
    anchor = {"kind": "calendar", "calendar_id": calendar_id, "fields": {"year": str(n)}}
    return {"anchor": anchor, "precision": "year"}


# --- the documents --------------------------------------------------------------------------------


def test_points_scale_absolute_moments_and_base_offsets_only() -> None:
    relative: dict[str, Any] = {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": "e", "slot": "start"},
            "offset": {"kind": "base", "units": "-5"},
        },
        "precision": "base",
    }
    ranged = {**year(3, "c"), "range": {"earliest": absolute(10), "latest": relative}}
    assert refine_point(ranged, 1000) == {
        **year(3, "c"),
        "range": {
            "earliest": absolute(10_000),
            "latest": {
                **relative,
                "anchor": {**relative["anchor"], "offset": {"kind": "base", "units": "-5000"}},
            },
        },
    }
    calendar_offset = {"kind": "calendar", "calendar_id": "c", "amounts": {"day": "2"}, "sign": 1}
    assert refine_json(calendar_offset, 1000) == calendar_offset


def test_documents_scale_nested_time_points_and_base_durations() -> None:
    body = {
        "type": "doc",
        "content": [{"type": "timeRef", "attrs": {"timePoint": absolute(7)}}],
    }
    assert refine_json(body, 10)["content"][0]["attrs"]["timePoint"] == absolute(70)
    end = {"kind": "duration", "duration": {"kind": "base", "units": "3"}}
    assert refine_json(end, 10) == {"kind": "duration", "duration": {"kind": "base", "units": "30"}}
    # A field value that merely looks like a duration isn't one.
    assert refine_json({"kind": "base", "units": "3", "note": "x"}, 10)["units"] == "3"


def test_rules_scale_intervals_limits_and_exclusions() -> None:
    rule = {
        "kind": "interval",
        "every": "60",
        "limit": {"kind": "until", "until": absolute(600)},
        "exclusions": [{"from": absolute(120), "to": absolute(180)}],
    }
    assert refine_rule(rule, 1000) == {
        "kind": "interval",
        "every": "60000",
        "limit": {"kind": "until", "until": absolute(600_000)},
        "exclusions": [{"from": absolute(120_000), "to": absolute(180_000)}],
    }


def test_definitions_scale_the_finest_level_and_overlay_periods() -> None:
    definition = {
        **YEARS,
        "overlays": [
            {"id": "moon", "name": "Moon", "period": {"num": "2551443", "den": "1"},
             "epoch": absolute(5)},
        ],
    }  # fmt: skip
    refined = refine_definition(definition, 1000)
    templates = refined["regimes"][0]["templates"]
    assert templates["day"]["uniform"]["count"] == "86400000"
    assert templates["year"] == YEARS["regimes"][0]["templates"]["year"]
    assert refined["regimes"][0]["alignment"]["at"] == absolute(0, "year")
    assert refined["overlays"][0]["period"] == {"num": "2551443000", "den": "1"}
    assert refined["overlays"][0]["epoch"] == absolute(5000)
    runs = {**YEARS["regimes"][0]["templates"]}
    runs["day"] = {"level": "day", "sequence": [{"run": {"count": "86400"}}]}
    with_runs = {**YEARS, "regimes": [{**YEARS["regimes"][0], "templates": runs}]}
    sequence = refine_definition(with_runs, 2)["regimes"][0]["templates"]["day"]["sequence"]
    assert sequence == [{"run": {"count": "172800"}}]
    named = {"id": "tick", "template": "day", "name": "Tick"}
    runs["day"] = {"level": "day", "sequence": [named]}
    with pytest.raises(RefineError) as error:
        refine_definition(with_runs, 2)
    assert error.value.code == "refine.named_base_units"


def test_rates() -> None:
    assert refine_rate({"num": "3", "den": "2"}, 1, 1000) == {"num": "3", "den": "2000"}
    assert refine_rate({"num": "3", "den": "2"}, 1000) == {"num": "1500", "den": "1"}


# --- a vault --------------------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return new_app(tmp_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> LinkApi:
    return LinkApi(client)


@pytest.fixture(autouse=True)
def _no_merging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    calendar = api.calendar(dimension["id"])
    return {"dimension": dimension, "calendar": calendar}


def refine(app: FastAPI, api: LinkApi, dimension: str, factor: int, **options: Any) -> Any:
    manager: VaultManager = app.state.vaults
    return refine_dimension_base_unit(manager, api.vault, dimension, factor, **options)


def ext(api: LinkApi, entity_id: str) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity_id).json()["ext"]
    return found


def test_dates_stay_and_moments_scale(app: FastAPI, api: LinkApi, world: dict[str, Any]) -> None:
    dimension, calendar = world["dimension"], world["calendar"]["id"]
    crowned = api.make(
        "event", "Crowned", dimension_id=dimension["id"],
        ext={"start": year(3, calendar),
             "end": {"kind": "duration", "duration": {"kind": "base", "units": str(DAY)}}},
    )  # fmt: skip
    fixed = api.make(
        "event", "Fixed", dimension_id=dimension["id"], ext={"start": absolute(5 * DAY)}
    )
    before = ext(api, crowned["id"])
    old_d = int(ext(api, dimension["id"])["duration"])
    found = refine(
        app, api, "Aetheria", 1000,
        base_unit={"singular": "millisecond", "plural": "milliseconds", "abbr": "ms"},
    )  # fmt: skip
    assert found.backup_id is not None
    report = found.report
    assert report.duration == old_d * 1000
    assert report.rewritten["events"] == 2
    assert report.problems_after == report.problems_before == 0
    after = ext(api, crowned["id"])
    assert after["start"]["anchor"]["fields"] == {"year": "3"}
    assert int(after["start_t"]) == int(before["start_t"]) * 1000
    assert int(after["end_t"]) == int(before["end_t"]) * 1000
    assert after["end"]["duration"] == {"kind": "base", "units": str(DAY * 1000)}
    assert after["display"]["start"] == before["display"]["start"]
    assert ext(api, fixed["id"])["start"]["anchor"]["t"] == str(5 * DAY * 1000)
    refined_dimension = ext(api, dimension["id"])
    assert int(refined_dimension["duration"]) == old_d * 1000
    assert refined_dimension["base_unit"]["abbr"] == "ms"
    definition = ext(api, calendar)["definition"]
    assert definition["regimes"][0]["templates"]["day"]["uniform"]["count"] == str(DAY * 1000)


def test_relative_anchors_and_series_follow(
    app: FastAPI, api: LinkApi, world: dict[str, Any]
) -> None:
    dimension = world["dimension"]["id"]
    war = api.make("event", "War", dimension_id=dimension, ext={"start": absolute(10 * DAY)})
    offset = {"kind": "base", "units": str(DAY)}
    after = {"anchor": {"kind": "relative", "ref": {"type": "event", "id": war["id"],
             "slot": "start"}, "offset": offset}, "precision": "base"}  # fmt: skip
    peace = api.make("event", "Peace", dimension_id=dimension, ext={"start": after})
    rule = {"kind": "interval", "every": str(7 * DAY), "limit": {"kind": "count", "count": "3"}}
    market = api.make(
        "event", "Market", dimension_id=dimension,
        ext={"start": absolute(DAY), "recurrence": rule},
    )  # fmt: skip
    refine(app, api, dimension, 60)
    assert int(ext(api, peace["id"])["start_t"]) == 11 * DAY * 60
    assert ext(api, market["id"])["recurrence"]["every"] == str(7 * DAY * 60)
    occurrences = api.client.get(
        f"{api.base}/events/{market['id']}/occurrences",
        params={"from": "0", "to": str(100 * DAY * 60)},
    ).json()["items"]
    assert [int(o["start_t"]) for o in occurrences] == [DAY * 60 * (1 + 7 * i) for i in range(3)]


def test_a_dry_run_changes_nothing(app: FastAPI, api: LinkApi, world: dict[str, Any]) -> None:
    event = api.make(
        "event", "E", dimension_id=world["dimension"]["id"], ext={"start": absolute(DAY)}
    )
    found = refine(app, api, world["dimension"]["id"], 10, dry_run=True)
    assert found.backup_id is None
    assert found.report.rewritten["events"] == 1
    assert ext(api, event["id"])["start_t"] == str(DAY)


def test_history_before_a_refinement_cant_be_undone(
    app: FastAPI, api: LinkApi, world: dict[str, Any]
) -> None:
    dimension = world["dimension"]["id"]
    api.make("event", "Before", dimension_id=dimension, ext={"start": absolute(DAY)})
    earlier = changesets(app, api.vault)[-1]["id"]
    refine(app, api, dimension, 10)
    refinement = changesets(app, api.vault)[-1]
    assert refinement["origin"] == "refinement"
    later = api.make("event", "After", dimension_id=dimension, ext={"start": absolute(DAY)})
    for changeset_id in (earlier, refinement["id"]):
        response = api.client.post(f"{api.base}/changes/{changeset_id}/revert")
        problem(response, 409, "conflict")
    last = changesets(app, api.vault)[-1]["id"]
    assert api.client.post(f"{api.base}/changes/{last}/revert").status_code == 200
    assert api.get(later["id"]).status_code == 404


def test_refusals(app: FastAPI, api: LinkApi, world: dict[str, Any]) -> None:
    with pytest.raises(Exception, match="No dimension"):
        refine(app, api, "Nowhere", 10)
    with pytest.raises(Exception, match="factor"):
        refine(app, api, world["dimension"]["id"], 1)


def test_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = LinkApi(client)
        dimension = api.make("dimension", "Aetheria")
        calendar = api.calendar(dimension["id"])
        api.make("event", "E", dimension_id=dimension["id"], ext={"start": year(2, calendar["id"])})
        vault = api.vault
    runner = CliRunner()
    args = ["vault", "refine-base-unit", vault, "--dimension", "Aetheria", "--factor", "1000"]
    dry = runner.invoke(cli.app, [*args, "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "would rewrite" in dry.output
    bad = runner.invoke(cli.app, [*args, "--unit", "ms"])
    assert bad.exit_code == 2
    done = runner.invoke(cli.app, [*args, "--unit", "millisecond,milliseconds,ms"])
    assert done.exit_code == 0, done.output
    assert "backup taken before" in done.output
    # Every stored moment is what its spec resolves to now.
    check = runner.invoke(cli.app, ["vault", "check", vault])
    assert check.exit_code == 0, check.output
