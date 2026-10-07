"""Vault maintenance (``persistence-and-migrations.md`` §2, §3.4): ``check`` (schema state, SQLite
integrity, foreign keys and the derived-data checkers, on a copy of the database), ``reindex``
(rebuild all derived data) and ``optimize`` (``PRAGMA optimize``, optionally ``VACUUM``)."""

import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from lore.core.db import create_vault_engine, optimize, snapshot, vacuum
from lore.core.db.migrate import SchemaState, SchemaStatus
from lore.core.maintenance.checks import DERIVED_DATA, DerivedDataCheck, Problem
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults import OpenVault, VaultManager
from lore.core.vaults.format import DATABASE_NAME


@dataclass(frozen=True)
class CheckReport:
    checks: tuple[str, ...]  # the ids of the checks that ran
    problems: tuple[Problem, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def sqlite_problems(session: Session) -> list[Problem]:
    """``PRAGMA integrity_check`` (at most its first 100 errors) and ``foreign_key_check``."""
    problems = [
        Problem("integrity", "integrity_error", message)
        for (message,) in session.connection().exec_driver_sql("PRAGMA integrity_check").all()
        if message != "ok"
    ]
    for table, rowid, parent, _fk in session.connection().exec_driver_sql(
        "PRAGMA foreign_key_check"
    ):
        problems.append(
            Problem(
                "foreign_keys",
                "foreign_key_violation",
                f"{table} row {rowid} refers to a missing {parent} row",
            )
        )
    return problems


def check_vault(
    manager: VaultManager,
    vault_id: str,
    checks: Sequence[DerivedDataCheck] = DERIVED_DATA,
    scratch_dir: Path | None = None,
) -> CheckReport:
    """Check a vault without changing anything in its folder.

    The database is copied (``snapshot``: consistent, WAL included, the source only read) into a
    temporary folder (``scratch_dir``, default the system's) and everything runs on the copy,
    which is deleted afterwards. A copy that isn't at this app's head is reported and not
    checked further. The vault isn't opened through the manager (no migration, no index
    rebuild, no lock), so a running server can keep it open meanwhile.
    """
    if manager.module_registry is None:
        raise ValueError("checking a vault needs the module registry")
    info = manager.get(vault_id)
    with tempfile.TemporaryDirectory(prefix="lore-check-", dir=scratch_dir) as scratch:
        copy = Path(scratch) / DATABASE_NAME
        try:
            snapshot(info.database_path, copy)
            status = manager.migrator.status_of(copy)
        except sqlite3.DatabaseError as error:
            return _unreadable(error)
        except DatabaseError as error:
            return _unreadable(error.orig)
        if status.state is not SchemaState.CURRENT:
            return CheckReport(("schema",), (_schema_problem(status),))
        engine = create_vault_engine(copy, pool=NullPool)
        try:
            opened = OpenVault(info, engine, False, manager.module_registry.history_tables())
            report = run_checks(opened, manager.module_registry, checks)
        finally:
            engine.dispose()
    return CheckReport(("schema", *report.checks), report.problems)


def _schema_problem(status: SchemaStatus) -> Problem:
    advice = (
        "migrate the vault first"
        if status.state is SchemaState.NEEDS_MIGRATION
        else "it was written by a newer app version"
    )
    return Problem(
        "schema",
        f"vault_{status.state}",
        f"the schema is at {status.revision or 'base'}, this app's head is {status.head}: {advice}",
    )


def _unreadable(error: BaseException | None) -> CheckReport:
    return CheckReport(
        ("schema",),
        (Problem("schema", "database_unreadable", f"the database can't be read: {error}"),),
    )


def run_checks(
    vault: OpenVault,
    registry: ModuleRegistry,
    checks: Sequence[DerivedDataCheck] = DERIVED_DATA,
) -> CheckReport:
    """Run every check on an opened database in one transaction that is rolled back (a write
    transaction: FTS5's integrity check needs one). ``check_vault`` runs it on a copy."""
    factory = vault.sessions if vault.read_only else vault.write_sessions
    with factory() as session:
        try:
            problems = sqlite_problems(session)
            context = VaultContext(vault, session, registry)
            for check in checks:
                problems += check.verify(context)
        finally:
            session.rollback()
    return CheckReport(
        ("integrity", "foreign_keys", *(check.id for check in checks)), tuple(problems)
    )


def reindex_vault(
    vault: OpenVault,
    registry: ModuleRegistry,
    checks: Sequence[DerivedDataCheck] = DERIVED_DATA,
) -> dict[str, int]:
    """Rebuild every kind of derived data in one write transaction; returns the count of each.
    The consistency findings are scanned again afterwards (``consistency``: their number); a
    repair records findings but never refuses (``record_only``)."""
    from lore.core.consistency.engine import record_only, scan  # noqa: PLC0415 (import cycle)

    counts: dict[str, int] = {}
    with vault.write_sessions.begin() as session:
        record_only(session)
        context = VaultContext(vault, session, registry)
        for check in checks:
            counts[check.id] = check.rebuild(context)
        counts["consistency"] = sum(scan(context).values())
    return counts


def optimize_vault(vault: OpenVault, *, vacuum_database: bool = False) -> None:
    """``PRAGMA optimize``, then ``VACUUM`` (rewrites the whole file: needs free disk space about
    the size of the database) when asked."""
    optimize(vault.engine)
    if vacuum_database:
        vacuum(vault.engine)
