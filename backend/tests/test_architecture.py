"""The import-linter contracts that guard module boundaries exist and hold."""

import subprocess
import sys
import tomllib
from pathlib import Path

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
    # In a subprocess: import-linter reconfigures logging and would disable existing loggers.
    lint_imports = Path(sys.executable).parent / "lint-imports"
    result = subprocess.run(
        [lint_imports, "--config", PYPROJECT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
