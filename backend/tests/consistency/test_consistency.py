"""The consistency engine (``consistency.md``, D8): precision-aware comparisons, incremental
checks in the write transaction, blocking and "save anyway", severities and scans, the core
rules (definite, possible and no finding) and the API."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from lore.core.consistency import rules
from lore.core.consistency.compare import Point, violates_order, worst
from lore.core.consistency.engine import ConsistencyError, hits_of, record_only
from lore.core.entities.models import Entity
from lore.core.history import recorder
from lore.core.time.models import Calendar, Event
from lore.core.time.series import series_using as using
from tests.entity_api import LinkApi, make_client, problem
from tests.queries import statements
from tests.time.test_proposals import two_months

DAY = 86_400
YEAR = 61 * DAY  # two_months(): 31 + 30 days


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
    prime = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    return {"dimension": dimension, "calendar": calendar, "prime": prime}


def at(t: int, *, approximate: bool = False) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base",
            "approximate": approximate}  # fmt: skip


def year(world: dict[str, Any], number: int) -> dict[str, Any]:
    """A year-precision date: extent ``[start, start + YEAR)``."""
    anchor = {"kind": "calendar", "calendar_id": world["calendar"]["id"],
              "fields": {"year": str(number)}}  # fmt: skip
    return {"anchor": anchor, "precision": "year"}


def until(t: int) -> dict[str, Any]:
    return {"kind": "time_point", "time_point": at(t)}


def event(api: LinkApi, world: dict[str, Any], name: str, start: Any, **body: Any) -> Any:
    ext = {"start": start, **({"end": body.pop("end")} if "end" in body else {})}
    return api.create("event", name, dimension_id=world["dimension"]["id"], ext=ext, **body)


def made(response: Any) -> dict[str, Any]:
    assert response.status_code in (200, 201), response.json()
    entity: dict[str, Any] = response.json()["entity"]
    return entity


def findings(api: LinkApi, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/consistency/findings", params=params)
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def of_rule(api: LinkApi, rule: str, **params: Any) -> list[dict[str, Any]]:
    return findings(api, rule=rule, **params)


def severity(api: LinkApi, rule: str, value: str | None) -> Any:
    return api.client.patch(f"{api.base}/consistency/rules/{rule}", json={"severity": value})


def patch(api: LinkApi, entity_id: str, **body: Any) -> Any:
    return api.patch(api.get(entity_id).json(), **body)


def vault(api: LinkApi) -> Any:
    return api.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]


def scan(api: LinkApi) -> dict[str, Any]:
    response = api.client.post(f"{api.base}/consistency/scan")
    assert response.status_code == 200, response.json()
    result: dict[str, Any] = response.json()
    return result


# --- comparisons ---------------------------------------------------------------------------------


def test_precision_aware_order() -> None:
    exact = Point.exact
    assert violates_order(exact(5), exact(4)) == "definite"
    assert violates_order(exact(4), exact(4)) is None
    assert violates_order(exact(3), exact(4)) is None
    assert violates_order(exact(5, approximate=True), exact(4)) == "possible"
    # a = 10 exactly, b somewhere in [0, 100): b may be after a.
    assert violates_order(exact(10), Point(0, 0, 100)) == "possible"
    assert violates_order(Point(100, 100, 200), Point(0, 0, 100)) == "definite"
    assert violates_order(Point(50, 50, 200), Point(60, 60, 70)) is None
    assert worst(None, "possible") == "possible"
    assert worst("possible", "definite") == "definite"
    assert worst(None, None) is None


# --- rules: sub-events, causality, duplicates ----------------------------------------------------


def test_subevent_outside_parent(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.subevent_outside_parent"
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    inside = made(event(api, world, "Battle", at(12 * DAY), end=until(13 * DAY),
                        parent_id=parent["id"]))  # fmt: skip
    assert of_rule(api, rule) == []
    early = made(event(api, world, "Skirmish", at(5 * DAY), parent_id=parent["id"]))
    [finding] = of_rule(api, rule)
    assert (finding["severity"], finding["certainty"], finding["owner"]) == (
        "warning", "definite", "core"
    )  # fmt: skip
    assert [s["id"] for s in finding["subjects"]] == [early["id"], parent["id"]]
    assert finding["subjects"][0] == {"id": early["id"], "name": "Skirmish", "kind": "event"}
    assert finding["message"] == "“Skirmish” lies outside its parent event “War”."
    assert finding["timeline_id"] == world["prime"]
    # Fixed: the finding goes away. Moving the parent instead brings it back.
    assert patch(api, early["id"], ext={"start": at(15 * DAY)}).status_code == 200
    assert of_rule(api, rule) == []
    assert patch(api, parent["id"], ext={"start": at(14 * DAY)}).status_code == 200
    assert {s["id"] for f in of_rule(api, rule) for s in f["subjects"]} == {
        inside["id"],
        parent["id"],
    }
    # A child known only to the year may start before its parent: possible, shown as info.
    vague = made(event(api, world, "Rumor", year(world, 1), parent_id=parent["id"]))
    found = {f["subjects"][0]["id"]: f for f in of_rule(api, rule)}
    assert (found[vague["id"]]["certainty"], found[vague["id"]]["severity"]) == (
        "possible", "info"
    )  # fmt: skip
    assert [f["subjects"][0]["id"] for f in findings(api, severity="info")] == [vague["id"]]
    assert findings(api, certainty="possible") == findings(api, severity="info")


def test_effect_before_cause(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.effect_before_cause"
    cause = made(event(api, world, "Spark", at(10 * DAY)))
    effect = made(event(api, world, "Fire", at(5 * DAY)))
    later = made(event(api, world, "Ash", at(20 * DAY)))
    api.made_link("core.causes", cause, later)
    assert of_rule(api, rule) == []
    link = api.made_link("core.causes", cause, effect)
    [finding] = of_rule(api, rule)
    assert [s["id"] for s in finding["subjects"]] == [effect["id"], cause["id"]]
    assert finding["certainty"] == "definite"
    # Circa: only possible.
    assert patch(api, effect["id"], ext={"start": at(5 * DAY, approximate=True)}).status_code == 200
    assert [f["certainty"] for f in of_rule(api, rule)] == ["possible"]
    # Removing the link resolves it.
    assert api.delete_link(link["id"]).status_code == 200
    assert of_rule(api, rule) == []


def test_duplicates_are_off_until_enabled(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.duplicate_name_same_time"
    first = made(event(api, world, "Council", at(10 * DAY), end=until(12 * DAY)))
    second = made(event(api, world, "council", at(11 * DAY)))
    made(event(api, world, "Council", at(30 * DAY)))  # no overlap
    assert of_rule(api, rule) == []  # off: not evaluated
    rules = {r["id"]: r for r in api.client.get(f"{api.base}/consistency/rules").json()["items"]}
    assert (rules[rule]["severity"], rules[rule]["default_severity"]) == ("off", "off")
    # Leaving off scans the rule.
    changed = severity(api, rule, "warning")
    assert changed.status_code == 200, changed.json()
    assert (changed.json()["severity"], changed.json()["findings"]) == ("warning", 1)
    [finding] = of_rule(api, rule)
    assert {s["id"] for s in finding["subjects"]} == {first["id"], second["id"]}
    # Now incremental.
    assert patch(api, second["id"], name="Senate").status_code == 200
    assert of_rule(api, rule) == []
    assert patch(api, second["id"], name="COUNCIL").status_code == 200
    assert len(of_rule(api, rule)) == 1
    # Off again: the findings are deleted.
    assert severity(api, rule, "off").json()["findings"] == 0
    assert of_rule(api, rule) == []
    assert severity(api, rule, None).json()["severity"] == "off"  # back to the default


def test_anchor_to_trashed(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.time.anchor_to_trashed"
    target = made(event(api, world, "Coronation", at(10 * DAY)))
    ref = {"type": "event", "id": target["id"], "slot": "start"}
    feast = made(event(api, world, "Feast", {"anchor": {"kind": "relative", "ref": ref,
                 "offset": {"kind": "base", "units": "60"}}, "precision": "base"}))  # fmt: skip
    assert api.delete(target["id"]).status_code == 200
    [finding] = of_rule(api, rule)
    assert [s["id"] for s in finding["subjects"]] == [feast["id"]]
    assert finding["data"]["status"] == "trashed_ref"
    assert api.restore(target["id"]).status_code == 200
    assert of_rule(api, rule) == []
    # Purging freezes the feast's anchor; findings about the purged event are gone too.
    assert api.delete(target["id"]).status_code == 200
    assert api.delete(target["id"], purge=True).status_code == 200
    assert of_rule(api, rule) == []


# --- hard rules ----------------------------------------------------------------------------------


def test_hard_rules_from_stored_data(api: LinkApi, world: dict[str, Any]) -> None:
    """Data the services refuse (imports, migrations): found by scans."""
    war = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    battle = made(event(api, world, "Battle", at(12 * DAY), parent_id=war["id"]))
    with vault(api).write_sessions.begin() as session:
        session.execute(update(Event).where(Event.entity_id == war["id"])
                        .values(end_t=5 * DAY, time_status="out_of_bounds"))  # fmt: skip
        session.execute(update(Entity).where(Entity.id == war["id"]).values(parent_id=battle["id"]))
        session.execute(update(Calendar).values(compile_status="error"))
    result = scan(api)
    assert result["rules"] >= 10
    rules = {f["rule_id"]: f for f in findings(api)}
    assert rules["core.time.end_before_start"]["subjects"][0]["id"] == war["id"]
    assert rules["core.time.out_of_bounds"]["message"] == (
        "The time of “War” lies outside the dimension's time."
    )
    assert {s["id"] for s in rules["core.parent.cycle"]["subjects"]} == {war["id"], battle["id"]}
    assert rules["core.calendar.invalid"]["subjects"][0]["id"] == world["calendar"]["id"]
    hard = ("core.time.end_before_start", "core.time.out_of_bounds", "core.parent.cycle",
            "core.calendar.invalid")  # fmt: skip
    assert {rules[r]["severity"] for r in hard} == {"error"}
    severities = [f["severity"] for f in findings(api)]
    assert severities == sorted(severities, key=["error", "warning", "info"].index)
    # Hard rules can't be configured or suppressed.
    problem(severity(api, "core.time.out_of_bounds", "off"), 422, "validation_error")
    body = {"fingerprint": rules["core.parent.cycle"]["fingerprint"], "note": "on purpose"}
    problem(api.client.post(f"{api.base}/consistency/suppressions", json=body), 422,
            "validation_error")  # fmt: skip


def test_parent_not_allowed(api: LinkApi, world: dict[str, Any]) -> None:
    calendar = world["calendar"]
    war = made(event(api, world, "War", at(10 * DAY)))
    with vault(api).write_sessions.begin() as session:
        session.execute(update(Entity).where(Entity.id == war["id"])
                        .values(parent_id=calendar["id"]))  # fmt: skip
    scan(api)
    [finding] = of_rule(api, "core.parent.not_allowed")
    assert finding["message"] == "“War” can't be placed under a calendar (“Reckoning”)."


def test_invalid_dates_accepted_by_a_calendar_proposal(api: LinkApi, world: dict[str, Any]) -> None:
    """A proposal's explicit keep_date accepts a broken record: the hard finding doesn't block."""
    fields = {"year": "1", "month": "frostfall", "day": "31"}
    anchor = {"kind": "calendar", "calendar_id": world["calendar"]["id"], "fields": fields}
    last = made(event(api, world, "Last", {"anchor": anchor, "precision": "day"}))
    url = f"{api.base}/calendars/{world['calendar']['id']}/proposals"
    proposal = api.client.post(url, json={"definition": two_months(frost=30)}).json()
    key = next(i["key"] for i in proposal["items"] if i["entity_id"] == last["id"])
    applied = api.client.post(
        f"{url}/{proposal['id']}/apply", json={"strategies": {key: "keep_date"}}
    )
    assert applied.status_code == 200, applied.json()
    [finding] = of_rule(api, "core.time.invalid_date")
    assert (finding["severity"], finding["subjects"][0]["id"]) == ("error", last["id"])
    # Fixing the date resolves it.
    assert patch(api, last["id"], ext={"start": at(DAY)}).status_code == 200
    assert of_rule(api, "core.time.invalid_date") == []


# --- blocking and suppression --------------------------------------------------------------------


def test_errors_block_until_suppressed(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.subevent_outside_parent"
    assert severity(api, rule, "error").status_code == 200
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    before = len(api.client.get(f"{api.base}/changes").json()["items"])
    blocked = problem(event(api, world, "Raid", at(5 * DAY), parent_id=parent["id"]), 422,
                      "consistency_error")  # fmt: skip
    [found] = blocked["context"]["findings"]
    assert (found["rule_id"], found["suppressible"]) == (rule, True)
    assert blocked["errors"][0]["code"] == rule
    assert len(api.client.get(f"{api.base}/changes").json()["items"]) == before  # rolled back
    # Possible findings never block.
    assert event(api, world, "Rumor", year(world, 1), parent_id=parent["id"]).status_code == 201
    # Save anyway (a create's fingerprints change with its new id: by rule). The suppression is
    # part of the write's changeset.
    suppress = [{"rule_id": rule, "note": "A raid before the war began."}]
    raid = made(event(api, world, "Raid", at(5 * DAY), parent_id=parent["id"], suppress=suppress))
    assert findings(api, rule=rule, certainty="definite") == []  # suppressed
    [suppressed] = findings(api, status="suppressed")
    assert suppressed["suppression"]["note"] == "A raid before the war began."
    assert suppressed["subjects"][0]["id"] == raid["id"]
    change = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    detail = api.client.get(f"{api.base}/changes/{change['id']}").json()
    assert "consistency_suppressions" in {c["table_name"] for c in detail["changes"]}
    # Taking the suppression back shows the finding again; suppressing it through the API too.
    fingerprint = suppressed["fingerprint"]
    assert (
        api.client.delete(f"{api.base}/consistency/suppressions/{fingerprint}").status_code == 204
    )
    assert [f["fingerprint"] for f in of_rule(api, rule, certainty="definite")] == [fingerprint]
    assert (
        api.client.delete(f"{api.base}/consistency/suppressions/{fingerprint}").status_code == 404
    )
    body = {"fingerprint": fingerprint, "note": "Fine."}
    created = api.client.post(f"{api.base}/consistency/suppressions", json=body)
    assert created.status_code == 201, created.json()
    assert created.json()["suppression"]["note"] == "Fine."
    problem(api.client.post(f"{api.base}/consistency/suppressions", json=body), 409, "conflict")
    unknown = {"fingerprint": "0" * 64, "note": "?"}
    problem(api.client.post(f"{api.base}/consistency/suppressions", json=unknown), 404, "not_found")
    # A suppress member naming no finding is refused, and so is one naming both or neither.
    problem(event(api, world, "Other", at(DAY), suppress=[unknown]), 422, "validation_error")
    by_rule = [{"rule_id": rule, "note": "?"}]
    problem(event(api, world, "Other", at(DAY), suppress=by_rule), 422, "validation_error")
    both = [{**unknown, "rule_id": rule}]
    problem(event(api, world, "Other", at(DAY), suppress=both), 422, "validation_error")


def test_body_less_writes_block_too(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.subevent_outside_parent"
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    raid = made(event(api, world, "Raid", at(5 * DAY), parent_id=parent["id"]))
    assert api.delete(raid["id"]).status_code == 200
    assert severity(api, rule, "error").status_code == 200
    blocked = problem(api.restore(raid["id"]), 422, "consistency_error")
    fingerprint = blocked["context"]["findings"][0]["fingerprint"]
    restored = api.client.post(
        f"{api.base}/entities/{raid['id']}/restore",
        json={"suppress": [{"fingerprint": fingerprint, "note": "Intended."}]},
    )
    assert restored.status_code == 200, restored.json()


def test_undo_is_checked(api: LinkApi, world: dict[str, Any]) -> None:
    rule = "core.event.subevent_outside_parent"
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    raid = made(event(api, world, "Raid", at(5 * DAY), parent_id=parent["id"]))
    assert patch(api, raid["id"], ext={"start": at(12 * DAY)}).status_code == 200
    fix = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    assert severity(api, rule, "error").status_code == 200
    url = f"{api.base}/changes/{fix['id']}/revert"
    blocked = problem(api.client.post(url), 409, "revert_conflict")
    [found] = blocked["context"]["findings"]
    assert found["rule_id"] == rule
    suppress = [{"fingerprint": found["fingerprint"], "note": "Undo it anyway."}]
    assert api.client.post(url, json={"suppress": suppress}).status_code == 200
    assert api.get(raid["id"]).json()["ext"]["start_t"] == str(5 * DAY)


def test_recurrence_rule_broken_by_a_calendar_edit(api: LinkApi, world: dict[str, Any]) -> None:
    """``core.recurrence.invalid_rule`` (configurable error): a calendar proposal that breaks a
    series' rule needs an explicit keep_date and then a "save anyway"."""
    rule = {"kind": "calendar", "calendar_id": world["calendar"]["id"], "freq": {"level": "year"},
            "select": {"path": [{"level": "month", "values": ["thawing"]}]},
            "limit": {"kind": "never"}}  # fmt: skip
    series = made(api.create("event", "Thaw feast", dimension_id=world["dimension"]["id"],
                             ext={"start": at(0), "recurrence": rule}))  # fmt: skip
    single = two_months()
    single["regimes"][0]["templates"]["year"]["sequence"] = [
        {"id": "frostfall", "template": "frost", "name": "Frostfall"}
    ]
    url = f"{api.base}/calendars/{world['calendar']['id']}/proposals"
    proposal = api.client.post(url, json={"definition": single}).json()
    key = next(i["key"] for i in proposal["items"] if i["slot"] == "recurrence")
    apply = f"{url}/{proposal['id']}/apply"
    blocked = problem(api.client.post(apply, json={"strategies": {key: "keep_date"}}), 422,
                      "consistency_error")  # fmt: skip
    [found] = blocked["context"]["findings"]
    assert (found["rule_id"], found["subjects"]) == ("core.recurrence.invalid_rule", [series["id"]])
    suppress = [{"fingerprint": found["fingerprint"], "note": "Will fix the rule later."}]
    done = api.client.post(apply, json={"strategies": {key: "keep_date"}, "suppress": suppress})
    assert done.status_code == 200, done.json()
    [suppressed] = findings(api, status="suppressed")
    assert suppressed["rule_id"] == "core.recurrence.invalid_rule"


def test_only_a_calendar_write_looks_up_its_series(
    api: LinkApi, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``series_using`` reads every series: writing events and links never calls it (a link
    write per event pair made the ``large`` sample world quadratic), a calendar edit does."""
    looked_up: list[str] = []

    def series_using(session: Any, calendar_id: str) -> list[str]:
        looked_up.append(calendar_id)
        return using(session, calendar_id)

    monkeypatch.setattr(rules, "series_using", series_using)
    a, b = made(event(api, world, "Spark", at(DAY))), made(event(api, world, "Fire", at(2 * DAY)))
    api.made_link("core.causes", a, b)
    assert looked_up == []
    assert patch(api, world["calendar"]["id"], name="Old Reckoning").status_code == 200
    assert looked_up == [world["calendar"]["id"]]


# --- API ------------------------------------------------------------------------------------------


def test_findings_api(api: LinkApi, world: dict[str, Any]) -> None:
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    children = [
        made(event(api, world, f"Raid {i}", at(i * DAY), parent_id=parent["id"]))
        for i in range(1, 4)
    ]
    assert severity(api, "core.event.subevent_outside_parent", "error").status_code == 200
    made(event(api, world, "Rumor", year(world, 1), parent_id=parent["id"]))  # possible
    cause = made(event(api, world, "Spark", at(50 * DAY)))
    api.made_link("core.causes", cause, children[0])  # a warning
    every = findings(api)
    assert [f["severity"] for f in every] == ["error", "error", "error", "warning", "info"]
    # Within a severity, newest first.
    assert [f["subjects"][0]["id"] for f in every[:3]] == [c["id"] for c in reversed(children)]
    page = api.client.get(f"{api.base}/consistency/findings", params={"limit": 2}).json()
    rest = api.client.get(f"{api.base}/consistency/findings",
                          params={"limit": 10, "cursor": page["next_cursor"]}).json()  # fmt: skip
    assert [f["fingerprint"] for f in page["items"] + rest["items"]] == [
        f["fingerprint"] for f in every
    ]
    assert rest["next_cursor"] is None
    assert len(findings(api, entity=children[0]["id"])) == 2
    assert len(findings(api, severity=["warning", "info"])) == 2
    assert len(findings(api, owner="core")) == 5
    assert findings(api, owner="world") == []
    assert len(findings(api, timeline=world["prime"])) == 5
    problem(api.client.get(f"{api.base}/consistency/findings", params={"cursor": "x"}), 422,
            "validation_error")  # fmt: skip
    # Readers see none of it.
    for path in ("findings", "rules"):
        reader = api.client.get(f"{api.base}/consistency/{path}", params={"as_reader": "true"})
        problem(reader, 404, "not_found")
    # The registry lists core's rules.
    registry = api.client.get(f"{api.base}/registry").json()
    assert "core.event.subevent_outside_parent" in {r["id"] for r in registry["consistency_rules"]}
    problem(severity(api, "core.nope.rule", "warning"), 404, "not_found")


def test_module_changes_rescan(api: LinkApi, world: dict[str, Any]) -> None:
    war = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    with vault(api).write_sessions.begin() as session:
        session.execute(update(Event).where(Event.entity_id == war["id"]).values(end_t=DAY))
    assert of_rule(api, "core.time.end_before_start") == []  # nobody looked yet
    toggled = api.modules("extra", enabled=not _enabled(api, "extra"))
    assert toggled.status_code == 200, toggled.json()
    assert len(of_rule(api, "core.time.end_before_start")) == 1


def _enabled(api: LinkApi, module_id: str) -> bool:
    modules = api.client.get(f"{api.base}/registry").json()["modules"]
    return bool(next(m for m in modules if m["id"] == module_id)["enabled"])


def test_writes_outside_the_api_are_checked(api: LinkApi, world: dict[str, Any]) -> None:
    """The CLI and scripts write through the vault's sessions: same checks, same blocking."""
    rule = "core.event.subevent_outside_parent"
    parent = made(event(api, world, "War", at(10 * DAY), end=until(20 * DAY)))
    raid = made(event(api, world, "Raid", at(12 * DAY)))
    assert severity(api, rule, "error").status_code == 200

    def move_raid_out(*, repair: bool) -> None:
        with vault(api).write_sessions.begin() as session:
            if repair:
                record_only(session)
            moved = session.get(Entity, raid["id"])
            assert moved is not None
            moved.parent_id = parent["id"]
            session.execute(update(Event).where(Event.entity_id == raid["id"]).values(start_t=DAY))

    with pytest.raises(ConsistencyError):
        move_raid_out(repair=False)
    assert api.get(raid["id"]).json()["parent_id"] is None  # refused
    # A repair session records findings without blocking.
    move_raid_out(repair=True)
    assert [f["subjects"][0]["id"] for f in of_rule(api, rule)] == [raid["id"]]


# --- large vaults (#235) -------------------------------------------------------------------------


def test_a_link_fires_link_type_triggers_only() -> None:
    """A link belongs to both its ends in history, but writing it changes neither's records:
    only rules triggered by its link type look at them."""
    row = {"link_type": "core.causes", "source_id": "a", "target_id": "b"}
    change = recorder.RecordedChange("links", "l", None, row, ("a", "b"))
    hits = hits_of(cast(Session, None), [change])  # nothing to look up
    assert hits.kinds == {}
    assert hits.link_types == {"core.causes": {"a", "b"}}
    by_id = {rule.id: rule for rule in rules.CORE_RULES}
    assert hits.subjects(by_id["core.event.effect_before_cause"]) == {"a", "b"}
    assert hits.subjects(by_id["core.event.subevent_outside_parent"]) == set()
    assert hits.subjects(by_id["core.time.end_before_start"]) == set()


def test_pair_rules_load_time_points_in_sets(api: LinkApi, world: dict[str, Any]) -> None:
    """A scan over more sub-events outside their parent (dated in every way) and more effects
    before their cause runs the same statements: points aren't loaded one by one."""
    era = made(event(api, world, "Era", at(10 * YEAR), end=until(11 * YEAR)))
    cause = made(event(api, world, "Cause", at(50 * YEAR)))
    count = 0

    def scan(pairs: int) -> tuple[int, int]:
        nonlocal count
        for _ in range(pairs):
            count += 1
            late = made(event(api, world, f"Late {count}", year(world, 20 + count),
                              parent_id=era["id"]))  # fmt: skip
            made(event(api, world, f"Later {count}", at(40 * YEAR + count),
                       end={"kind": "duration", "duration": {"kind": "base", "units": "5"}},
                       parent_id=era["id"]))  # fmt: skip
            relative = {"anchor": {"kind": "relative",
                                   "ref": {"type": "event", "id": late["id"], "slot": "start"},
                                   "offset": {"kind": "base", "units": "-3"}},
                        "precision": "base"}  # fmt: skip
            effect = made(event(api, world, f"Effect {count}", relative))
            assert api.link("core.causes", cause, effect).status_code == 201
        with statements() as seen:
            assert api.client.post(f"{api.base}/consistency/scan").status_code == 200
        return len(findings(api, limit=200)), len(seen)

    few, few_statements = scan(2)
    many, many_statements = scan(10)
    assert (few, many) == (6, 36)
    assert many_statements == few_statements
