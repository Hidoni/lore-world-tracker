"""The import-linter contracts that guard module boundaries exist and hold."""

import tomllib
from pathlib import Path

from importlinter import cli as importlinter_cli

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _contracts() -> dict[str, dict[str, object]]:
    config = tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]
    return {contract["id"]: contract for contract in config["contracts"]}


def test_chronology_purity_contract_present() -> None:
    contract = _contracts()["chronology-is-pure"]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["lore.chronology"]
    assert {"lore.core", "lore.modules", "lore.app", "lore.cli", "lore.config"} <= set(
        contract["forbidden_modules"]  # type: ignore[call-overload]
    )


def test_core_does_not_import_modules_contract_present() -> None:
    contract = _contracts()["core-does-not-import-modules"]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["lore.core"]
    assert contract["forbidden_modules"] == ["lore.modules"]


def test_contracts_hold() -> None:
    assert importlinter_cli.lint_imports(config_filename=str(PYPROJECT)) == 0
