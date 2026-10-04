"""SQLite engines: connection PRAGMAs, read-only opening and the startup capability check."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry, Pool, QueuePool

from lore.core.errors import LoreError

# The trigram tokenizer's remove_diacritics option arrived in 3.45 (trigram in 3.34, window
# functions in 3.25).
MIN_SQLITE_VERSION = (3, 45, 0)

# Applied on every new connection, in this order. journal_mode is persistent and needs write
# access, so read-only connections skip it.
AUTHOR_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA temp_store = MEMORY",
)
READ_ONLY_PRAGMAS = AUTHOR_PRAGMAS[1:]

# Execution option read by the "begin" hook (see for_writing).
BEGIN_IMMEDIATE_OPTION = "lore_begin_immediate"

# One probe per required feature: (name, statements). A probe fails if any statement raises.
_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("json1", ("SELECT json_extract('{\"a\": 1}', '$.a')",)),
    ("window_functions", ("SELECT row_number() OVER (ORDER BY 1)",)),
    (
        "fts5_trigram",
        (
            "CREATE VIRTUAL TABLE temp.lore_probe_trigram"
            " USING fts5(x, tokenize = 'trigram remove_diacritics 1')",
            "DROP TABLE temp.lore_probe_trigram",
        ),
    ),
)


class SQLiteCapabilityError(LoreError):
    """The SQLite library lacks a feature the app relies on (the app refuses to start)."""

    code = "sqlite_unsupported"
    title = "Unsupported SQLite build"


def _parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".")[:3])


def missing_sqlite_capabilities(
    connect: Callable[[], sqlite3.Connection] = lambda: sqlite3.connect(":memory:"),
) -> list[str]:
    """Names of the required SQLite features that ``connect()``'s library doesn't provide."""
    connection = connect()
    try:
        missing: list[str] = []
        (version,) = connection.execute("SELECT sqlite_version()").fetchone()
        if _parse_version(version) < MIN_SQLITE_VERSION:
            minimum = ".".join(map(str, MIN_SQLITE_VERSION))
            missing.append(f"sqlite>={minimum} (found {version})")
        for name, statements in _PROBES:
            try:
                for statement in statements:
                    connection.execute(statement)
            except sqlite3.Error:
                missing.append(name)
        return missing
    finally:
        connection.close()


def ensure_sqlite_capabilities(
    connect: Callable[[], sqlite3.Connection] = lambda: sqlite3.connect(":memory:"),
) -> None:
    missing = missing_sqlite_capabilities(connect)
    if missing:
        raise SQLiteCapabilityError(
            "This SQLite build lacks required features: " + ", ".join(missing),
            context={"missing": missing},
        )


def database_uri(path: Path, *, read_only: bool, immutable: bool) -> str:
    # URIs give explicit modes: rw refuses to create a missing database, ro refuses writes.
    uri = f"file:{quote(str(path.resolve()))}?mode={'ro' if read_only else 'rw'}"
    if immutable:
        uri += "&immutable=1"
    return uri


def create_vault_engine(
    path: Path,
    *,
    read_only: bool = False,
    immutable: bool = False,
    foreign_keys: bool = True,
    pool: type[Pool] = QueuePool,
) -> Engine:
    """An engine on an existing vault database.

    ``read_only`` opens with ``mode=ro`` (writes fail), ``immutable`` additionally tells SQLite the
    file cannot change (published snapshots, ``journal_mode=DELETE``). Connections are opened
    lazily; the PRAGMAs run on each new one. ``foreign_keys=False`` is for migrations only
    (``lore.core.db.migrate``), which check the foreign keys themselves before committing.
    """
    if immutable and not read_only:
        raise ValueError("immutable requires read_only")
    uri = database_uri(path, read_only=read_only, immutable=immutable)
    pragmas: tuple[str, ...] = READ_ONLY_PRAGMAS if read_only else AUTHOR_PRAGMAS
    if not foreign_keys:
        pragmas = tuple(
            "PRAGMA foreign_keys = OFF" if pragma == "PRAGMA foreign_keys = ON" else pragma
            for pragma in pragmas
        )

    def creator() -> sqlite3.Connection:
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    engine = create_engine("sqlite+pysqlite://", creator=creator, poolclass=pool)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
        # Let SQLAlchemy emit BEGIN itself (see "begin" below) instead of pysqlite's implicit
        # transaction handling, so SAVEPOINTs and transactional DDL behave.
        dbapi_connection.isolation_level = None
        for pragma in pragmas:
            dbapi_connection.execute(pragma)

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        immediate = connection.get_execution_options().get(BEGIN_IMMEDIATE_OPTION, False)
        connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def for_writing(engine: Engine) -> Engine:
    """The same engine (and pool), but transactions start with ``BEGIN IMMEDIATE``.

    Use it for every transaction that may write. A deferred transaction that has read and then
    writes after another connection committed fails at once with "database is locked"
    (``SQLITE_BUSY_SNAPSHOT``): ``busy_timeout`` can't help, because waiting wouldn't make its
    snapshot current. ``BEGIN IMMEDIATE`` takes the write lock up front, so concurrent writers
    wait their turn (up to ``busy_timeout``) instead. Reads stay deferred and never block.
    """
    return engine.execution_options(**{BEGIN_IMMEDIATE_OPTION: True})


def optimize(engine: Engine) -> None:
    """``PRAGMA optimize`` (on vault close)."""
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA optimize")
