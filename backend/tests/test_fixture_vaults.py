"""Golden fixture vaults (``persistence-and-migrations.md`` §3.5) and the sample world generator
(``testing.md`` §2).

Every ``tests/fixtures/vaults/v<version>/`` (a vault folder written by an app release, and the
``expected.json`` the generator wrote with it) is upgraded to head on a copy, checked with
``lore vault check``'s checks and smoke-tested through the API. Fixtures are never regenerated or
deleted: each milestone release adds one.
"""

import json
import shutil
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripts import make_sample_vault
from scripts.make_sample_vault import Scale, generate

from lore.app import create_app
from lore.config import Settings
from lore.core.maintenance import check_vault
from lore.core.vaults import VaultManager
from tests.conftest import local_client
from tests.entity_api import HEADERS

FIXTURES = Path(__file__).parent / "fixtures" / "vaults"
FIXTURE_DIRS = sorted(path for path in FIXTURES.iterdir() if path.is_dir())


def test_there_is_a_fixture_for_every_release() -> None:
    assert [path.name for path in FIXTURE_DIRS][:7] == [
        "v0.1.0",
        "v0.2.0",
        "v0.3.0",
        "v0.4.0",
        "v0.5.0",
        "v0.6.0",
        "v0.8.0",
    ]


@pytest.fixture(params=FIXTURE_DIRS, ids=[path.name for path in FIXTURE_DIRS])
def fixture(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def _client(data_dir: Path) -> TestClient:
    return local_client(create_app(Settings(data_dir=data_dir)), headers=HEADERS)


@pytest.fixture
def upgraded(fixture: Path, tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """A copy of the fixture vault in a fresh data dir, migrated to head, and its expectations."""
    expected: dict[str, Any] = json.loads((fixture / "expected.json").read_text("utf-8"))
    shutil.copytree(fixture / "vault", tmp_path / "vaults" / expected["folder"])
    with _client(tmp_path) as client:
        vault_id = expected["vault_id"]
        listed = client.get(f"/api/v1/vaults/{vault_id}").json()
        assert listed["schema_status"]["state"] in {"current", "needs_migration"}
        migrated = client.post(f"/api/v1/vaults/{vault_id}/migrate")
        assert migrated.status_code == 200, migrated.json()
        status = client.get(f"/api/v1/vaults/{vault_id}").json()["schema_status"]
        assert status["state"] == "current"
        assert status["revision"] == status["head"]
        # The first open runs the one-time data upgrades (time-point fields, link validity).
        assert client.get(f"/api/v1/vaults/{vault_id}/entities").status_code == 200
        yield client, expected


def _manager(client: TestClient) -> VaultManager:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    return manager


def _all(client: TestClient, url: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    params["limit"] = 500
    while True:
        page = client.get(url, params=params)
        assert page.status_code == 200, page.json()
        items += page.json()["items"]
        params["cursor"] = page.json()["next_cursor"]
        if params["cursor"] is None:
            return items


def test_fixture_upgrades_to_head_and_passes_the_vault_checks(upgraded: Any) -> None:
    client, expected = upgraded
    report = check_vault(_manager(client), expected["vault_id"])
    assert report.problems == ()


def test_fixture_content_survives_the_upgrade(upgraded: Any) -> None:
    client, expected = upgraded
    base = f"/api/v1/vaults/{expected['vault_id']}"
    entities = _all(client, f"{base}/entities")
    # Branch-only entities (v0.8.0 on) are listed in their branch.
    timelines = {e["name"]: e["id"] for e in entities if e["kind"] == "timeline"}
    for branch in expected.get("branches", {}):
        seen = {entity["id"] for entity in entities}
        own = _all(client, f"{base}/entities", timeline=timelines[branch])
        entities += [entity for entity in own if entity["id"] not in seen]
    assert dict(Counter(entity["kind"] for entity in entities)) == expected["entities"]
    assert len(_all(client, f"{base}/trash")) >= expected["trashed_entities"]
    by_name = {entity["name"]: entity["id"] for entity in entities}

    link_ids: set[str] = set()
    for entity in entities:
        assert client.get(f"{base}/entities/{entity['id']}").status_code == 200
        links = client.get(f"{base}/entities/{entity['id']}/links").json()["items"]
        link_ids.update(item["link"]["id"] for item in links)
    assert len(link_ids) == expected["links"]

    for target, sources in expected["backlinks"].items():
        backlinks = client.get(f"{base}/entities/{by_name[target]}/backlinks").json()["items"]
        assert sorted(item["entity"]["name"] for item in backlinks) == sources

    hits = client.get(f"{base}/search", params={"q": expected["search"]["query"]}).json()
    assert [hit["name"] for hit in hits["items"]][:1] == [expected["search"]["name"]]

    link_types = {item["key"] for item in client.get(f"{base}/link-types").json()["items"]}
    assert set(expected["custom_link_types"]) <= link_types


def _check_time(client: TestClient, expected: dict[str, Any]) -> None:
    """The time facts of a sample world (from v0.2.0 on): calendars, the core events' moments and
    the series' materialized occurrences."""
    base = f"/api/v1/vaults/{expected['vault_id']}"
    calendars = {e["name"] for e in _all(client, f"{base}/entities", kind="calendar")}
    assert set(expected.get("calendars", {})) <= calendars
    events = {e["name"]: e["id"] for e in _all(client, f"{base}/entities", kind="event")}
    for name, moments in expected.get("moments", {}).items():
        ext = client.get(f"{base}/entities/{events[name]}").json()["ext"]
        assert [ext["start_t"], ext["end_t"], ext["time_status"]] == [*moments, "ok"], name
    for name, states in expected.get("occurrences", {}).items():
        found = {}
        for event_id in events.values():
            ext = client.get(f"{base}/entities/{event_id}").json()["ext"]
            if ext["series_id"] == events[name]:
                found[ext["occurrence_key"]] = ext["occurrence_state"]
        assert found == states, name


def test_fixture_time_survives_the_upgrade(upgraded: Any) -> None:
    client, expected = upgraded
    _check_time(client, expected)


def test_readers_never_see_the_fixtures_private_content(upgraded: Any) -> None:
    client, expected = upgraded
    base = f"/api/v1/vaults/{expected['vault_id']}"
    names = {entity["name"] for entity in _all(client, f"{base}/entities", as_reader=True)}
    assert names
    assert names.isdisjoint(expected["reader_hidden"])


def test_fixture_lexicons_survive_the_upgrade(upgraded: Any) -> None:
    """Lexicons (v0.5.0 on): in the language's alphabet order, private words for authors only."""
    client, expected = upgraded
    base = f"/api/v1/vaults/{expected['vault_id']}"
    languages = {
        entity["name"]: entity["id"]
        for entity in _all(client, f"{base}/entities", kind=["language"])
    }
    for name, headwords in expected.get("lexicon", {}).items():
        path = f"{base}/m/languages/{languages[name]}/lexicon"
        items = client.get(path, params={"limit": 500}).json()["items"]
        assert [item["headword"] for item in items] == headwords, name
        hidden = set(expected.get("lexicon_hidden", []))
        readers = client.get(path, params={"limit": 500, "as_reader": True}).json()["items"]
        assert [i["headword"] for i in readers] == [h for h in headwords if h not in hidden]


def test_fixture_facts_survive_the_upgrade(upgraded: Any) -> None:
    """Facts (v0.6.0 on): validity moments, existence at moments, private facts for authors
    only, and the marriage valid from the coronation."""
    client, expected = upgraded
    if not expected.get("facts"):
        pytest.skip("this fixture predates facts")
    base = f"/api/v1/vaults/{expected['vault_id']}"
    ids = {entity["name"]: entity["id"] for entity in _all(client, f"{base}/entities")}
    prime = next(
        e for e in _all(client, f"{base}/entities", kind="timeline") if e["name"] == "Prime"
    )
    for name, facts in expected["facts"].items():
        found = client.get(f"{base}/entities/{ids[name]}/facts", params={"timeline": prime["id"]})
        assert found.status_code == 200, found.json()
        items = found.json()["items"]
        assert [[f["field_key"], f["valid_from_t"], f["valid_to_t"]] for f in items] == facts
        assert all(f["time_status"] == "ok" for f in items), name
        readers = client.get(f"{base}/entities/{ids[name]}/facts", params={"as_reader": True})
        if name in expected["facts_hidden"]:
            assert readers.json()["items"] == []
        else:
            assert len(readers.json()["items"]) == len(items)
    for name, states in expected["existence"].items():
        for at, existence in states.items():
            state = client.get(f"{base}/entities/{ids[name]}/state",
                               params={"timeline": prime["id"], "at": at})  # fmt: skip
            assert state.json()["existence"] == existence, (name, at)
    married = client.get(f"{base}/entities/{ids['Ilsa the Tidebound']}/links",
                         params={"type": "characters.spouse_of"}).json()["items"]  # fmt: skip
    died = expected["facts"]["King Aldric"][0][2]
    assert [(i["other"]["name"], i["link"]["valid_from_t"]) for i in married] == [
        ("Lord Tavish", died)
    ]


def test_fixture_advanced_time_survives_the_upgrade(upgraded: Any) -> None:
    """Branches, correspondences and worldlines (v0.8.0 on): the branch point, a mapped moment
    and the time traveler's segments."""
    client, expected = upgraded
    if not expected.get("worldlines"):
        pytest.skip("this fixture predates advanced time")
    base = f"/api/v1/vaults/{expected['vault_id']}"
    ids = {entity["name"]: entity["id"] for entity in _all(client, f"{base}/entities")}
    for name, branch in expected["branches"].items():
        timeline = client.get(f"{base}/entities/{ids[name]}").json()
        assert timeline["ext"]["branch_t"] == branch["branch_t"], name
    for gate in expected["correspondences"].values():
        found = client.get(f"{base}/m/correspondences/map", params={
            "from_dimension": ids[gate["from"]], "to_dimension": ids[gate["to"]],
            "t": gate["t"]}).json()  # fmt: skip
        assert found["result_t"] == gate["mapped"]
    for name, segments in expected["worldlines"].items():
        found = client.get(f"{base}/m/worldlines/entities/{ids[name]}/segments").json()
        assert [[s["start_t"], s["end_t"]] for s in found["segments"]] == segments, name


def test_an_upgraded_fixture_takes_writes_and_undo(upgraded: Any) -> None:
    client, expected = upgraded
    base = f"/api/v1/vaults/{expected['vault_id']}"
    changes = client.get(f"{base}/changes", params={"limit": 1}).json()["items"]
    assert changes, "the fixture has history"
    undone = client.post(f"{base}/changes/{changes[0]['id']}/revert")
    assert undone.status_code == 200, undone.json()

    calendar = next(e for e in _all(client, f"{base}/entities", kind="calendar"))
    dimension = client.get(f"{base}/entities/{calendar['dimension_id']}").json()
    created = client.post(
        f"{base}/entities",
        json={
            "kind": "event",
            "name": "Upgrade Day",
            "dimension_id": dimension["id"],
            "ext": {"start": {"anchor": {"kind": "absolute", "t": "86400"}, "precision": "day"}},
        },
    )
    assert created.status_code == 201, created.json()
    link = client.post(
        f"{base}/links",
        json={
            "link_type": "core.related",
            "source_id": created.json()["entity"]["id"],
            "target_id": dimension["id"],
        },
    )
    assert link.status_code == 201, link.json()
    assert check_vault(_manager(client), expected["vault_id"]).problems == ()


# --- the generator -------------------------------------------------------------------------------


def _content(data_dir: Path, vault_id: str) -> list[tuple[Any, ...]]:
    """Everything the seed decides, without generated ids and timestamps."""
    with _client(data_dir) as client:
        base = f"/api/v1/vaults/{vault_id}"
        entities = _all(client, f"{base}/entities")
        names = {entity["id"]: entity["name"] for entity in entities}
        rows: list[tuple[Any, ...]] = []
        for summary in entities:
            entity = client.get(f"{base}/entities/{summary['id']}").json()
            links = client.get(f"{base}/entities/{summary['id']}/links").json()["items"]
            rows.append((
                entity["kind"], entity["name"], entity["summary"], entity["visibility"],
                names.get(entity["parent_id"]), names.get(entity["dimension_id"]),
                sorted(tag["name"] for tag in entity["tags"]),
                [alias["alias"] for alias in entity["aliases"]],
                json.dumps(entity["body"], sort_keys=True).count("entityLink"),
                [(entity["ext"] or {}).get(key) for key in (
                    "start_t", "end_t", "time_status", "occurrence_key", "occurrence_state")],
                ((entity["ext"] or {}).get("recurrence") or {}).get("kind"),
                sorted((item["link"]["link_type"], item["direction"], item["other"]["name"])
                       for item in links),
            ))  # fmt: skip
        return sorted(rows, key=repr)


def test_the_generator_is_deterministic_for_a_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(make_sample_vault.SIZES, "small", Scale(events=120, links=150))
    monkeypatch.setattr(make_sample_vault, "ENTITIES_PER_TRANSACTION", 50)
    monkeypatch.setattr(make_sample_vault, "LINKS_PER_TRANSACTION", 100)
    first = generate(tmp_path / "a", "small", seed=7)
    second = generate(tmp_path / "b", "small", seed=7)
    other = generate(tmp_path / "c", "small", seed=8)

    assert first.entities == {
        "calendar": 11,
        "character": 8,
        "dimension": 4,
        "event": 50 + 120,
        "group": 7,
        "language": 5,
        "location": 9,
        "misc": 5,
        "species": 4,
        "timeline": 5,
        "writing_system": 2,
    }
    assert first.links == 65 + 150
    assert (first.entities, first.links) == (second.entities, second.links)
    assert _content(tmp_path / "a", first.vault_id) == _content(tmp_path / "b", second.vault_id)
    assert _content(tmp_path / "a", first.vault_id) != _content(tmp_path / "c", other.vault_id)
    with _client(tmp_path / "a") as client:
        assert check_vault(_manager(client), first.vault_id).problems == ()


def test_the_core_has_its_time_facts(tmp_path: Path) -> None:
    """Every preset and the custom calendar, events at every precision and with every end kind,
    series of every rule kind with materialized occurrences, all resolved (``testing.md`` §2)."""
    world = generate(tmp_path, "tiny")
    assert sorted(world.calendars.values()) == sorted([
        "alternating-years", "custom", "gregorian", "julian", "julian-gregorian",
        "lunisolar-metonic", "mayan", "shire-reckoning", "simple-360", "simple-360",
        "simple-360",
    ])  # fmt: skip
    assert world.occurrences == {
        "Rite of Tides": {"2": "referenced", "4": "modified", "6": "cancelled"}
    }
    assert world.moments["The Endless Vigil"][1] == str(10**110)  # end_of_time
    expected = {**world.__dict__}
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{world.vault_id}"
        _check_time(client, expected)
        events = _all(client, f"{base}/entities", kind="event")
        exts = [client.get(f"{base}/entities/{e['id']}").json()["ext"] for e in events]
        anchors = {x["start"]["anchor"]["kind"] for x in exts}
        precisions = {x["start"]["precision"] for x in exts}
        ends = {x["end"]["kind"] for x in exts}
        rules = {x["recurrence"]["kind"] for x in exts if x["recurrence"]}
        assert anchors == {"absolute", "calendar", "relative"}
        assert {"base", "second", "minute", "hour", "day", "month", "year", "kin"} <= precisions
        assert ends == {"time_point", "duration", "instant", "end_of_time", "unknown"}
        assert rules == {"calendar", "interval"}
        assert any(x["start"]["approximate"] for x in exts)
        assert check_vault(_manager(client), world.vault_id).problems == ()


def test_the_core_has_a_branch(tmp_path: Path) -> None:
    """ "What if Aurel survived" (M9): it inherits what started before the assassination, not
    the assassination or what follows it, and its branch-only entities show only in it."""
    world = generate(tmp_path, "tiny")
    branch = world.branches["What if Aurel survived"]
    assert branch["parent"] == "Prime"
    assert "Recovery of Aurel" in branch["events"]
    assert "Founding of Varn" in branch["events"]
    assert {"Assassination of Aurel", "War of the Succession"}.isdisjoint(branch["events"])
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{world.vault_id}"
        names = {e["name"] for e in _all(client, f"{base}/entities", kind="group")}
        assert "Council of the Survivor" not in names
        timelines = _all(client, f"{base}/entities", kind="timeline")
        survived = next(t for t in timelines if t["name"] == "What if Aurel survived")
        in_branch = {e["name"] for e in _all(client, f"{base}/entities", kind="group",
                                             timeline=survived["id"])}  # fmt: skip
        assert "Council of the Survivor" in in_branch
        assert check_vault(_manager(client), world.vault_id).problems == ()


def test_the_core_has_a_correspondence(tmp_path: Path) -> None:
    """The Drowned Gate (M9): a day in Aetheria is a year in the Dreaming, from the Sundering."""
    world = generate(tmp_path, "tiny")
    gate = world.correspondences["The Drowned Gate"]
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{world.vault_id}"
        dimensions = {
            e["name"]: e["id"] for e in _all(client, f"{base}/entities", kind="dimension")
        }
        found = client.get(f"{base}/m/correspondences/map", params={
            "from_dimension": dimensions[gate["from"]], "to_dimension": dimensions[gate["to"]],
            "t": gate["t"]}).json()  # fmt: skip
        assert found["result_t"] == gate["mapped"]
        assert check_vault(_manager(client), world.vault_id).problems == ()


def test_the_core_has_a_time_traveler(tmp_path: Path) -> None:
    """Wren (M9) leaves at the Sundering and warns of it before it happens: a warning caused by the
    Sundering, before it, that the worldline explains (no effect-before-cause finding)."""
    world = generate(tmp_path, "tiny")
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{world.vault_id}"
        wren = next(e for e in _all(client, f"{base}/entities", kind="character")
                    if e["name"] == "Wren")  # fmt: skip
        worldline = client.get(f"{base}/m/worldlines/entities/{wren['id']}/segments").json()
        assert len(worldline["segments"]) == 2
        items = client.get(f"{base}/m/worldlines/entities/{wren['id']}/personal-timeline")
        names = [i["name"] for i in items.json()["items"] if i["kind"] == "participation"]
        assert names[-2:] == ["The Sundering", "Wren's Warning"]
        found = client.get(f"{base}/consistency/findings",
                           params={"rule": "core.event.effect_before_cause"}).json()  # fmt: skip
        assert "Wren's Warning" not in str(found)


def test_a_fixture_is_a_bare_vault_folder_with_its_expectations(tmp_path: Path) -> None:
    target = tmp_path / "v9.9.9"
    world = make_sample_vault.write_fixture(target)
    assert sorted(path.name for path in (target / "vault").iterdir()) == ["lore.db", "vault.json"]
    expected = json.loads((target / "expected.json").read_text("utf-8"))
    assert expected["vault_id"] == world.vault_id
    assert expected["size"] == "tiny"
    with pytest.raises(FileExistsError):
        make_sample_vault.write_fixture(target)


def test_the_script_entry_point(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_sample_vault.main(["--size", "tiny", "--out", str(tmp_path)])
    assert "110 entities, 65 links" in capsys.readouterr().out
    assert len(list((tmp_path / "vaults").iterdir())) == 1


def test_v0_1_0_timelines_become_a_prime_and_branches(tmp_path: Path) -> None:
    """Migration ``39828513f6da`` (decided 2026-10-05): the earliest timeline is the prime, the
    others branch from it at absolute 0; every dimension got a time spec."""
    expected = json.loads((FIXTURES / "v0.1.0" / "expected.json").read_text("utf-8"))
    shutil.copytree(FIXTURES / "v0.1.0" / "vault", tmp_path / "vaults" / expected["folder"])
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{expected['vault_id']}"
        assert client.post(f"{base}/migrate").status_code == 200
        dimensions = {e["name"]: e for e in _all(client, f"{base}/entities", kind="dimension")}
        world = client.get(f"{base}/entities/{dimensions['Aetheria']['id']}").json()
        assert (world["ext"]["base_unit"]["singular"], world["ext"]["duration"]) == (
            "second", str(10**100)
        )  # fmt: skip
        tree = client.get(f"{base}/dimensions/{world['id']}/timelines").json()["items"]
        assert [(n["name"], n["is_prime"]) for n in tree] == [("Prime", True)]
        branches = tree[0]["children"]
        assert [(n["name"], n["branch_t"], n["branch_point"]["anchor"]) for n in branches] == [
            ("The Unbroken Crown", "0", {"kind": "absolute", "t": "0"})
        ]
        prime = client.get(f"{base}/entities/{tree[0]['id']}").json()
        assert prime["ext"]["is_prime"] is True


def test_v0_1_0_events_get_a_home_row_at_inception(tmp_path: Path) -> None:
    """Migration ``0f7812a431dd`` (decided 2026-10-06): every event starts at absolute 0 with an
    instant end on its dimension's prime timeline, and shows up in the event tree."""
    expected = json.loads((FIXTURES / "v0.1.0" / "expected.json").read_text("utf-8"))
    shutil.copytree(FIXTURES / "v0.1.0" / "vault", tmp_path / "vaults" / expected["folder"])
    with _client(tmp_path) as client:
        base = f"/api/v1/vaults/{expected['vault_id']}"
        assert client.post(f"{base}/migrate").status_code == 200
        events = _all(client, f"{base}/entities", kind="event", include_trashed="true")
        assert len(events) == 10
        primes: dict[str, str] = {}
        for summary in events:
            event = client.get(f"{base}/entities/{summary['id']}").json()
            ext = event["ext"]
            assert (ext["start"]["anchor"], ext["end"], ext["start_t"], ext["end_t"]) == (
                {"kind": "absolute", "t": "0"}, {"kind": "instant"}, "0", "0"
            )  # fmt: skip
            assert (ext["time_status"], ext["importance"], ext["category"]) == ("ok", 3, None)
            if event["dimension_id"] not in primes:
                world = client.get(f"{base}/entities/{event['dimension_id']}").json()
                primes[event["dimension_id"]] = world["ext"]["prime_timeline_id"]
            assert ext["timeline_id"] == primes[event["dimension_id"]]
        world = next(e for e in _all(client, f"{base}/entities", kind="dimension")
                     if e["name"] == "Aetheria")  # fmt: skip
        prime = client.get(f"{base}/entities/{world['id']}").json()["ext"]["prime_timeline_id"]
        roots = client.get(f"{base}/timelines/{prime}/event-tree").json()["items"]
        assert roots
        assert all(item["start_t"] == "0" for item in roots)
