"""Vault maintenance (``persistence-and-migrations.md`` §2, §3.4): ``check`` (schema state, SQLite
integrity, foreign keys and the derived-data checkers, on a copy of the database), ``reindex``
(rebuild all derived data), ``compact-history`` (history older than N days into per-entity
snapshots) and ``optimize`` (``PRAGMA optimize``, optionally ``VACUUM``)."""

import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from lore.core.db import create_vault_engine, optimize, snapshot, vacuum
from lore.core.db.migrate import SchemaState, SchemaStatus
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import NotFoundError
from lore.core.history.compaction import CompactionReport, compact_history
from lore.core.maintenance.checks import DERIVED_DATA, DerivedDataCheck, Problem
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.time.cache import CALENDARS, SERIES, WINDOWS
from lore.core.time.dimensions import DIMENSION
from lore.core.time.refine import RefineReport, refine_base_unit
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
            checks = with_module_checks(context, checks)
            for check in checks:
                problems += check.verify(context)
        finally:
            session.rollback()
    return CheckReport(
        ("integrity", "foreign_keys", *(check.id for check in checks)), tuple(problems)
    )


def with_module_checks(
    context: VaultContext, checks: Sequence[DerivedDataCheck]
) -> tuple[DerivedDataCheck, ...]:
    """``checks`` and the enabled modules' (``ModuleSpec.derived_checks``)."""
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    enabled = enabled_modules(context.session, context.registry)
    extra = [c for m in context.registry.modules if m.id in enabled for c in m.derived_checks]
    return (*checks, *extra)


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
        for check in with_module_checks(context, checks):
            counts[check.id] = check.rebuild(context)
        counts["consistency"] = sum(scan(context).values())
    return counts


def compact_vault_history(
    vault: OpenVault, older_than: timedelta, *, dry_run: bool = False
) -> CompactionReport:
    """Replace the vault's history older than ``older_than`` with per-entity snapshots
    (``lore.core.history.compaction``), in one write transaction; ``dry_run`` rolls it back and
    only reports. The freed pages are reused; ``optimize_vault(vacuum_database=True)`` shrinks
    the file."""
    if older_than <= timedelta(0):
        raise ValueError("older_than must be positive")
    with vault.write_sessions() as session:
        report = compact_history(session, utc_now() - older_than)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return report


@dataclass(frozen=True)
class Refinement:
    """A base-unit refinement's report and the backup taken before it (``None`` on a dry run)."""

    report: RefineReport
    backup_id: str | None


def refine_dimension_base_unit(
    manager: VaultManager,
    vault_id: str,
    dimension: str,
    factor: int,
    base_unit: dict[str, str] | None = None,
    *,
    dry_run: bool = False,
) -> Refinement:
    """Refine a dimension's base unit (``lore.core.time.refine``; ``dimension`` is its id or
    exact name) in one write transaction, after a backup of the vault (``kind = pre``, reason
    ``base-unit-refinement``); ``dry_run`` rolls it back and only reports. Consistency findings
    are recorded, never refusing (``record_only``), and scanned again."""
    from lore.core.consistency.engine import record_only, scan  # noqa: PLC0415 (import cycle)

    vault = manager.open(vault_id)
    registry = manager.module_registry
    assert registry is not None
    with vault.write_sessions() as session:
        dimension_id = _dimension_id(session, dimension)
    backup = None if dry_run else manager.backup_before(vault_id, "base-unit-refinement").id
    with vault.write_sessions() as session:
        record_only(session)
        context = VaultContext(vault, session, registry)
        report = refine_base_unit(context, dimension_id, factor, base_unit)
        scan(context)
        if dry_run:
            session.rollback()
            for cache in (CALENDARS, WINDOWS, SERIES):
                cache.forget_vault(vault.id)
        else:
            session.commit()
    return Refinement(report, backup)


def _dimension_id(session: Session, dimension: str) -> str:
    found = session.scalars(
        select(Entity.id).where(
            Entity.kind == DIMENSION,
            Entity.deleted_at.is_(None),
            or_(Entity.id == dimension, Entity.name == dimension),
        )
    ).all()
    if len(found) != 1:
        raise NotFoundError(
            f"No dimension {dimension!r}."
            if not found
            else f"Several dimensions are {dimension!r}."
        )
    return found[0]


def optimize_vault(vault: OpenVault, *, vacuum_database: bool = False) -> None:
    """``PRAGMA optimize``, then ``VACUUM`` (rewrites the whole file: needs free disk space about
    the size of the database) when asked."""
    optimize(vault.engine)
    if vacuum_database:
        vacuum(vault.engine)
