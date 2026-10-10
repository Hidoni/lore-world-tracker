"""Per-vault SQLite engines (``docs/architecture/persistence-and-migrations.md`` §2)."""

from lore.core.db.engine import (
    MIN_SQLITE_VERSION,
    SQLiteCapabilityError,
    Unindexed,
    WriteCounter,
    create_vault_engine,
    ensure_sqlite_capabilities,
    for_writing,
    missing_sqlite_capabilities,
    optimize,
    snapshot,
    unindexed,
    vacuum,
)

__all__ = [
    "MIN_SQLITE_VERSION",
    "SQLiteCapabilityError",
    "Unindexed",
    "WriteCounter",
    "create_vault_engine",
    "ensure_sqlite_capabilities",
    "for_writing",
    "missing_sqlite_capabilities",
    "optimize",
    "snapshot",
    "unindexed",
    "vacuum",
]
