import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.app import create_app_from_env
from lore.core.db.migrate import Migrator
from tests.migration_harness import FIRST_REVISION, migration_source, script_directory

runner = CliRunner()


def test_openapi_prints_document() -> None:
    result = runner.invoke(cli.app, ["openapi"])
    assert result.exit_code == 0
    document = json.loads(result.output)
    assert document["openapi"].startswith("3.1")
    operation_ids = {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
    }
    assert {"system_health", "system_meta"} <= operation_ids


def test_openapi_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    result = runner.invoke(cli.app, ["openapi", "--out", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["info"]["title"] == "Lore World Tracker"


def _capture_uvicorn(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append((app, kw)))
    monkeypatch.setattr(cli, "configure_logging", lambda *args: calls.append(("logging", {})))
    return calls


def test_serve_uses_settings_and_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_uvicorn(monkeypatch)
    monkeypatch.setenv("LORE_PORT", "9001")
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0
    [(marker, _), (app, options)] = calls
    assert marker == "logging"
    assert not isinstance(app, str)
    assert options == {
        "host": "127.0.0.1",
        "port": 9001,
        "log_level": "info",
        "log_config": None,
        "access_log": False,
        "workers": 1,
    }


def test_serve_reload_uses_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_uvicorn(monkeypatch)
    result = runner.invoke(cli.app, ["serve", "--reload", "--host", "0.0.0.0", "--port", "1234"])
    assert result.exit_code == 0
    [(marker, _), (app, options)] = calls
    assert marker == "logging"
    assert app == "lore.app:create_app_from_env"
    assert options["factory"] is True
    assert options["reload"] is True
    assert options["workers"] == 1
    assert (options["host"], options["port"]) == ("0.0.0.0", 1234)


def test_app_factory_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.app.configure_logging", lambda *args: None)
    monkeypatch.setenv("LORE_READ_ONLY", "true")
    assert create_app_from_env().state.settings.read_only is True


def test_vault_create_and_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    created = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    assert created.exit_code == 0, created.output
    vault_id, folder, name = created.output.split()
    assert name == "Aetheria"
    assert (tmp_path / "vaults" / folder / "vault.json").is_file()
    (tmp_path / "vaults" / "broken").mkdir()
    listed = runner.invoke(cli.app, ["vault", "list"])
    assert listed.exit_code == 0
    assert listed.stdout == f"{vault_id}  {folder}  Aetheria\n"
    assert "problem: broken: manifest_invalid" in listed.stderr


def test_vault_create_reports_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    result = runner.invoke(cli.app, ["vault", "create", "   "])
    assert result.exit_code == 1
    assert result.stderr.startswith("error:")
    monkeypatch.setenv("LORE_READ_ONLY", "true")
    result = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    assert result.exit_code == 1
    assert "read-only" in result.stderr


def test_vault_status_and_migrate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path / "data"))
    created = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    vault_id, folder, _ = created.output.split()
    head = Migrator().head()
    for reference in (vault_id, folder):
        status = runner.invoke(cli.app, ["vault", "status", reference])
        assert status.exit_code == 0, status.output
        assert f"folder:    {folder}" in status.stdout
        assert "schema:    current" in status.stdout
        assert f"revision:  {head}" in status.stdout
    migrated = runner.invoke(cli.app, ["vault", "migrate", folder])
    assert migrated.exit_code == 0
    assert migrated.stdout == f"already at {head}\n"
    missing = runner.invoke(cli.app, ["vault", "status", "nope"])
    assert missing.exit_code == 1
    assert "No vault with id or folder 'nope'" in missing.stderr


def test_vault_migrate_runs_pending_migrations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path / "data"))
    created = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    folder = created.output.split()[1]
    newer = script_directory(
        tmp_path / "newer", {"n.py": migration_source("next00000001", FIRST_REVISION, "pass")}
    )
    monkeypatch.setattr("lore.core.vaults.manager.Migrator", lambda: Migrator(newer))
    status = runner.invoke(cli.app, ["vault", "status", folder])
    assert "schema:    needs_migration" in status.stdout
    migrated = runner.invoke(cli.app, ["vault", "migrate", folder, "--to", "next00000001"])
    assert migrated.exit_code == 0, migrated.output
    assert migrated.stdout.startswith(f"migrated {FIRST_REVISION} -> next00000001\nbackup: ")
    refused = runner.invoke(cli.app, ["vault", "migrate", folder, "--to", FIRST_REVISION])
    assert refused.exit_code == 1
    assert "downgrades are done by restoring a backup" in refused.stderr


def test_db_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean = runner.invoke(cli.app, ["db", "check"])
    assert clean.exit_code == 0
    assert "migrations are clean" in clean.stdout
    forked = script_directory(
        tmp_path / "forked",
        {
            "a.py": migration_source("fork00000001", FIRST_REVISION, "pass"),
            "b.py": migration_source("fork00000002", FIRST_REVISION, "pass"),
        },
    )
    monkeypatch.setattr(cli, "Migrator", lambda: Migrator(forked))
    failed = runner.invoke(cli.app, ["db", "check"])
    assert failed.exit_code == 1
    assert "exactly one head, found 2" in failed.stderr
    revision = runner.invoke(cli.app, ["db", "revision", "-m", "more"])
    assert revision.exit_code == 1
    assert revision.stderr.startswith("error: The migration history must have exactly one head")


def test_db_revision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    location = script_directory(tmp_path / "m", {})
    monkeypatch.setattr(cli, "Migrator", lambda: Migrator(location))
    result = runner.invoke(cli.app, ["db", "revision", "-m", "add things", "--autogenerate"])
    assert result.exit_code == 0, result.output
    [new] = list((location / "versions").glob("*_add_things.py"))
    assert f"wrote {new}" in result.stdout
