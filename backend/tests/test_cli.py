import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.app import create_app_from_env

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
    return calls


def test_serve_uses_settings_and_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_uvicorn(monkeypatch)
    monkeypatch.setenv("LORE_PORT", "9001")
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0
    [(app, options)] = calls
    assert not isinstance(app, str)
    assert options == {"host": "127.0.0.1", "port": 9001, "log_level": "info", "workers": 1}


def test_serve_reload_uses_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_uvicorn(monkeypatch)
    result = runner.invoke(cli.app, ["serve", "--reload", "--host", "0.0.0.0", "--port", "1234"])
    assert result.exit_code == 0
    [(app, options)] = calls
    assert app == "lore.app:create_app_from_env"
    assert options["factory"] is True
    assert options["reload"] is True
    assert options["workers"] == 1
    assert (options["host"], options["port"]) == ("0.0.0.0", 1234)


def test_app_factory_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_READ_ONLY", "true")
    assert create_app_from_env().state.settings.read_only is True
