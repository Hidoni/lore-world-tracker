"""Migration test harness (``persistence-and-migrations.md`` §3.5 and §3.6).

Data-migration tests use the ``migrations`` fixture (``tests/conftest.py``)::

    def test_backfills_slugs(migrations: MigrationHarness) -> None:
        migrations.upgrade("<revision before>")
        migrations.execute("INSERT INTO entities (...) VALUES (...)")
        migrations.upgrade("<your revision>")
        assert migrations.rows("SELECT slug FROM entities") == [("dragon",)]

Framework tests build throwaway histories with :func:`script_directory`.
"""

import shutil
import sqlite3
import textwrap
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lore.core.db.migrate import MIGRATIONS_DIR, Migrator

FIRST_REVISION = "b9f3e4412ccc"


class MigrationHarness:
    """One SQLite database file plus the migrator that upgrades it."""

    def __init__(self, path: Path, migrator: Migrator | None = None) -> None:
        self.path = path
        self.migrator = migrator or Migrator()
        if not path.exists():
            sqlite3.connect(path).close()

    def upgrade(self, target: str = "head", *, vault: Mapping[str, str] | None = None) -> None:
        self.migrator.upgrade(self.path, target, attributes={"vault": dict(vault or {})})

    @property
    def revision(self) -> str | None:
        return self.migrator.status_of(self.path).revision

    def execute(self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] = ()) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def rows(self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] = ()) -> list[Any]:
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def tables(self) -> set[str]:
        return {name for (name,) in self.rows("SELECT name FROM sqlite_master WHERE type='table'")}


def migration_source(
    revision: str, down_revision: str | None, upgrade: str, downgrade: str = "pass"
) -> str:
    """The source of a migration file (``upgrade``/``downgrade`` are function bodies)."""
    return (
        f'"""[core] test migration {revision}"""\n'
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        f"revision = {revision!r}\n"
        f"down_revision = {down_revision!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n\n\n"
        "def upgrade() -> None:\n"
        f"{textwrap.indent(textwrap.dedent(upgrade).strip(), '    ')}\n\n\n"
        "def downgrade() -> None:\n"
        f"{textwrap.indent(textwrap.dedent(downgrade).strip(), '    ')}\n"
    )


def script_directory(
    root: Path, migrations: Mapping[str, str], *, include_real: bool = True
) -> Path:
    """A migration directory using the real ``env.py`` and template: the real migrations (if
    ``include_real``) plus ``migrations`` (file name → source)."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("env.py", "script.py.mako"):
        shutil.copy(MIGRATIONS_DIR / name, root / name)
    versions = root / "versions"
    versions.mkdir()
    if include_real:
        for path in (MIGRATIONS_DIR / "versions").glob("*.py"):
            shutil.copy(path, versions / path.name)
    for name, source in migrations.items():
        (versions / name).write_text(source, encoding="utf-8")
    return root
