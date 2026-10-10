"""Calendar edit proposals (``time-model.md`` §7.4, D1, R-TIME-5): impact preview, strategies
(keep the date, pin the moment, constrain invalid dates), stale detection, undo, backups and
expiry."""

import copy
from collections.abc import Iterator
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update

from lore.chronology.calendar import from_fields
from lore.chronology.presets import instantiate_preset, load_presets
from lore.chronology.schema import (
    AbsoluteAnchor,
    BaseUnit,
    CalendarAnchor,
    DurationEnd,
    TimePoint,
    TimePointEnd,
)
from lore.config import detect_spec_dir
from lore.core.db.types import utc_now
from lore.core.history import recorder
from lore.core.time import proposals
from lore.core.time.calendars import compile_document
from lore.core.time.models import Proposal
from lore.core.vaults import VaultManager
from tests.entity_api import LinkApi, make_client, problem
from tests.time.test_calendars import SECOND

DAY = 86_400
FROST, THAW = 31, 30  # month lengths (days)
YEAR = (FROST + THAW) * DAY


def two_months(frost: int = FROST, thaw: int = THAW) -> dict[str, Any]:
    """Days of 86,400 s; years of two months, Frostfall and Thawing; 1 Frostfall 1 at t = 0."""

    def month(days: int) -> dict[str, Any]:
        return {"level": "month", "uniform": {"count": str(days), "template": "day"}}

    year = [
        {"id": "frostfall", "template": "frost", "name": "Frostfall"},
        {"id": "thawing", "template": "thaw", "name": "Thawing"},
    ]
    return {
        "schema_version": 1,
        "levels": [
            {"id": "day", "label": "Day", "plural": "Days", "numbering_start": 1},
            {"id": "month", "label": "Month", "plural": "Months", "numbering_start": 1},
            {"id": "year", "label": "Year", "plural": "Years"},
        ],
        "regimes": [
            {
                "id": "default",
                "name": "Default",
                "templates": {
                    "day": {"level": "day", "uniform": {"count": str(DAY)}},
                    "frost": month(frost),
                    "thaw": month(thaw),
                    "year": {"level": "year", "sequence": year},
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
    with make_client(tmp_path) as client:
        yield LinkApi(client)


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    calendar = api.make(
        "calendar", "Reckoning", dimension_id=dimension["id"], ext={"definition": two_months()}
    )
    return {"dimension": dimension, "calendar": calendar}


def date(world: dict[str, Any], year: int, month: str, day: int | None = None) -> dict[str, Any]:
    fields = {"year": str(year), "month": month}
    if day is not None:
        fields["day"] = str(day)
    return {
        "anchor": {"kind": "calendar", "calendar_id": world["calendar"]["id"], "fields": fields},
        "precision": "day" if day is not None else "month",
    }


def event(api: LinkApi, world: dict[str, Any], name: str, start: Any, **ext: Any) -> dict[str, Any]:
    return api.make(
        "event", name, dimension_id=world["dimension"]["id"], ext={"start": start, **ext}
    )


def ext_of(api: LinkApi, entity_id: str) -> dict[str, Any]:
    found: dict[str, Any] = api.get(entity_id).json()["ext"]
    return found


def start_t(api: LinkApi, entity_id: str) -> int:
    return int(ext_of(api, entity_id)["start_t"])


def propose(api: LinkApi, world: dict[str, Any], definition: Any, status: int = 201) -> Any:
    response = api.client.post(
        f"{api.base}/calendars/{world['calendar']['id']}/proposals", json={"definition": definition}
    )
    assert response.status_code == status, response.json()
    return response.json()


def apply(api: LinkApi, world: dict[str, Any], proposal: dict[str, Any], **body: Any) -> Any:
    return api.client.post(
        f"{api.base}/calendars/{world['calendar']['id']}/proposals/{proposal['id']}/apply",
        json=body,
    )


def items(proposal: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """(entity id, slot) → item."""
    return {(item["entity_id"], item["slot"]): item for item in proposal["items"]}


def changesets(api: LinkApi) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = api.client.get(
        f"{api.base}/changes", params={"limit": 200}
    ).json()["items"]
    return found


def test_direct_edits_point_to_proposals(api: LinkApi, world: dict[str, Any]) -> None:
    event(api, world, "Thaw", date(world, 1, "thawing", 1))
    body = problem(api.patch(world["calendar"], ext={"definition": two_months(frost=30)}), 409,
                   "conflict")  # fmt: skip
    assert body["context"]["proposals"] == f"/calendars/{world['calendar']['id']}/proposals"


def test_month_length_change_keep_or_pin(api: LinkApi, world: dict[str, Any]) -> None:
    early = event(api, world, "Early", date(world, 1, "frostfall", 10))
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    one_day = {"kind": "duration", "duration": {"kind": "base", "units": str(DAY)}}
    later = event(api, world, "Later", date(world, 2, "thawing", 5), end=one_day)
    pinned = event(api, world, "Pinned", date(world, 3, "frostfall", 20))
    before = len(changesets(api))

    proposal = propose(api, world, two_months(frost=30))
    assert len(changesets(api)) == before  # a preview changes nothing
    found = items(proposal)
    assert (early["id"], "start") not in found  # 10 Frostfall 1 doesn't move
    moved = {(e["id"], slot) for e in (thaw, later, pinned) for slot in ("start", "end")}
    assert set(found) == moved
    item = found[(thaw["id"], "start")]
    assert (item["old_t"], item["new_t"]) == (str(31 * DAY), str(30 * DAY))
    assert (item["status"], item["problem"], item["name"]) == ("ok", None, "Thaw")
    assert item["old_display"] == item["new_display"] == "1 Thawing 1"  # the typed date is kept
    assert item["strategies"] == ["keep_date", "pin_moment"]
    assert found[(later["id"], "start")]["new_t"] == str(YEAR - DAY + 30 * DAY + 4 * DAY)
    assert proposal["summary"]["changed"] == 6
    assert proposal["base_revision"] == 1
    assert proposal["definition"] == two_months(frost=30)

    pin = found[(pinned["id"], "start")]["key"]
    applied = apply(api, world, proposal, strategies={pin: "pin_moment"})
    assert applied.status_code == 200, applied.json()
    result = applied.json()
    assert (result["kept"], result["pinned"], result["constrained"]) == (5, 1, 0)
    assert result["backup"] is None
    assert result["calendar"]["ext"]["definition_revision"] == 2
    assert result["calendar"]["ext"]["definition"] == two_months(frost=30)
    assert set(result["affected"]["entities"]) >= {thaw["id"], later["id"], pinned["id"]}
    assert start_t(api, early["id"]) == 9 * DAY
    assert start_t(api, thaw["id"]) == 30 * DAY
    assert int(ext_of(api, later["id"])["end_t"]) == start_t(api, later["id"]) + DAY
    pinned_ext = ext_of(api, pinned["id"])
    assert int(pinned_ext["start_t"]) == 2 * YEAR + 19 * DAY  # the old moment
    assert pinned_ext["start"] == {"anchor": {"kind": "absolute", "t": str(2 * YEAR + 19 * DAY)},
                                   "precision": "day", "approximate": False}  # fmt: skip
    assert len(changesets(api)) == before + 1  # one changeset
    # A proposal is used once.
    assert apply(api, world, proposal).status_code == 404


def test_relative_dependents_and_series_are_listed(api: LinkApi, world: dict[str, Any]) -> None:
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    after = event(api, world, "After", {
        "anchor": {"kind": "relative", "ref": {"type": "event", "id": thaw["id"], "slot": "start"},
                   "offset": {"kind": "base", "units": "60"}}, "precision": "base"})  # fmt: skip
    rule = {"kind": "calendar", "calendar_id": world["calendar"]["id"], "freq": {"level": "year"},
            "select": {"path": [{"level": "month", "values": ["thawing"]},
                                {"level": "day", "values": ["1"]}]},
            "limit": {"kind": "count", "count": "3"}}  # fmt: skip
    series = event(api, world, "Thawfeast", {"anchor": {"kind": "absolute", "t": "0"},
                                             "precision": "base"}, recurrence=rule)  # fmt: skip
    proposal = propose(api, world, two_months(frost=30))
    found = items(proposal)
    assert found[(after["id"], "start")]["new_t"] == str(30 * DAY + 60)
    [bounds] = proposal["series"]
    assert (bounds["entity_id"], bounds["name"]) == (series["id"], "Thawfeast")
    assert (bounds["old_start_t"], bounds["new_start_t"]) == (str(31 * DAY), str(30 * DAY))
    assert apply(api, world, proposal).status_code == 200
    assert start_t(api, after["id"]) == 30 * DAY + 60
    assert ext_of(api, series["id"])["series_start_t"] == str(30 * DAY)


def test_invalid_dates_need_a_strategy(api: LinkApi, world: dict[str, Any]) -> None:
    last = event(api, world, "Last", date(world, 1, "frostfall", 31))
    proposal = propose(api, world, two_months(frost=30))
    item = items(proposal)[(last["id"], "start")]
    assert (item["status"], item["problem"]["code"]) == ("invalid_date", "invalid_date")
    assert item["new_t"] is None
    assert item["constrained_t"] == str(29 * DAY)  # 30 Frostfall
    assert item["strategies"] == ["keep_date", "pin_moment", "constrain"]
    assert proposal["summary"]["by_problem"] == {"invalid_date": 1}

    body = problem(apply(api, world, proposal), 422, "proposal_unresolved")
    assert [e["path"] for e in body["errors"]] == [f"strategies.{item['key']}"]
    assert body["context"]["records"][0]["id"] == last["id"]
    assert ext_of(api, world["calendar"]["id"])["definition_revision"] == 1  # nothing changed

    # A strategy that doesn't fit the record, or an unknown record.
    wrong = problem(apply(api, world, proposal, strategies={"event/x/start": "keep_date"}), 422,
                    "validation_error")  # fmt: skip
    assert wrong["errors"][0]["code"] == "unknown_record"
    assert apply(api, world, proposal, default_strategy="constrain").status_code == 200
    constrained = ext_of(api, last["id"])
    assert constrained["start"]["anchor"]["fields"] == {"year": "1", "month": "frostfall",
                                                        "day": "30"}  # fmt: skip
    assert int(constrained["start_t"]) == 29 * DAY
    assert constrained["time_status"] == "ok"


def test_an_explicit_keep_date_accepts_a_problem(api: LinkApi, world: dict[str, Any]) -> None:
    last = event(api, world, "Last", date(world, 1, "frostfall", 31))
    proposal = propose(api, world, two_months(frost=30))
    key = items(proposal)[(last["id"], "start")]["key"]
    result = apply(api, world, proposal, strategies={key: "keep_date"})
    assert result.status_code == 200, result.json()
    assert result.json()["accepted"] == 1
    kept = ext_of(api, last["id"])
    assert (kept["time_status"], kept["start_t"]) == ("invalid_date", str(30 * DAY))  # last good
    assert kept["start"]["anchor"]["fields"]["day"] == "31"


def test_constrain_only_fits_invalid_dates(api: LinkApi, world: dict[str, Any]) -> None:
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    proposal = propose(api, world, two_months(frost=30))
    key = items(proposal)[(thaw["id"], "start")]["key"]
    body = problem(apply(api, world, proposal, strategies={key: "constrain"}), 422,
                   "validation_error")  # fmt: skip
    assert body["errors"][0]["path"] == f"strategies.{key}"


def test_stale_proposals(api: LinkApi, world: dict[str, Any]) -> None:
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    proposal = propose(api, world, two_months(frost=30))
    # A record of the calendar's dependency closure changes meanwhile.
    assert api.patch(api.get(thaw["id"]).json(),
                     ext={"start": date(world, 1, "thawing", 2)}).status_code == 200  # fmt: skip
    problem(apply(api, world, proposal), 409, "proposal_stale")
    # A new dependent is stale too.
    proposal = propose(api, world, two_months(frost=30))
    event(api, world, "New", date(world, 5, "thawing", 3))
    problem(apply(api, world, proposal), 409, "proposal_stale")
    # So is the calendar itself (another proposal applied first).
    first = propose(api, world, two_months(frost=30))
    second = propose(api, world, two_months(frost=29))
    assert apply(api, world, first).status_code == 200
    problem(apply(api, world, second), 409, "proposal_stale")
    assert start_t(api, thaw["id"]) == 31 * DAY  # 2 Thawing with 30-day Frostfalls


def test_undo_restores_every_moment(api: LinkApi, world: dict[str, Any]) -> None:
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    pinned = event(api, world, "Pinned", date(world, 2, "thawing", 1))
    last = event(api, world, "Last", date(world, 1, "frostfall", 31))
    old = {e["id"]: (ext_of(api, e["id"])["start"], start_t(api, e["id"]))
           for e in (thaw, pinned, last)}  # fmt: skip
    proposal = propose(api, world, two_months(frost=30))
    found = items(proposal)
    strategies = {found[(pinned["id"], "start")]["key"]: "pin_moment",
                  found[(last["id"], "start")]["key"]: "constrain"}  # fmt: skip
    assert apply(api, world, proposal, strategies=strategies).status_code == 200
    assert start_t(api, thaw["id"]) == 30 * DAY
    applied = changesets(api)[0]
    revert = api.client.post(f"{api.base}/changes/{applied['id']}/revert")
    assert revert.status_code == 200, revert.json()
    for entity_id, (spec, t) in old.items():
        assert (ext_of(api, entity_id)["start"], start_t(api, entity_id)) == (spec, t)
    calendar = ext_of(api, world["calendar"]["id"])
    assert calendar["definition"] == two_months()
    assert calendar["definition_revision"] == 1


def test_invalid_definitions_fail_fast(api: LinkApi, world: dict[str, Any]) -> None:
    event(api, world, "Thaw", date(world, 1, "thawing", 1))
    broken = copy.deepcopy(two_months())
    broken["regimes"][0]["top"]["pattern"]["template"] = "nope"
    body = propose(api, world, broken, status=422)
    assert body["code"] == "calendar_invalid"
    assert (
        api.client.post(
            f"{api.base}/calendars/{world['dimension']['id']}/proposals",
            json={"definition": two_months()},
        ).status_code
        == 404
    )  # not a calendar


def test_large_applies_take_a_backup(
    api: LinkApi, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proposals, "BACKUP_THRESHOLD", 1)
    event(api, world, "Thaw", date(world, 1, "thawing", 1))
    result = apply(api, world, propose(api, world, two_months(frost=30)))
    assert result.status_code == 200, result.json()
    backup = result.json()["backup"]
    assert backup.startswith("pre-calendar-proposal-")
    listed = api.client.get(f"{api.base}/backups").json()["items"]
    assert backup in [b["id"] for b in listed]


def test_the_backup_before_an_apply_restores(
    api: LinkApi, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-apply backup (deflated at the fastest level, #237) is a backup like any other:
    restored, it is the vault as it was before the apply."""
    monkeypatch.setattr(proposals, "BACKUP_THRESHOLD", 1)
    thaw = event(api, world, "Thaw", date(world, 1, "thawing", 1))
    before = start_t(api, thaw["id"])
    result = apply(api, world, propose(api, world, two_months(frost=30)))
    assert result.status_code == 200, result.json()
    assert start_t(api, thaw["id"]) != before
    download = api.client.get(f"{api.base}/backups/{result.json()['backup']}/download")
    assert download.status_code == 200
    restored = api.client.post(
        "/api/v1/vaults/restore",
        files={"file": ("backup.zip", download.content, "application/zip")},
    )
    assert restored.status_code == 201, restored.json()
    old = LinkApi(api.client, restored.json()["id"])
    assert start_t(old, thaw["id"]) == before
    assert ext_of(old, world["calendar"]["id"])["definition"] == two_months()


def test_proposals_expire(api: LinkApi, world: dict[str, Any]) -> None:
    event(api, world, "Thaw", date(world, 1, "thawing", 1))
    proposal = propose(api, world, two_months(frost=30))
    vault = api.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]
    with vault.write_sessions.begin() as session:
        past = utc_now() - timedelta(seconds=1)
        session.execute(update(Proposal).values(expires_at=past))
    assert apply(api, world, proposal).status_code == 404
    with vault.write_sessions.begin() as session:
        assert proposals.purge_expired(session) == 1
        assert session.scalars(select(Proposal)).all() == []


def _expire_all(vault: Any) -> None:
    with vault.write_sessions.begin() as session:
        session.execute(update(Proposal).values(expires_at=utc_now() - timedelta(seconds=1)))


def _proposals(vault: Any) -> list[Proposal]:
    with vault.sessions() as session:
        return list(session.scalars(select(Proposal)))


def test_expired_proposals_are_deleted_hourly_and_on_open(
    api: LinkApi, world: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    event(api, world, "Thaw", date(world, 1, "thawing", 1))
    manager = api.client.app.state.vaults  # type: ignore[attr-defined]
    vault = manager.open(api.vault)
    propose(api, world, two_months(frost=30))
    _expire_all(vault)
    now = utc_now()
    assert manager.run_scheduled_cleanup(now) == []  # just opened
    assert len(_proposals(vault)) == 1
    assert manager.run_scheduled_cleanup(now + timedelta(minutes=61)) == [api.vault]
    assert _proposals(vault) == []
    assert manager.run_scheduled_cleanup(now + timedelta(minutes=62)) == []
    # Opening a vault deletes them too.
    propose(api, world, two_months(frost=30))
    _expire_all(vault)
    manager.close()
    assert _proposals(manager.open(api.vault)) == []
    # Never on a read-only server; failures are logged.
    assert VaultManager(tmp_path, read_only=True).run_scheduled_cleanup() == []
    opened = manager.open(api.vault)
    opened.engine.dispose()
    opened.info.database_path.chmod(0o000)
    try:
        assert manager.run_scheduled_cleanup(utc_now() + timedelta(hours=2)) == []
    finally:
        opened.info.database_path.chmod(0o644)
    assert "deleting expired proposals" in caplog.text


# --- the strategies' spec rewrites ---------------------------------------------------------------


def _compiled(definition: Any) -> Any:
    base_unit = BaseUnit.model_validate(SECOND)
    return compile_document(definition, base_unit, 10**15, "c").calendar


def _calendar_point(fields: dict[str, str], precision: str = "day", **anchor: Any) -> TimePoint:
    return TimePoint.model_validate(
        {"anchor": {"kind": "calendar", "calendar_id": "c", "fields": fields, **anchor},
         "precision": precision, "approximate": True}
    )  # fmt: skip


def test_constrained_dates() -> None:
    calendar = _compiled(two_months(frost=30))
    last = _calendar_point({"year": "1", "month": "frostfall", "day": "31"})
    t, spec = proposals.constrained(calendar, "c", last, 10**15) or (None, None)
    assert t == 29 * DAY
    assert isinstance(spec, TimePoint)
    assert spec.anchor.fields == {"year": "1", "month": "frostfall", "day": "30"}  # type: ignore[union-attr]
    assert spec.approximate is True
    end = TimePointEnd(kind="time_point", time_point=last)
    t, spec = proposals.constrained(calendar, "c", end, 10**15) or (None, None)
    assert t == 29 * DAY
    assert isinstance(spec, TimePointEnd)
    assert spec.time_point.anchor.fields["day"] == "30"  # type: ignore[union-attr]
    # Not a date of this calendar, not a calendar date, a precision that isn't a level, or a
    # constrained moment outside the dimension: nothing to constrain.
    assert proposals.constrained(calendar, "other", last, 10**15) is None
    absolute = TimePoint.model_validate(
        {"anchor": {"kind": "absolute", "t": "5"}, "precision": "base"}
    )
    assert proposals.constrained(calendar, "c", absolute, 10**15) is None
    assert (
        proposals.constrained(calendar, "c", _calendar_point({"year": "1"}, "week"), 10**15) is None
    )
    assert proposals.constrained(calendar, "c", last, DAY) is None
    assert proposals.constrained(calendar, "c", None, 10**15) is None


def test_constrained_era_dates() -> None:
    spec_dir = detect_spec_dir()
    assert spec_dir is not None
    preset = load_presets(spec_dir)["alternating-years"]
    calendar = _compiled(instantiate_preset(preset, Fraction(1), origin=10**12).model_dump(
        mode="json", by_alias=True, exclude_unset=True))  # fmt: skip
    # 1 BF is an even year: Ash has 30 days.
    ash = _calendar_point({"year": "1", "month": "ash", "day": "31"}, era="bf")
    found = proposals.constrained(calendar, "c", ash, 10**15)
    assert found is not None
    t, spec = found
    assert isinstance(spec, TimePoint)
    assert isinstance(spec.anchor, CalendarAnchor)
    assert (spec.anchor.era, spec.anchor.fields) == ("bf", {"year": "1", "month": "ash",
                                                             "day": "30"})  # fmt: skip
    assert from_fields(calendar, spec.anchor.fields, "day", era="bf") == t


def test_pinned_specs() -> None:
    day = _calendar_point({"year": "1", "month": "frostfall", "day": "3"})
    kept = proposals.pinned(day, 42, lambda level: True)
    assert (kept.anchor, kept.precision, kept.approximate) == (  # type: ignore[union-attr]
        AbsoluteAnchor(kind="absolute", t="42"),
        "day",
        True,
    )
    assert proposals.pinned(day, 42, lambda level: False).precision == "base"  # type: ignore[union-attr]
    end = proposals.pinned(TimePointEnd(kind="time_point", time_point=day), 42, lambda _l: True)
    assert isinstance(end, TimePointEnd)
    assert end.time_point.precision == "day"
    duration = DurationEnd.model_validate({"kind": "duration",
                                           "duration": {"kind": "base", "units": "5"}})  # fmt: skip
    pinned_duration = proposals.pinned(duration, 42, lambda _l: True)
    assert isinstance(pinned_duration, TimePointEnd)
    assert (pinned_duration.time_point.precision, pinned_duration.time_point.approximate) == (
        "base", False
    )  # fmt: skip
