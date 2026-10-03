import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lore.core.db.migrate import Migrator
from lore.core.errors import InvalidInputError, ReadOnlyError
from lore.core.vaults import VaultInfo, VaultManager
from lore.core.vaults.errors import (
    VaultMigrationFailedError,
    VaultNeedsMigrationError,
    VaultNewerThanAppError,
)
from lore.core.vaults.meta import get_meta
from tests.conftest import AppFactory, local_client
from tests.migration_harness import (
    REAL_HEAD,
    MigrationHarness,
    migration_source,
    script_directory,
)

NOTES_REVISION = "notes0000001"
NOTES = migration_source(
    NOTES_REVISION,
    REAL_HEAD,
    """
    op.create_table("notes", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO notes (id) VALUES (1)")
    """,
)
FAILING = migration_source(
    "fail00000001",
    REAL_HEAD,
    """
    op.create_table("half_done", sa.Column("id", sa.Integer(), primary_key=True))
    raise RuntimeError("boom")
    """,
)
HEADERS = {"X-Lore-Client": "test"}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def newer(tmp_path: Path) -> Migrator:
    """An app version whose history has one more migration than the real one."""
    return Migrator(script_directory(tmp_path / "newer", {"notes.py": NOTES}))


@pytest.fixture
def failing(tmp_path: Path) -> Migrator:
    return Migrator(script_directory(tmp_path / "failing", {"fail.py": FAILING}))


@pytest.fixture
def old_vault(data_dir: Path) -> VaultInfo:
    """A vault created by the current app (at REAL_HEAD), with some content."""
    manager = VaultManager(data_dir)
    info = manager.create("Aetheria")
    manager.close()
    return info


@pytest.fixture
def managers(data_dir: Path) -> Iterator[list[VaultManager]]:
    """Managers created by tests via ``make``; closed afterwards."""
    created: list[VaultManager] = []
    yield created
    for manager in created:
        manager.close()


def make(managers: list[VaultManager], data_dir: Path, **options: object) -> VaultManager:
    manager = VaultManager(data_dir, **options)  # type: ignore[arg-type]
    managers.append(manager)
    return manager


def backups(info: VaultInfo) -> list[Path]:
    folder = info.path / "backups" / "auto"
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_create_migrates_to_head_and_seeds_vault_meta(
    managers: list[VaultManager], data_dir: Path
) -> None:
    manager = make(managers, data_dir)
    info = manager.create("Aetheria")
    assert manager.schema_status(info).state == "current"
    assert backups(info) == []  # nothing to back up in a new vault
    with manager.open(info.id).sessions() as session:
        assert get_meta(session, "vault_id") == info.id
        assert get_meta(session, "name") == "Aetheria"
        assert get_meta(session, "created_at") == info.manifest.created_at.isoformat()
        assert get_meta(session, "settings")["defaults"] == {"visibility": "public"}


def test_rename_keeps_vault_meta_in_sync(managers: list[VaultManager], data_dir: Path) -> None:
    manager = make(managers, data_dir)
    info = manager.create("Aetheria")
    opened = manager.open(info.id)
    manager.rename(info.id, "Renamed")
    with opened.sessions() as session:
        assert get_meta(session, "name") == "Renamed"


def test_open_syncs_a_name_changed_while_closed(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo
) -> None:
    renamer = make(managers, data_dir)
    renamer.rename(old_vault.id, "Renamed")  # never opens the database
    renamer.close()
    with make(managers, data_dir).open(old_vault.id).sessions() as session:
        assert get_meta(session, "name") == "Renamed"


def test_open_auto_migrates_after_a_backup(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo, newer: Migrator
) -> None:
    manager = make(managers, data_dir, migrator=newer)
    assert manager.schema_status(old_vault).state == "needs_migration"
    opened = manager.open(old_vault.id)
    with opened.engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM notes")).scalar() == 1
    assert manager.schema_status(old_vault).state == "current"
    [backup] = backups(old_vault)
    assert backup.name.startswith(f"pre-migrate-{REAL_HEAD}-to-{NOTES_REVISION}-")
    assert backup.suffix == ".db"
    # the backup is the vault as it was, and restoring it brings the old schema back
    manager.close()
    shutil.copy(backup, old_vault.database_path)
    restored = MigrationHarness(old_vault.database_path)
    assert restored.revision == REAL_HEAD
    assert "notes" not in restored.tables()


def test_a_failed_migration_marks_the_vault_unusable(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo, failing: Migrator
) -> None:
    manager = make(managers, data_dir, migrator=failing)
    before = old_vault.database_path.read_bytes()
    with pytest.raises(VaultMigrationFailedError) as caught:
        manager.open(old_vault.id)
    error = caught.value
    assert error.code == "vault_migration_failed"
    assert error.status == 500
    assert error.context is not None
    [backup] = backups(old_vault)
    assert error.context["backup"] == str(backup)
    assert "boom" in error.context["error"]
    assert str(backup) in error.detail
    # the original file is untouched
    assert old_vault.database_path.read_bytes() == before
    harness = MigrationHarness(old_vault.database_path)
    assert harness.revision == REAL_HEAD
    assert "half_done" not in harness.tables()
    # unusable for this process: no second attempt, no second backup
    assert manager.schema_status(old_vault).state == "migration_failed"
    for attempt in (manager.open, manager.migrate):
        with pytest.raises(VaultMigrationFailedError, match="Restart the app"):
            attempt(old_vault.id)
    assert len(backups(old_vault)) == 1


def test_a_newer_vault_is_refused(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo, newer: Migrator
) -> None:
    newer_app = make(managers, data_dir, migrator=newer)
    newer_app.migrate(old_vault.id)
    newer_app.close()
    current_app = make(managers, data_dir)
    status = current_app.schema_status(old_vault)
    assert (status.state, status.revision, status.head) == (
        "newer_than_app",
        NOTES_REVISION,
        REAL_HEAD,
    )
    for attempt in (current_app.open, current_app.migrate):
        with pytest.raises(VaultNewerThanAppError) as caught:
            attempt(old_vault.id)
        assert caught.value.code == "vault_newer_than_app"
        assert caught.value.status == 409


def test_auto_migrate_off_needs_an_explicit_migration(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo, newer: Migrator
) -> None:
    manager = make(managers, data_dir, migrator=newer, auto_migrate=False)
    with pytest.raises(VaultNeedsMigrationError) as caught:
        manager.open(old_vault.id)
    assert caught.value.code == "vault_needs_migration"
    assert caught.value.context == {"revision": REAL_HEAD, "head": NOTES_REVISION}
    assert backups(old_vault) == []
    result = manager.migrate(old_vault.id)
    assert (result.from_revision, result.to_revision) == (REAL_HEAD, NOTES_REVISION)
    assert result.backup == backups(old_vault)[0]
    manager.open(old_vault.id)
    again = manager.migrate(old_vault.id)
    assert again.backup is None
    assert len(backups(old_vault)) == 1


def test_migrate_to_a_revision(
    managers: list[VaultManager], data_dir: Path, newer: Migrator, tmp_path: Path
) -> None:
    longest = Migrator(
        script_directory(
            tmp_path / "longest",
            {
                "notes.py": NOTES,
                "more.py": migration_source("more00000001", NOTES_REVISION, "pass"),
            },
        )
    )
    info = make(managers, data_dir).create("Aetheria")
    manager = make(managers, data_dir, migrator=longest, auto_migrate=False)
    result = manager.migrate(info.id, NOTES_REVISION)
    assert result.to_revision == NOTES_REVISION
    assert manager.schema_status(info).revision == NOTES_REVISION
    for target in (REAL_HEAD, "unknown", "base"):
        with pytest.raises(InvalidInputError, match="downgrades are done by restoring"):
            manager.migrate(info.id, target)
    assert manager.migrate(info.id).to_revision == "more00000001"


def test_read_only_never_migrates(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo, newer: Migrator
) -> None:
    reader = make(managers, data_dir, read_only=True, migrator=newer)
    with pytest.raises(VaultNeedsMigrationError):
        reader.open(old_vault.id)
    with pytest.raises(ReadOnlyError):
        reader.migrate(old_vault.id)
    assert backups(old_vault) == []
    current = make(managers, data_dir, read_only=True)
    with current.open(old_vault.id).engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM vault_meta")).scalar() == 4


def test_an_unreadable_database_is_reported(
    managers: list[VaultManager], data_dir: Path, old_vault: VaultInfo
) -> None:
    old_vault.database_path.write_bytes(b"this is not a database")
    assert make(managers, data_dir).schema_status(old_vault).state == "database_unreadable"


# --- API ------------------------------------------------------------------------------------


def test_schema_status_and_migrate_endpoint(
    make_app: AppFactory, data_dir: Path, old_vault: VaultInfo, newer: Migrator
) -> None:
    app = make_app(data_dir=data_dir, auto_migrate=False)
    app.state.vaults = VaultManager(data_dir, auto_migrate=False, migrator=newer)
    with local_client(app, headers=HEADERS) as client:
        vault = client.get(f"/api/v1/vaults/{old_vault.id}").json()
        assert vault["schema_status"] == {
            "state": "needs_migration",
            "revision": REAL_HEAD,
            "head": NOTES_REVISION,
        }
        response = client.post(f"/api/v1/vaults/{old_vault.id}/migrate")
        assert response.status_code == 200
        body = response.json()
        assert body["from_revision"] == REAL_HEAD
        assert body["to_revision"] == NOTES_REVISION
        assert body["backup"] == str(backups(old_vault)[0])
        assert body["vault"]["schema_status"]["state"] == "current"
        again = client.post(f"/api/v1/vaults/{old_vault.id}/migrate").json()
        assert again["backup"] is None
        [listed] = client.get("/api/v1/vaults").json()["items"]
        assert listed["schema_status"]["state"] == "current"


def test_migration_errors_over_http(
    make_app: AppFactory, data_dir: Path, old_vault: VaultInfo, failing: Migrator
) -> None:
    app = make_app(data_dir=data_dir)
    app.state.vaults = VaultManager(data_dir, migrator=failing)
    with local_client(app, headers=HEADERS) as client:
        response = client.post(f"/api/v1/vaults/{old_vault.id}/migrate")
        assert response.status_code == 500
        problem = response.json()
        assert problem["code"] == "vault_migration_failed"
        assert problem["context"]["backup"].endswith(".db")


def test_migrate_endpoint_is_refused_read_only(
    make_app: AppFactory, data_dir: Path, old_vault: VaultInfo
) -> None:
    client: TestClient
    with local_client(make_app(data_dir=data_dir, read_only=True), headers=HEADERS) as client:
        response = client.post(f"/api/v1/vaults/{old_vault.id}/migrate")
    assert response.status_code == 403
    assert response.json()["code"] == "read_only"
