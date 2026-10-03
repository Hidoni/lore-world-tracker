import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from lore.core.db import (
    SQLiteCapabilityError,
    create_vault_engine,
    ensure_sqlite_capabilities,
    missing_sqlite_capabilities,
)
from tests.conftest import AppFactory, local_client


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "lore.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    connection.execute("INSERT INTO notes (body) VALUES ('hello')")
    connection.commit()
    connection.close()
    return path


PRAGMA_NAMES = ("journal_mode", "synchronous", "foreign_keys", "busy_timeout", "temp_store")


def pragmas(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        return {
            name: connection.exec_driver_sql(f"PRAGMA {name}").scalar() for name in PRAGMA_NAMES
        }


def test_author_pragmas_apply_to_every_connection(database: Path) -> None:
    engine = create_vault_engine(database)
    try:
        expected = {
            "journal_mode": "wal",
            "synchronous": 1,  # NORMAL
            "foreign_keys": 1,
            "busy_timeout": 5000,
            "temp_store": 2,  # MEMORY
        }
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        engine.dispose()  # a fresh pool: new connections get the PRAGMAs too
        assert pragmas(engine) == expected
    finally:
        engine.dispose()


def test_transactions_commit_and_roll_back(database: Path) -> None:
    engine = create_vault_engine(database)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO notes (body) VALUES ('kept')"))
        connection = engine.connect()
        transaction = connection.begin()
        connection.execute(text("INSERT INTO notes (body) VALUES ('dropped')"))
        transaction.rollback()
        connection.close()
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE scratch (x)"))
            savepoint = connection.begin_nested()
            connection.execute(text("INSERT INTO scratch VALUES (1)"))
            savepoint.rollback()
            assert connection.execute(text("SELECT count(*) FROM scratch")).scalar() == 0
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT body FROM notes ORDER BY id")).all()
            assert [row.body for row in rows] == ["hello", "kept"]
    finally:
        engine.dispose()


def test_author_mode_never_creates_a_database(tmp_path: Path) -> None:
    engine = create_vault_engine(tmp_path / "missing.db")
    with pytest.raises(OperationalError), engine.connect():
        pass
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.parametrize("immutable", [False, True])
def test_read_only_open_refuses_writes(database: Path, immutable: bool) -> None:
    engine = create_vault_engine(database, read_only=True, immutable=immutable)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT body FROM notes")).scalar() == "hello"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            # read-only connections leave the persistent journal mode alone
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "delete"
        with pytest.raises(OperationalError, match="readonly"), engine.begin() as connection:
            connection.execute(text("INSERT INTO notes (body) VALUES ('nope')"))
    finally:
        engine.dispose()


def test_immutable_requires_read_only(database: Path) -> None:
    with pytest.raises(ValueError, match="immutable"):
        create_vault_engine(database, immutable=True)


def test_paths_with_uri_characters(tmp_path: Path) -> None:
    folder = tmp_path / "a ?#%&b"
    folder.mkdir()
    path = folder / "lore.db"
    sqlite3.connect(path).close()
    engine = create_vault_engine(path, read_only=True)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


def test_this_sqlite_has_every_capability() -> None:
    assert missing_sqlite_capabilities() == []
    ensure_sqlite_capabilities()


class CrippledSQLite:
    """A connection to an old SQLite without FTS5 (simulated)."""

    def __init__(self) -> None:
        self.inner = sqlite3.connect(":memory:")

    def execute(self, sql: str) -> sqlite3.Cursor:
        if "sqlite_version" in sql:
            return self.inner.execute("SELECT '3.40.1'")
        if "fts5" in sql:
            raise sqlite3.OperationalError("no such module: fts5")
        return self.inner.execute(sql)

    def close(self) -> None:
        self.inner.close()


def crippled() -> sqlite3.Connection:
    return CrippledSQLite()  # type: ignore[return-value]


def test_capability_check_reports_what_is_missing() -> None:
    assert missing_sqlite_capabilities(crippled) == [
        "sqlite>=3.43.0 (found 3.40.1)",
        "fts5_trigram",
        "fts5_contentless_delete",
    ]
    with pytest.raises(SQLiteCapabilityError) as caught:
        ensure_sqlite_capabilities(crippled)
    assert caught.value.code == "sqlite_unsupported"
    assert caught.value.context == {
        "missing": ["sqlite>=3.43.0 (found 3.40.1)", "fts5_trigram", "fts5_contentless_delete"]
    }


def test_app_refuses_to_start_without_capabilities(
    make_app: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> None:
        raise SQLiteCapabilityError("too old")

    monkeypatch.setattr("lore.app.ensure_sqlite_capabilities", fail)
    with pytest.raises(SQLiteCapabilityError), local_client(make_app()):
        pass
