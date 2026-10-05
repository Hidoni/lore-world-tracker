"""Vault maintenance (``persistence-and-migrations.md`` §2, §3.4): ``lore vault check`` (SQLite
integrity, foreign keys, derived data), ``reindex`` (rebuilds derived data), ``optimize`` and
the daily ``PRAGMA optimize``."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.core.maintenance import check_vault, reindex_vault
from lore.core.maintenance.checks import DERIVED_DATA
from lore.core.vaults import VaultManager
from lore.modules import ALL_MODULES
from tests.entity_api import Api, make_client
from tests.test_richtext import mention, text


def doc(*content: Any) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": list(content)}]}


def link(label: str, entity_id: str) -> dict[str, Any]:
    return text(label, mention(entity_id))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path) as test_client:
        yield test_client


@pytest.fixture
def world(client: TestClient) -> tuple[Api, dict[str, Any], dict[str, Any]]:
    """A vault with two entities, one mentioning the other."""
    api = Api(client)
    anvil = api.make("misc", "Anvil", body=doc(text("heavy")))
    forge = api.make("misc", "Forge", body=doc(text("holds the "), link("anvil", anvil["id"])))
    return api, anvil, forge


def manager_of(client: TestClient) -> VaultManager:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    return manager


def codes(client: TestClient, vault_id: str) -> list[str]:
    manager = manager_of(client)
    report = check_vault(manager, vault_id)
    assert report.checks == ("schema", "integrity", "foreign_keys", "search", "mentions")
    return sorted(problem.code for problem in report.problems)


def raw(client: TestClient, vault_id: str) -> sqlite3.Connection:
    """A raw connection to the vault's database (bypassing every service), autocommitting."""
    connection = sqlite3.connect(manager_of(client).get(vault_id).database_path)
    connection.isolation_level = None
    return connection


def test_a_healthy_vault_has_no_problems(client: TestClient, world: Any) -> None:
    api, _anvil, _forge = world
    assert codes(client, api.vault) == []


def test_corrupted_derived_data_is_detected_and_fixed_by_reindex(
    client: TestClient, world: Any
) -> None:
    api, anvil, forge = world
    misc = api.make("misc", "Bellows")
    with closing(raw(client, api.vault)) as connection:
        connection.execute("DELETE FROM search_docs WHERE doc_id = ?", (anvil["id"],))
        connection.execute(
            "UPDATE search_docs SET name = 'Smithy' WHERE doc_id = ?", (forge["id"],)
        )
        connection.execute(
            "INSERT INTO search_docs (doc_type, doc_id, entity_id, kind, visibility)"
            " VALUES ('entity', 'ghost', ?, 'misc', 'public')",
            (misc["id"],),
        )
        connection.execute(
            "INSERT INTO search_docs (doc_type, doc_id, entity_id, kind, visibility)"
            " VALUES ('gone.thing', 'x', ?, 'gone.thing', 'public')",
            (misc["id"],),
        )
        connection.execute("DELETE FROM mentions WHERE source_entity_id = ?", (forge["id"],))
        connection.execute(
            "INSERT INTO mentions (source_entity_id, target_entity_id, count_public)"
            " VALUES (?, ?, 1)",
            (misc["id"], anvil["id"]),
        )
        connection.execute("DELETE FROM vault_meta WHERE key = 'search_index'")
    assert codes(client, api.vault) == [
        "mentions_stale",
        "mentions_stale",
        "search_document_missing",
        "search_document_orphaned",
        "search_document_orphaned",
        "search_document_stale",
        "search_index_outdated",
    ]
    manager = manager_of(client)
    assert manager.module_registry is not None
    counts = reindex_vault(manager.open(api.vault), manager.module_registry)
    assert counts == {"search": 3, "mentions": 3}
    assert codes(client, api.vault) == []
    hits = api.client.get(f"{api.base}/search", params={"q": "heavy"}).json()["items"]
    assert [hit["name"] for hit in hits] == ["Anvil"]
    backlinks = api.client.get(f"{api.base}/entities/{anvil['id']}/backlinks").json()
    assert [item["entity"]["name"] for item in backlinks["items"]] == ["Forge"]


def test_a_corrupt_full_text_index_is_detected_and_fixed_by_reindex(
    client: TestClient, world: Any
) -> None:
    api, _anvil, _forge = world
    with closing(raw(client, api.vault)) as connection:
        connection.execute("INSERT INTO search_trigram(search_trigram) VALUES ('delete-all')")
    assert codes(client, api.vault) == ["search_fts_corrupt"]
    manager = manager_of(client)
    assert manager.module_registry is not None
    reindex_vault(manager.open(api.vault), manager.module_registry)
    assert codes(client, api.vault) == []


def test_foreign_key_violations_are_reported(client: TestClient, world: Any) -> None:
    api, anvil, _forge = world
    with closing(raw(client, api.vault)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE mentions SET target_entity_id = 'missing' WHERE target_entity_id = ?",
            (anvil["id"],),
        )
    assert "foreign_key_violation" in codes(client, api.vault)


def test_the_check_leaves_the_vault_untouched(client: TestClient, world: Any) -> None:
    api, _anvil, _forge = world
    changes = api.client.get(f"{api.base}/changes").json()["items"]
    with closing(raw(client, api.vault)) as connection:
        connection.execute("DELETE FROM mentions")
    assert codes(client, api.vault) == ["mentions_stale"]
    assert codes(client, api.vault) == ["mentions_stale"]  # nothing was repaired
    assert api.client.get(f"{api.base}/changes").json()["items"] == changes


def test_the_check_runs_on_a_copy_that_is_deleted(
    client: TestClient, world: Any, tmp_path: Path
) -> None:
    api, _anvil, _forge = world
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with closing(raw(client, api.vault)) as connection:
        connection.execute("DELETE FROM mentions")
    report = check_vault(manager_of(client), api.vault, scratch_dir=scratch)
    assert [problem.code for problem in report.problems] == ["mentions_stale"]
    assert list(scratch.iterdir()) == []


def test_unreadable_and_foreign_schemas_are_reported_without_checking(
    client: TestClient, world: Any
) -> None:
    api, _anvil, _forge = world
    manager = manager_of(client)
    with closing(raw(client, api.vault)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'f00d'")
    report = check_vault(manager, api.vault)
    assert report.checks == ("schema",)
    assert [p.code for p in report.problems] == ["vault_newer_than_app"]
    with closing(raw(client, api.vault)) as connection:
        connection.execute("DELETE FROM alembic_version")
    assert [p.code for p in check_vault(manager, api.vault).problems] == ["vault_needs_migration"]
    manager.close()
    database = manager.get(api.vault).database_path
    for leftover in database.parent.glob("lore.db-*"):
        leftover.unlink()
    database.write_bytes(b"not a database" * 100)
    report = check_vault(manager, api.vault)
    assert report.checks == ("schema",)
    assert [p.code for p in report.problems] == ["database_unreadable"]


def test_derived_data_checks_are_registered_in_order() -> None:
    assert [check.id for check in DERIVED_DATA] == ["search", "mentions"]


# --- the daily PRAGMA optimize ----------------------------------------------------------------


def test_open_vaults_are_optimized_daily(client: TestClient, world: Any) -> None:
    api, _anvil, _forge = world
    manager = manager_of(client)
    manager.open(api.vault)
    now = datetime.now(UTC)
    assert manager.run_scheduled_optimize(now) == []  # just opened
    assert manager.run_scheduled_optimize(now + timedelta(hours=23)) == []
    assert manager.run_scheduled_optimize(now + timedelta(days=1, minutes=1)) == [api.vault]
    assert manager.run_scheduled_optimize(now + timedelta(days=1, minutes=2)) == []
    assert manager.run_scheduled_optimize(now + timedelta(days=2, minutes=2)) == [api.vault]


def test_the_daily_optimize_skips_read_only_servers_and_logs_failures(
    tmp_path: Path, client: TestClient, world: Any, caplog: pytest.LogCaptureFixture
) -> None:
    api, _anvil, _forge = world
    assert VaultManager(tmp_path, read_only=True).run_scheduled_optimize() == []
    manager = manager_of(client)
    opened = manager.open(api.vault)
    opened.engine.dispose()
    opened.info.database_path.chmod(0o000)
    try:
        later = datetime.now(UTC) + timedelta(days=2)
        assert manager.run_scheduled_optimize(later) == []
    finally:
        opened.info.database_path.chmod(0o644)
    assert "PRAGMA optimize failed" in caplog.text


def test_the_scheduler_runs_backups_and_the_daily_optimize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = manager_of(client)
    calls: list[str] = []
    monkeypatch.setattr(manager, "run_scheduled_backups", lambda: calls.append("backups"))
    monkeypatch.setattr(manager, "run_scheduled_optimize", lambda: calls.append("optimize"))
    client.app.state.scheduler.run_once()  # type: ignore[attr-defined]
    assert calls == ["backups", "optimize"]


# --- the CLI ----------------------------------------------------------------------------------


@pytest.fixture
def cli_vault(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, Path]:
    """A vault (with the real modules) holding a dimension and a mention; its id and database."""
    with make_client(tmp_path, modules=tuple(ALL_MODULES)) as test_client:
        api = Api(test_client)
        world = api.make("dimension", "Aetheria")
        api.make("dimension", "Umbra", body=doc(link("Aetheria", world["id"])))
        database = manager_of(test_client).get(api.vault).database_path
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    return api.vault, database


def test_cli_check(cli_vault: tuple[str, Path]) -> None:
    vault, database = cli_vault
    runner = CliRunner()
    result = runner.invoke(cli.app, ["vault", "check", vault])
    assert result.exit_code == 0, result.output
    assert result.output == "ok (schema, integrity, foreign_keys, search, mentions)\n"
    report = runner.invoke(cli.app, ["vault", "check", vault, "--json"])
    assert report.exit_code == 0, report.output
    assert json.loads(report.output) == {
        "vault": vault,
        "ok": True,
        "checks": ["schema", "integrity", "foreign_keys", "search", "mentions"],
        "problems": [],
    }

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DELETE FROM mentions")
    broken = runner.invoke(cli.app, ["vault", "check", vault])
    assert broken.exit_code == 1
    assert broken.stdout.startswith("mentions: mentions_stale: the mentions of entity ")
    assert "1 problem(s) found" in broken.stderr
    broken_json = runner.invoke(cli.app, ["vault", "check", vault, "--json"])
    assert broken_json.exit_code == 1
    document = json.loads(broken_json.stdout)
    assert document["ok"] is False
    assert [(p["check"], p["code"]) for p in document["problems"]] == [
        ("mentions", "mentions_stale")
    ]

    fixed = runner.invoke(cli.app, ["vault", "reindex", vault])
    assert fixed.exit_code == 0, fixed.output
    assert fixed.output == "search: rebuilt 2 documents\nmentions: rebuilt 2 entities\n"
    assert runner.invoke(cli.app, ["vault", "check", vault]).exit_code == 0
    assert runner.invoke(cli.app, ["vault", "check", "nope"]).exit_code == 1


def _fingerprint(database: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(database.parent.iterdir())
        if path.is_file()
    }


def test_cli_check_never_changes_the_vault(cli_vault: tuple[str, Path]) -> None:
    """Opening the vault would rebuild a missing index (and migrate an old schema): the check
    must report the problem instead, and leave every file of the vault as it was."""
    vault, database = cli_vault
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DELETE FROM vault_meta WHERE key = 'search_index'")
        connection.execute("DELETE FROM search_docs")
    before = _fingerprint(database)
    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(cli.app, ["vault", "check", vault, "--json"])
        assert result.exit_code == 1
        found = {p["code"] for p in json.loads(result.stdout)["problems"]}
        assert found == {"search_index_outdated", "search_document_missing"}
    assert _fingerprint(database) == before


def test_cli_check_works_while_a_server_has_the_vault_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with make_client(tmp_path, modules=tuple(ALL_MODULES)) as test_client:
        api = Api(test_client)
        api.make("dimension", "Aetheria")
        monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
        result = CliRunner().invoke(cli.app, ["vault", "check", api.vault])
        assert result.exit_code == 0, result.output
        api.make("dimension", "Umbra")  # the server still writes


def test_cli_optimize(cli_vault: tuple[str, Path]) -> None:
    vault, _database = cli_vault
    runner = CliRunner()
    result = runner.invoke(cli.app, ["vault", "optimize", vault])
    assert result.exit_code == 0, result.output
    assert result.output == "optimized\n"
    vacuumed = runner.invoke(cli.app, ["vault", "optimize", vault, "--vacuum"])
    assert vacuumed.exit_code == 0, vacuumed.output
    assert vacuumed.output.startswith("optimized and vacuumed (")
    assert runner.invoke(cli.app, ["vault", "check", vault]).exit_code == 0
    assert runner.invoke(cli.app, ["vault", "optimize", "nope"]).exit_code == 1
