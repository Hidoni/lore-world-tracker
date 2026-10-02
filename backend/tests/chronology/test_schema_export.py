import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.chronology.schema_export import BUNDLE_FILE, TOP_LEVEL_TYPES, export_schemas

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "spec" / "chronology" / "schema"

runner = CliRunner()


def test_export_produces_one_file_per_type_and_a_bundle() -> None:
    files = export_schemas()
    assert set(files) == set(TOP_LEVEL_TYPES) | {BUNDLE_FILE}
    for name, (type_name, _) in TOP_LEVEL_TYPES.items():
        document = json.loads(files[name])
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert document["title"] == type_name
        assert "$ref" not in document  # the root is the type itself
    bundle = json.loads(files[BUNDLE_FILE])
    assert set(bundle["properties"]) == {name for name, _ in TOP_LEVEL_TYPES.values()}
    assert {"TimePoint", "LocalAnchor", "Predicate", "CalendarRule"} <= bundle["$defs"].keys()


def test_export_is_deterministic_and_has_no_field_titles() -> None:
    first, second = export_schemas(), export_schemas()
    assert first == second
    rational = json.loads(first["rational.json"])
    assert "title" not in rational["properties"]["num"]


def test_committed_schemas_are_up_to_date() -> None:
    """The drift check behind "editing a model without `make gen` fails `make check`"."""
    for name, text in export_schemas().items():
        assert (SCHEMA_DIR / name).read_text(encoding="utf-8") == text, (
            f"spec/chronology/schema/{name} is stale: run `make gen`"
        )


def test_cli_writes_and_checks(tmp_path: Path) -> None:
    out = tmp_path / "schema"
    stale = tmp_path / "schema" / "removed-type.json"
    out.mkdir()
    stale.write_text("{}")

    result = runner.invoke(cli.app, ["chronology", "export-schemas", "--out", str(out), "--check"])
    assert result.exit_code == 1
    assert "not generated" in result.output
    assert "stale" in result.output

    result = runner.invoke(cli.app, ["chronology", "export-schemas", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert {path.name for path in out.iterdir()} == set(export_schemas())

    result = runner.invoke(cli.app, ["chronology", "export-schemas", "--out", str(out), "--check"])
    assert result.exit_code == 0
    assert "up to date" in result.output

    (out / "rational.json").write_text("{}\n")
    result = runner.invoke(cli.app, ["chronology", "export-schemas", "--out", str(out), "--check"])
    assert result.exit_code == 1
    assert "rational.json" in result.output


def test_cli_defaults_to_the_spec_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_SPEC_DIR", str(tmp_path))
    result = runner.invoke(cli.app, ["chronology", "export-schemas"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "chronology" / "schema" / BUNDLE_FILE).is_file()


def test_cli_without_spec_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_SPEC_DIR", "")
    result = runner.invoke(cli.app, ["chronology", "export-schemas"])
    assert result.exit_code == 2
    assert "no spec directory" in result.output
