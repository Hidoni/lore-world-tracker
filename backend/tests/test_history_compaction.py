"""History compaction (``data-model.md`` §7, Retention; ``lore vault compact-history``)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.core.db.types import utc_now
from lore.core.history import recorder
from lore.core.history.compaction import CompactionReport, compact_history
from lore.core.maintenance import compact_vault_history
from lore.core.vaults import VaultManager
from tests.conftest import local_client
from tests.entity_api import HEADERS, LinkApi, new_app, problem
from tests.history_utils import changes_of, changesets, snapshot

type Net = dict[tuple[str, str], tuple[Any, Any]]


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


def compact(app: FastAPI, vault_id: str, cutoff: datetime) -> CompactionReport:
    manager: VaultManager = app.state.vaults
    with manager.open(vault_id).write_sessions.begin() as session:
        return compact_history(session, cutoff)


def net_history(app: FastAPI, vault_id: str) -> Net:
    """Each row's first ``before`` and last ``after`` over the whole history (rows that ended
    where they started left out): what compaction must keep."""
    net: Net = {}
    for changeset in changesets(app, vault_id):
        for change in changes_of(app, vault_id, changeset["id"]):
            key = (change["table_name"], change["row_id"])
            first = net[key][0] if key in net else change["before"]
            net[key] = (first, change["after"])
    return {key: value for key, value in net.items() if value[0] != value[1]}


def owners(app: FastAPI, vault_id: str, changeset_id: str) -> set[str]:
    manager: VaultManager = app.state.vaults
    with manager.open(vault_id).engine.connect() as connection:
        return {
            entity_id
            for (entity_id,) in connection.exec_driver_sql(
                "SELECT entity_id FROM change_entities JOIN changes ON changes.id = change_id "
                "WHERE changeset_id = ?",
                (changeset_id,),
            )
        }


def feed(api: LinkApi, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/changes", params=params)
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def history(api: LinkApi, entity_id: str) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/entities/{entity_id}/history")
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def revert(api: LinkApi, changeset_id: str) -> Any:
    return api.client.post(f"{api.base}/changes/{changeset_id}/revert")


def test_old_history_becomes_one_snapshot_per_entity(api: LinkApi, app: FastAPI) -> None:
    ana = api.make("misc", "Ana", tags=["Hero"])
    ana = api.patch(ana, name="Anna").json()["entity"]
    ana = api.patch(ana, summary="brave").json()["entity"]
    bo = api.make("misc", "Bo")
    api.made_link("core.related", ana, bo)
    cutoff = utc_now()
    later = api.patch(api.get(ana["id"]).json(), summary="braver").json()["entity"]
    kept = changesets(app, api.vault)[-1]
    expected, rows = net_history(app, api.vault), snapshot(app, api.vault)

    report = compact(app, api.vault, cutoff)

    assert (report.changesets, report.snapshots) == (5, 3)  # Ana, Bo, the tag (vault-wide)
    assert net_history(app, api.vault) == expected
    assert snapshot(app, api.vault) == rows  # world data is untouched
    sets = changesets(app, api.vault)
    assert sets[-1] == kept  # the kept history stays as it was, and sorts last
    snapshots = sets[:-1]
    assert {s["origin"] for s in snapshots} == {"compaction"}
    day = cutoff.date().isoformat()
    assert sorted(s["summary"] for s in snapshots) == [
        f"Changes of “Anna” before {day} (compacted)",
        f"Changes of “Bo” before {day} (compacted)",
        f"Vault-wide changes before {day} (compacted)",
    ]
    of_ana = next(s for s in snapshots if "Anna" in s["summary"])
    # Ana's snapshot holds her row as created (an insert), her tag and the link to Bo
    assert {(c["table_name"], c["op"]) for c in changes_of(app, api.vault, of_ana["id"])} == {
        ("entities", "insert"),
        ("entity_tags", "insert"),
        ("links", "insert"),
    }
    assert owners(app, api.vault, of_ana["id"]) == {ana["id"], bo["id"]}
    # the link keeps both owners: Bo's history shows Ana's snapshot too (newest first: it
    # ends with the link)
    assert [h["summary"] for h in history(api, bo["id"])] == [
        f"Changes of “Anna” before {day} (compacted)",
        f"Changes of “Bo” before {day} (compacted)",
    ]
    assert [h["origin"] for h in feed(api, origin="compaction")] == ["compaction"] * 3

    problem(revert(api, of_ana["id"]), 409, "conflict")  # snapshots can't be undone
    assert revert(api, kept["id"]).status_code == 200  # the kept history can
    assert api.get(later["id"]).json()["summary"] == "brave"


def test_rows_that_end_where_they_started_are_dropped(api: LinkApi, app: FastAPI) -> None:
    gone = api.make("misc", "Gone", tags=["Fleeting"])
    assert api.delete(gone["id"]).status_code == 200  # to the trash, then purged
    assert api.delete(gone["id"], purge=True).status_code == 200
    cutoff = utc_now()

    report = compact(app, api.vault, cutoff)

    # the tag row stays: tags outlive their entities
    assert (report.changesets, report.snapshots) == (3, 1)
    [only] = changesets(app, api.vault)
    assert {c["table_name"] for c in changes_of(app, api.vault, only["id"])} == {"tags"}


def test_nothing_old_compacts_nothing(api: LinkApi, app: FastAPI) -> None:
    cutoff = utc_now()
    api.make("misc", "Fresh")
    before = changesets(app, api.vault)
    assert compact(app, api.vault, cutoff) == CompactionReport(0, 0, 0, 0)
    assert changesets(app, api.vault) == before


def test_a_changeset_saved_since_the_cutoff_ends_the_compacted_prefix(
    api: LinkApi, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    ana = api.make("misc", "Ana")
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(minutes=2))
    ana = api.patch(ana, summary="one").json()["entity"]
    cutoff = utc_now()
    api.patch(ana, summary="two")  # merges into the edit before the cutoff
    created, merged = changesets(app, api.vault)

    report = compact(app, api.vault, cutoff)

    assert (report.changesets, report.snapshots) == (1, 1)
    snapshot_set, kept = changesets(app, api.vault)
    assert kept == merged
    assert snapshot_set["id"] < kept["id"]
    assert snapshot_set["created_at"] == created["created_at"]


def test_undos_of_compacted_changesets_lose_their_reference(api: LinkApi, app: FastAPI) -> None:
    ana = api.make("misc", "Ana")
    api.patch(ana, summary="edited")
    edit = changesets(app, api.vault)[-1]
    cutoff = utc_now()
    undo = revert(api, edit["id"]).json()["changeset"]
    assert undo["reverts_changeset_id"] == edit["id"]
    expected = net_history(app, api.vault)

    compact(app, api.vault, cutoff)

    assert net_history(app, api.vault) == expected
    kept = changesets(app, api.vault)[-1]
    assert (kept["id"], kept["origin"], kept["reverts_changeset_id"]) == (undo["id"], "undo", None)
    assert revert(api, undo["id"]).status_code == 200  # redo still works
    assert api.get(ana["id"]).json()["summary"] == "edited"


def test_compacting_again_keeps_the_history(api: LinkApi, app: FastAPI) -> None:
    ana = api.make("misc", "Ana")
    api.patch(ana, summary="one")
    compact(app, api.vault, utc_now())
    ana = api.get(ana["id"]).json()
    api.patch(ana, summary="two")
    bo = api.make("misc", "Bo")
    cutoff = utc_now()
    api.patch(bo, summary="later")
    expected = net_history(app, api.vault)

    report = compact(app, api.vault, cutoff)

    assert (report.changesets, report.snapshots) == (3, 2)
    assert net_history(app, api.vault) == expected
    [ana_set] = [s for s in changesets(app, api.vault) if "Ana" in s["summary"]]
    [row] = changes_of(app, api.vault, ana_set["id"])
    assert (row["op"], row["after"]["summary"]) == ("insert", "two")


# --- the maintenance call and the CLI ---------------------------------------------------------


def age(database: Path, days: int) -> None:
    """Move every changeset ``days`` into the past."""
    with closing(sqlite3.connect(database)) as connection, connection:
        for changeset_id, created, updated in connection.execute(
            "SELECT id, created_at, updated_at FROM changesets"
        ).fetchall():
            connection.execute(
                "UPDATE changesets SET created_at = ?, updated_at = ? WHERE id = ?",
                (
                    (datetime.fromisoformat(created) - timedelta(days=days)).isoformat(
                        timespec="microseconds"
                    ),
                    (datetime.fromisoformat(updated) - timedelta(days=days)).isoformat(
                        timespec="microseconds"
                    ),
                    changeset_id,
                ),
            )


def test_a_dry_run_changes_nothing(api: LinkApi, app: FastAPI) -> None:
    api.make("misc", "Ana")
    manager: VaultManager = app.state.vaults
    opened = manager.open(api.vault)
    age(opened.info.database_path, 10)
    before = changesets(app, api.vault)
    report = compact_vault_history(opened, timedelta(days=5), dry_run=True)
    assert (report.changesets, report.snapshots) == (1, 1)
    assert changesets(app, api.vault) == before
    assert compact_vault_history(opened, timedelta(days=30)) == CompactionReport(0, 0, 0, 0)
    with pytest.raises(ValueError, match="positive"):
        compact_vault_history(opened, timedelta(0))


def test_cli_compact_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, app: FastAPI, api: LinkApi
) -> None:
    ana = api.make("misc", "Ana")
    api.patch(ana, summary="edited")
    manager: VaultManager = app.state.vaults
    database = manager.get(api.vault).database_path
    age(database, 10)
    manager.close()
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    runner = CliRunner()

    dry = runner.invoke(
        cli.app, ["vault", "compact-history", api.vault, "--older-than", "5", "--dry-run"]
    )
    assert dry.exit_code == 0, dry.output
    assert dry.output == (
        "would compact 2 changesets (2 changes) older than 5 days into 1 snapshots (1 changes)\n"
    )
    done = runner.invoke(cli.app, ["vault", "compact-history", api.vault, "--older-than", "5"])
    assert done.exit_code == 0, done.output
    assert done.output.startswith("compacted 2 changesets")
    with closing(sqlite3.connect(database)) as connection:
        [(origin, summary)] = connection.execute("SELECT origin, summary FROM changesets")
        [(after,)] = connection.execute("SELECT after FROM changes")
    assert origin == "compaction"
    assert summary.startswith("Changes of “Ana” before ")
    assert json.loads(after)["summary"] == "edited"
    assert runner.invoke(cli.app, ["vault", "compact-history", api.vault]).exit_code != 0
    zero = ["vault", "compact-history", api.vault, "--older-than", "0"]
    assert runner.invoke(cli.app, zero).exit_code != 0
