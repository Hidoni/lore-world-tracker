import json
import re
import tempfile
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Column, Integer, MetaData, Table

from lore.core.db import create_vault_engine
from lore.core.db.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    Migrator,
    SchemaState,
    backup_database,
)
from lore.core.models import load_metadata
from tests.migration_harness import (
    FIRST_REVISION,
    MigrationHarness,
    migration_source,
    script_directory,
)

NOTES = migration_source(
    "notes0000001",
    FIRST_REVISION,
    'op.create_table("notes", sa.Column("id", sa.Integer(), primary_key=True))',
    'op.drop_table("notes")',
)


def notes_metadata() -> MetaData:
    """The real models plus a ``notes`` table (as a model change that needs a migration)."""
    metadata = MetaData(naming_convention=load_metadata().naming_convention)
    for table in load_metadata().tables.values():
        table.to_metadata(metadata)
    Table("notes", metadata, Column("id", Integer, primary_key=True))
    return metadata


# --- the real history -----------------------------------------------------------------------


def test_upgrade_an_empty_database_to_head(migrations: MigrationHarness) -> None:
    assert migrations.revision is None
    migrations.upgrade(
        vault={"vault_id": "v-1", "name": "Aetheria", "created_at": "2026-10-03T00:00:00+00:00"}
    )
    assert migrations.revision == Migrator().head()
    assert migrations.tables() == {"alembic_version", "vault_meta"}
    meta = {key: json.loads(value) for key, value in migrations.rows("SELECT * FROM vault_meta")}
    assert meta == {
        "vault_id": "v-1",
        "name": "Aetheria",
        "created_at": "2026-10-03T00:00:00+00:00",
        "settings": {
            "modules": {},
            "consistency": {},
            "display": {},
            "defaults": {"visibility": "public"},
        },
    }


def test_the_real_history_is_clean() -> None:
    migrator = Migrator()
    assert len(migrator.heads()) == 1
    assert migrator.check() == []


def test_real_migrations_are_self_contained_and_named() -> None:
    template = re.compile(r"^\d{8}_\d{4}_[0-9a-f]{12}_[a-z0-9_]+\.py$")
    for path in sorted((MIGRATIONS_DIR / "versions").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert template.fullmatch(path.name), path.name
        assert re.search(r'^"""\[(core|core:time|module: [a-z_]+)\] ', source), path.name
        assert not re.search(r"^\s*(from|import) lore\b", source, re.MULTILINE), path.name


def test_downgrade_of_the_first_migration(migrations: MigrationHarness) -> None:
    migrations.upgrade()
    engine = create_vault_engine(migrations.path)
    try:
        with engine.connect() as connection, connection.begin():
            command.downgrade(migrations.migrator.config(connection), "base")
    finally:
        engine.dispose()
    assert migrations.tables() == {"alembic_version"}


# --- status ---------------------------------------------------------------------------------


def test_status_compares_with_head(tmp_path: Path) -> None:
    longer = Migrator(script_directory(tmp_path / "longer", {"notes.py": NOTES}))
    shorter = Migrator()
    database = MigrationHarness(tmp_path / "x.db", longer)
    assert shorter.status_of(database.path).state is SchemaState.NEEDS_MIGRATION
    database.upgrade(FIRST_REVISION)
    assert shorter.status_of(database.path).state is SchemaState.CURRENT
    assert longer.status_of(database.path).state is SchemaState.NEEDS_MIGRATION
    database.upgrade()
    status = shorter.status_of(database.path)
    assert status.state is SchemaState.NEWER_THAN_APP
    assert (status.revision, status.head) == ("notes0000001", FIRST_REVISION)


def test_is_ahead(tmp_path: Path) -> None:
    migrator = Migrator(script_directory(tmp_path / "m", {"notes.py": NOTES}))
    assert migrator.is_ahead("notes0000001", FIRST_REVISION)
    assert migrator.is_ahead("notes0000001", None)
    assert migrator.is_ahead(FIRST_REVISION, None)
    assert not migrator.is_ahead(FIRST_REVISION, "notes0000001")
    assert not migrator.is_ahead(FIRST_REVISION, FIRST_REVISION)
    assert not migrator.is_ahead("unknown", None)
    assert not migrator.is_ahead(FIRST_REVISION, "unknown")


# --- failure handling -----------------------------------------------------------------------


def test_a_failing_migration_leaves_the_database_untouched(tmp_path: Path) -> None:
    failing = migration_source(
        "fail00000001",
        FIRST_REVISION,
        """
        op.create_table("half_done", sa.Column("id", sa.Integer(), primary_key=True))
        op.execute("UPDATE vault_meta SET value = '\\"changed\\"' WHERE key = 'name'")
        raise RuntimeError("boom")
        """,
    )
    migrator = Migrator(script_directory(tmp_path / "m", {"fail.py": failing}))
    database = MigrationHarness(tmp_path / "x.db", migrator)
    database.upgrade(FIRST_REVISION, vault={"name": "Aetheria"})
    before = database.path.read_bytes()
    with pytest.raises(RuntimeError, match="boom"):
        database.upgrade()
    assert database.revision == FIRST_REVISION
    assert "half_done" not in database.tables()
    assert database.rows("SELECT value FROM vault_meta WHERE key = 'name'") == [('"Aetheria"',)]
    assert database.path.read_bytes() == before


def test_foreign_key_violations_abort_the_migration(tmp_path: Path) -> None:
    orphans = migration_source(
        "fk0000000001",
        FIRST_REVISION,
        """
        op.create_table("parents", sa.Column("id", sa.Integer(), primary_key=True))
        op.create_table(
            "children",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("parents.id")),
        )
        op.execute("INSERT INTO children (id, parent_id) VALUES (1, 99)")
        """,
    )
    migrator = Migrator(script_directory(tmp_path / "m", {"fk.py": orphans}))
    database = MigrationHarness(tmp_path / "x.db", migrator)
    with pytest.raises(MigrationError, match="foreign key"):
        database.upgrade()
    assert database.revision is None
    assert database.tables() == set()


def test_backup_is_a_restorable_copy(tmp_path: Path, migrations: MigrationHarness) -> None:
    migrations.upgrade(vault={"name": "Aetheria"})
    backup = tmp_path / "backups" / "auto" / "copy.db"
    backup_database(migrations.path, backup)
    restored = MigrationHarness(backup)
    assert restored.revision == migrations.revision
    assert restored.rows("SELECT value FROM vault_meta WHERE key='name'") == [('"Aetheria"',)]


# --- lore db check / revision ---------------------------------------------------------------


def test_check_fails_with_two_heads(tmp_path: Path) -> None:
    fork = migration_source("fork00000001", FIRST_REVISION, "pass")
    other = migration_source("fork00000002", FIRST_REVISION, "pass")
    migrator = Migrator(script_directory(tmp_path / "m", {"a.py": fork, "b.py": other}))
    [problem] = migrator.check()
    assert "exactly one head, found 2" in problem
    with pytest.raises(MigrationError):
        migrator.head()
    with pytest.raises(MigrationError):
        migrator.revision("more")


def test_check_fails_when_models_and_migrations_differ(tmp_path: Path) -> None:
    model_without_migration = Migrator(metadata=notes_metadata)
    assert model_without_migration.check() == [
        "model/migration mismatch: ('add_table', Table('notes', MetaData(), "
        "Column('id', Integer(), table=<notes>, primary_key=True, nullable=False), schema=None))"
    ]
    migration_without_model = Migrator(script_directory(tmp_path / "m", {"notes.py": NOTES}))
    [problem] = migration_without_model.check()
    assert problem.startswith("model/migration mismatch: ('remove_table'")
    both = Migrator(script_directory(tmp_path / "both", {"notes.py": NOTES}), notes_metadata)
    assert both.check() == []


def test_check_ignores_fts_tables(tmp_path: Path) -> None:
    fts = migration_source(
        "fts000000001",
        FIRST_REVISION,
        """
        op.execute("CREATE VIRTUAL TABLE search_fts USING fts5(body)")
        op.execute("CREATE VIRTUAL TABLE search_trigram USING fts5(body, tokenize='trigram')")
        """,
    )
    migrator = Migrator(script_directory(tmp_path / "m", {"fts.py": fts}))
    assert migrator.check() == []


def test_revision_autogenerates_from_the_models(tmp_path: Path) -> None:
    migrator = Migrator(script_directory(tmp_path / "m", {}), notes_metadata)
    path = migrator.revision("Add notes", autogenerate=True)
    assert path.parent == tmp_path / "m" / "versions"
    assert re.fullmatch(r"\d{8}_\d{4}_[0-9a-f]{12}_add_notes\.py", path.name)
    source = path.read_text(encoding="utf-8")
    assert source.startswith('"""[core] Add notes')
    assert f"down_revision: str | None = {FIRST_REVISION!r}" in source
    assert 'op.create_table("notes"' in source or "op.create_table('notes'" in source
    assert migrator.check() == []  # the new migration matches the models


def test_plain_revision(tmp_path: Path) -> None:
    migrator = Migrator(script_directory(tmp_path / "m", {}))
    path = migrator.revision("backfill something")
    source = path.read_text(encoding="utf-8")
    assert "def upgrade() -> None:\n    pass" in source
    assert len(migrator.heads()) == 1
    assert migrator.heads() != [FIRST_REVISION]


def test_env_refuses_to_run_without_a_connection() -> None:
    with pytest.raises(RuntimeError, match=r"lore\.core\.db\.migrate"):
        command.upgrade(Migrator().config(), "head")


def test_scratch_databases_are_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert Migrator().check() == []
    assert list(tmp_path.iterdir()) == []
