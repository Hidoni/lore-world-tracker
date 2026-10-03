"""The import-linter contracts that guard module boundaries exist and hold."""

import ast
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


# --- module boundaries (modules.md §2.3) -----------------------------------------------------
# lore.modules.<a> may import lore.modules.<b> only as lore.modules.<b>.api, and only when <b> is
# in <a>.depends_on. The rule depends on each module's declared dependencies, so it is checked
# here from the registry instead of a static import-linter contract.

MODULES_ROOT = Path(__file__).resolve().parents[1] / "src" / "lore" / "modules"


def _imported_names(path: Path, package: str) -> list[tuple[int, str]]:
    """Absolute names imported by a file (``from x import y`` yields ``x.y`` and ``x``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            names += [(node.lineno, f"{module}.{alias.name}") for alias in node.names]
    return names


def module_import_violations(root: Path, depends_on: dict[str, tuple[str, ...]]) -> list[str]:
    violations: list[str] = []
    for package_dir in sorted(p for p in root.iterdir() if (p / "__init__.py").is_file()):
        module_id = package_dir.name
        if module_id not in depends_on:
            violations.append(f"{module_id}: package is not registered in ALL_MODULES")
            continue
        for path in sorted(package_dir.rglob("*.py")):
            relative = path.relative_to(root).with_suffix("")
            package = ".".join(["lore", "modules", *relative.parts[:-1]])
            for line, name in _imported_names(path, package):
                parts = name.split(".")
                if parts[:2] != ["lore", "modules"]:
                    continue
                where = f"{path.relative_to(root)}:{line}"
                if len(parts) < 3 or parts[2] in {"__init__", "load_metadata", "ALL_MODULES"}:
                    violations.append(f"{where}: imports lore.modules itself ({name})")
                    continue
                other = parts[2]
                if other == module_id:
                    continue
                if parts[3:4] != ["api"]:
                    violations.append(f"{where}: {name}: only lore.modules.{other}.api is public")
                elif other not in depends_on[module_id]:
                    violations.append(f"{where}: {name}: {other!r} is not in depends_on")
    return violations


def test_modules_import_only_declared_dependencies_through_api() -> None:
    from lore.modules import ALL_MODULES  # noqa: PLC0415

    declared = {module.id: module.depends_on for module in ALL_MODULES}
    assert module_import_violations(MODULES_ROOT, declared) == []


def test_module_boundary_check_catches_violations(tmp_path: Path) -> None:
    files = {
        "a/__init__.py": "",
        "a/api.py": "def thing() -> None: ...\n",
        "b/__init__.py": "",
        "b/service.py": (
            "from lore.modules.a import api\n"  # ok: declared dependency, public API
            "from lore.modules.a.api import thing\n"  # ok
            "from lore.modules.b import models\n"  # ok: own package
            "from . import models as again\n"  # ok: relative, own package
        ),
        "b/models.py": "",
        "c/__init__.py": "",
        "c/service.py": (
            "import lore.modules.a.service\n"  # not the public API
            "from lore.modules.a import api\n"  # a is not a dependency of c
            "from lore.modules import ALL_MODULES\n"  # the registry itself
            "from ..a import service\n"  # relative escape into another module
        ),
        "stray/__init__.py": "",
    }
    for name, source in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(source)
    violations = module_import_violations(tmp_path, {"a": (), "b": ("a",), "c": ()})
    assert violations == [
        "c/service.py:1: lore.modules.a.service: only lore.modules.a.api is public",
        "c/service.py:2: lore.modules.a.api: 'a' is not in depends_on",
        "c/service.py:3: imports lore.modules itself (lore.modules.ALL_MODULES)",
        "c/service.py:4: lore.modules.a.service: only lore.modules.a.api is public",
        "stray: package is not registered in ALL_MODULES",
    ]
