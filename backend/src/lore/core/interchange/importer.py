"""The interchange import (``interchange.md`` §4): a document's rows written into an existing
vault in one transaction, recorded as one changeset (origin ``import``, undoable) and checked by
the consistency engine like any other write.

1. The rows are brought to this app's schema: a document from an older schema goes through a
   scratch database the migrations upgrade (``rows_at_head``).
2. Ids: ``remap`` (default) gives every row whose key is an id a fresh UUIDv7, so importing twice
   gives two copies; ``keep`` keeps them. Every id-shaped string in the rows (foreign keys, slot
   anchors, rich text, ``fact:<id>`` keys…) is rewritten with the same map.
3. References (multiversal entities of a dimension export) are matched in the vault by id, else
   by kind and name; rows that need an unmatched one are left out.
4. Rows whose key the vault already has (by id, or by a unique key: a tag's name, a custom
   field's kind and key) are taken as that row when they are the same (or the table is
   ``reuse_by_key``), and are conflicts otherwise: ``fail`` (default) refuses the import with a
   report, ``overwrite`` replaces the vault's rows (after a backup).
5. Derived data (time edges and moments, search, mentions) is rebuilt for what was written.
"""

import sqlite3
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from sqlalchemy import Column, MetaData, Table, UniqueConstraint, and_, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from lore.core.db import create_vault_engine
from lore.core.db.migrate import Migrator
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError
from lore.core.history import recorder
from lore.core.interchange.export import (
    ENTITIES,
    exported_tables,
    interchange_tables,
    primary_key,
    row_id,
)
from lore.core.interchange.format import (
    DEFAULT_LIMITS,
    ID,
    ConflictMode,
    IdMode,
    InterchangeConflictError,
    InterchangeDocument,
    InterchangeModulesError,
    InterchangeNewerError,
    InvalidInterchangeError,
    Limits,
    Reference,
    codec,
    decode_row,
    encode_value,
    file_name,
    read_archive,
)
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.time.cache import CALENDARS, SERIES, WINDOWS
from lore.core.vaults.publish import OPTIONAL_REFERENCES

if TYPE_CHECKING:
    from lore.core.vaults.manager import OpenVault, VaultManager

type Rows = dict[str, list[dict[str, Any]]]

# Columns that differ between copies of the same record (left out when rows are compared).
BOOKKEEPING = frozenset({"created_at", "updated_at", "revision"})
SUPPRESSIONS = "consistency_suppressions"
_BATCH = 500
_CONFLICTS_SHOWN = 50


@dataclass
class ImportReport:
    """What an import did, by table: rows ``created``, ``updated`` (overwritten), ``reused`` (the
    vault's own, same or matched by key) and ``dropped`` (they needed a record the vault doesn't
    have, or suppressions of remapped ids); the references matched and not."""

    vault_id: str
    ids: IdMode
    scope: str
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    reused: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    references_matched: int = 0
    references_unmatched: list[Reference] = field(default_factory=list)
    files: int = 0
    entities: list[str] = field(default_factory=list)  # ids of the entities written
    changeset_id: str | None = None


# --- rows at this app's schema --------------------------------------------------------------------


def rows_at_head(
    migrator: Migrator, document: InterchangeDocument, tables: Sequence[Table], scratch: Path
) -> Rows:
    """The document's rows as SQLite stores them at this app's head (``InvalidInterchangeError``
    for rows that don't fit, ``InterchangeNewerError`` for a schema this app doesn't know)."""
    by_name = {table.name: table for table in tables}
    revision = document.schema_revision
    if revision == migrator.head():
        unknown = sorted(set(document.tables) - set(by_name))
        if unknown:
            raise InvalidInterchangeError(
                "The document has tables this app doesn't import.", context={"tables": unknown}
            )
        return {
            name: [
                decode_row(by_name[name], row, f"/tables/{name}/{i}")
                for i, row in enumerate(document.tables.get(name, []))
            ]
            for name in by_name
        }
    if not migrator.is_known(revision):
        raise InterchangeNewerError(
            f"The document's schema {revision!r} is unknown to this app (written by a newer one?).",
            context={"schema_revision": revision},
        )
    return _upgraded(migrator, document, tables, scratch)


def _upgraded(
    migrator: Migrator, document: InterchangeDocument, tables: Sequence[Table], scratch: Path
) -> Rows:
    """Rows of an older schema: written into a scratch database at their revision, upgraded by
    the migrations (which rewrite stored documents too), read back."""
    path = scratch / "upgrade.db"
    sqlite3.connect(path).close()
    migrator.upgrade(path, document.schema_revision)
    engine = create_vault_engine(path, foreign_keys=False, pool=NullPool)
    try:
        old = MetaData()
        old.reflect(bind=engine)
        current = {table.name: table for table in tables}
        with engine.begin() as connection:
            for name, rows in document.tables.items():
                table = old.tables.get(name)
                if table is None:
                    raise InvalidInterchangeError(
                        f"The document's schema has no table {name!r}.", context={"table": name}
                    )
                now = current.get(name)
                codecs: dict[str, Column[Any]] = {
                    column: now.c[column]
                    if now is not None and column in now.c
                    else table.c[column]
                    for column in (column.name for column in table.c)
                }
                decoded = [
                    decode_row(table, row, f"/tables/{name}/{i}", codecs)
                    for i, row in enumerate(rows)
                ]
                if decoded:
                    connection.execute(insert(_plain(name, list(table.c.keys()))), decoded)
    finally:
        engine.dispose()
    migrator.upgrade(path, "head", check_foreign_keys=False)
    engine = create_vault_engine(path, foreign_keys=False, pool=NullPool)
    try:
        with engine.connect() as connection:
            upgraded: Rows = {}
            for table in tables:
                order = ", ".join(f'"{name}"' for name in primary_key(table))
                result = connection.exec_driver_sql(
                    f'SELECT * FROM "{table.name}" ORDER BY {order}'
                )
                upgraded[table.name] = [dict(row) for row in result.mappings()]
            return upgraded
    finally:
        engine.dispose()


def _plain(name: str, columns: Sequence[str]) -> Table:
    """A table without types: values go to SQLite as they are (raw stored values)."""
    return Table(name, MetaData(), *(Column(column) for column in columns))


# --- the import -----------------------------------------------------------------------------------


def import_interchange(
    manager: VaultManager,
    vault_id: str,
    source: IO[bytes],
    *,
    ids: IdMode = "remap",
    on_conflict: ConflictMode = "fail",
    limits: Limits = DEFAULT_LIMITS,
) -> ImportReport:
    """Import an interchange zip (or a bare document) into an existing vault. ``overwrite``
    takes a backup first (``pre-import``)."""
    registry = manager.module_registry
    if registry is None:
        raise ValueError("an interchange import needs the module registry")
    vault = manager.open(vault_id)
    if vault.read_only:
        raise ConflictError("A read-only server can't import.")
    tables = exported_tables(registry)
    with tempfile.TemporaryDirectory(prefix="lore-import-") as scratch:
        archive = read_archive(source, Path(scratch), limits)
        rows = rows_at_head(manager.migrator, archive.document, tables, Path(scratch))
        if on_conflict == "overwrite":
            manager.backup_before(vault_id, "import")
        try:
            with vault.write_sessions() as session:
                job = _Import(
                    VaultContext(vault, session, registry),
                    document=archive.document,
                    rows=rows,
                    files=archive.files,
                    tables=tables,
                    ids=ids,
                    on_conflict=on_conflict,
                )
                report = job.run()
                session.commit()
                report.changeset_id = recorder.context(session).changeset_id
        finally:
            _forget_caches(vault)
    return report


def _forget_caches(vault: OpenVault) -> None:
    for cache in (CALENDARS, WINDOWS, SERIES):
        cache.forget_vault(vault.id)


@dataclass
class _Written:
    table: Table
    rows: list[dict[str, Any]]
    before: list[dict[str, Any]]  # the vault's rows they replace (overwrite)


class _Import:
    def __init__(
        self,
        context: VaultContext,
        *,
        document: InterchangeDocument,
        rows: Rows,
        files: Mapping[str, Path],
        tables: Sequence[Table],
        ids: IdMode,
        on_conflict: ConflictMode,
    ) -> None:
        self.context = context
        self.session: Session = context.session
        self.registry: ModuleRegistry = context.registry
        self.document = document
        self.rows = rows
        self.files = files
        self.tables = list(tables)
        self.by_name = {table.name: table for table in tables}
        self.ids = ids
        self.on_conflict = on_conflict
        self.mapping: dict[str, str] = {}
        self.report = ImportReport(context.vault.id, ids, document.scope.kind)
        self.conflicts: list[dict[str, Any]] = []
        self.conflict_count = 0
        # Rows taken as the vault's own (by table: their original ids), and those that replace
        # one (original id → the vault's row).
        self.reused: dict[str, set[str]] = {}
        self.replacing: dict[str, dict[str, dict[str, Any]]] = {}
        self.exists: dict[tuple[str, str], dict[Any, bool]] = {}  # the vault's, asked once

    def run(self) -> ImportReport:
        session = self.session
        session.execute(select(1))  # the transaction is open
        session.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
        history = recorder.context(session)
        history.origin = "import"
        self._check_modules()
        if self.ids == "remap":
            self._remap()
        self._match_references()
        self._match_keys()
        rows = {name: [self._rewrite(row) for row in table_rows if not self._is_reused(name, row)]
                for name, table_rows in self.rows.items()}  # fmt: skip
        if self.ids == "remap" and rows.get(SUPPRESSIONS):
            # Suppressions name findings by a hash of their subjects' ids, which changed.
            self.report.dropped[SUPPRESSIONS] = len(rows.pop(SUPPRESSIONS))
        rows = self._without_dangling(rows)
        written = self._plan(rows)
        if self.conflict_count and self.on_conflict == "fail":
            raise InterchangeConflictError(
                f"{self.conflict_count} record(s) of the file clash with the vault's; nothing "
                "was imported. Import with fresh ids, or overwrite.",
                context={"count": self.conflict_count, "conflicts": self.conflicts},
            )
        self._write(written)
        self._store_files(written)
        self._rebuild(written)
        entities = len(self.report.entities)
        source = self.document.source.name
        what = (
            f"“{self.document.scope.name}” from “{source}”"
            if self.document.scope.kind == "dimension"
            else f"“{source}”"
        )
        recorder.describe(session, f"Imported {what} ({entities} entities)")
        return self.report

    # --- checks -----------------------------------------------------------------------------------

    def _check_modules(self) -> None:
        """The modules whose records the document holds must be enabled here."""
        registry = self.registry
        enabled = enabled_modules(self.session, registry)
        owners = {model.__tablename__: m.id for m in registry.modules for model in m.models}  # type: ignore[attr-defined]
        kinds = {kind.key: m.id for m in registry.modules for kind in m.kinds}
        providers = {m.id for m in registry.modules if m.kind_providers}
        modules = {m.id for m in registry.modules}
        needed: set[str] = {
            owners[name] for name, rows in self.rows.items() if rows and name in owners
        }
        for entity in self.rows.get(ENTITIES, []):
            kind = str(entity["kind"])
            if kind in kinds:
                needed.add(kinds[kind])
            elif kind.startswith("custom."):
                needed |= providers
        for link in self.rows.get("links", []):
            prefix = str(link["link_type"]).partition(".")[0]
            if prefix in modules:
                needed.add(prefix)
        missing = sorted(needed - enabled)
        if missing:
            raise InterchangeModulesError(
                "The file holds records of modules this vault doesn't have enabled: "
                + ", ".join(missing)
                + ".",
                context={"modules": missing},
            )

    # --- ids --------------------------------------------------------------------------------------

    def _remap(self) -> None:
        """A fresh UUIDv7 for every row whose key is an id, in the order of the old ids (so
        lists sorted by id keep their order)."""
        old: set[str] = set()
        for table in self.tables:
            keys = primary_key(table)
            if len(keys) != 1:
                continue
            for row in self.rows.get(table.name, []):
                value = row[keys[0]]
                if isinstance(value, str) and ID.fullmatch(value):
                    old.add(value)
        for value in sorted(old):
            self.mapping[value] = str(uuid.uuid7())

    def _rewrite(self, row: Mapping[str, Any]) -> dict[str, Any]:
        mapping = self.mapping
        if not mapping:
            return dict(row)

        def swap(match: Any) -> str:
            found: str = match.group(0)
            return mapping.get(found, found)

        return {k: ID.sub(swap, v) if isinstance(v, str) else v for k, v in row.items()}

    def _match_references(self) -> None:
        """Each reference: the vault's entity with its id (multiversal, of its kind), else the one
        multiversal entity of its kind and name."""
        for reference in self.document.references:
            found = self.session.execute(
                select(Entity.kind, Entity.dimension_id).where(Entity.id == reference.id)
            ).first()
            target: str | None = None
            if found is not None and found.kind == reference.kind and found.dimension_id is None:
                target = reference.id
            else:
                named = list(
                    self.session.scalars(
                        select(Entity.id).where(
                            Entity.kind == reference.kind,
                            Entity.name == reference.name,
                            Entity.dimension_id.is_(None),
                            Entity.deleted_at.is_(None),
                        )
                    )
                )
                if len(named) == 1:
                    target = named[0]
            if target is None:
                self.report.references_unmatched.append(reference)
            else:
                self.mapping[reference.id] = target
                self.report.references_matched += 1

    def _is_reused(self, table: str, row: Mapping[str, Any]) -> bool:
        reused = self.reused.get(table)
        return bool(reused) and row_id(self.by_name[table], row) in reused  # type: ignore[operator]

    def _match_keys(self) -> None:
        """Rows whose unique key (other than the primary key) the vault already has."""
        declared = interchange_tables(self.registry)
        for table in self.tables:
            uniques = [
                [column.name for column in constraint.columns]
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            ]
            keys = primary_key(table)
            if not uniques or len(keys) != 1:
                continue
            spec = declared.get(table.name)
            for row in self.rows.get(table.name, []):
                incoming = self._rewrite(row)
                for columns in uniques:
                    existing = self._stored(table, {column: incoming[column] for column in columns})
                    if existing is None:
                        continue
                    original = row[keys[0]]
                    if (spec is not None and spec.reuse_by_key) or self._same(
                        table, incoming, existing, ignore=set(keys)
                    ):
                        self.mapping[original] = existing[keys[0]]
                        self.reused.setdefault(table.name, set()).add(original)
                        self._count(self.report.reused, table.name)
                    else:
                        self._conflict(table, incoming, "key", columns)
                        self.mapping[original] = existing[keys[0]]
                        self.replacing.setdefault(table.name, {})[existing[keys[0]]] = existing
                    break

    # --- references to what isn't there ----------------------------------------------------------

    def _without_dangling(self, rows: Rows) -> Rows:
        """Rows whose foreign keys point at neither an imported row nor one of the vault: an
        optional reference is cleared, any other such row is left out (until nothing changes)."""
        foreign = {
            table.name: [(fk.parent.name, fk.column.table.name, fk.column.name)
                         for fk in sorted(table.foreign_keys, key=lambda fk: fk.parent.name)]
            for table in self.tables
        }  # fmt: skip
        changed = True
        while changed:
            changed = False
            present = {
                (target, column): {row[column] for row in rows.get(target, [])}
                for fks in foreign.values()
                for _column, target, column in fks
            }
            for table in self.tables:
                fks = foreign[table.name]
                kept = [
                    row
                    for row in rows.get(table.name, [])
                    if self._refers(table, row, fks, present)
                ]
                dropped = len(rows.get(table.name, [])) - len(kept)
                if dropped:
                    self._count(self.report.dropped, table.name, dropped)
                    changed = True
                rows[table.name] = kept
        return rows

    def _refers(
        self,
        table: Table,
        row: dict[str, Any],
        foreign: Sequence[tuple[str, str, str]],
        present: Mapping[tuple[str, str], set[Any]],
    ) -> bool:
        """Whether every foreign key of a row points at an imported row or one of the vault's
        (an optional one that doesn't is cleared)."""
        for column, target, target_column in foreign:
            value = row[column]
            if value is None or value in present[(target, target_column)]:
                continue
            if self._in_vault(target, target_column, value):
                continue
            if (table.name, column) in OPTIONAL_REFERENCES and table.c[column].nullable:
                row[column] = None
            else:
                return False
        return True

    def _in_vault(self, table: str, column: str, value: Any) -> bool:
        known = self.exists.setdefault((table, column), {})
        if value not in known:
            plain = _plain(table, [column])
            known[value] = (
                self.session.execute(
                    select(plain.c[column]).where(plain.c[column] == value).limit(1)
                ).first()
                is not None
            )
        return known[value]

    # --- conflicts and writes --------------------------------------------------------------------

    def _plan(self, rows: Rows) -> list[_Written]:
        """Each table's rows to insert or update; same rows the vault has are skipped, others
        with a key it has are conflicts."""
        written: list[_Written] = []
        for table in self.tables:
            keys = primary_key(table)
            replacing = self.replacing.get(table.name, {})
            inserts: list[dict[str, Any]] = []
            updates: list[dict[str, Any]] = []
            before: list[dict[str, Any]] = []
            table_rows = rows.get(table.name, [])
            stored = self._stored_by_key(table, table_rows)
            for row in table_rows:
                key = tuple(row[name] for name in keys)
                existing = replacing.get(row[keys[0]]) if len(keys) == 1 else None
                if existing is None:
                    existing = stored.get(key)
                    if existing is not None:
                        if self._same(table, row, existing):
                            self._count(self.report.reused, table.name)
                            continue
                        self._conflict(table, row, "id", keys)
                if existing is None:
                    inserts.append(row)
                else:
                    updates.append(row)
                    before.append(existing)
            if inserts:
                written.append(_Written(table, inserts, []))
            if updates:
                written.append(_Written(table, updates, before))
        return written

    def _write(self, written: Sequence[_Written]) -> None:
        session = self.session
        try:
            for part in written:
                table = part.table
                plain = _plain(table.name, list(table.c.keys()))
                if not part.before:
                    for start in range(0, len(part.rows), _BATCH):
                        session.execute(insert(plain), part.rows[start : start + _BATCH])
                    recorder.record_bulk(session, table, [], part.rows)
                    self._count(self.report.created, table.name, len(part.rows))
                else:
                    keys = primary_key(table)
                    for row in part.rows:
                        session.execute(
                            update(plain)
                            .where(and_(*(plain.c[key] == row[key] for key in keys)))
                            .values(row)
                        )
                    recorder.record_bulk(session, table, part.before, part.rows)
                    self._count(self.report.updated, table.name, len(part.rows))
                if table.name == ENTITIES:
                    self.report.entities.extend(row["id"] for row in part.rows)
            session.flush()
        except IntegrityError as exc:
            raise InterchangeConflictError(
                "The file's records break a rule of the vault (a unique key: e.g. a second prime "
                "timeline of a dimension); nothing was imported.",
                context={"error": str(exc.orig)},
            ) from exc

    def _store_files(self, written: Sequence[_Written]) -> None:
        declared = interchange_tables(self.registry)
        folder = self.context.vault.info.path
        inverse = {new: old for old, new in self.mapping.items()}
        for part in written:
            spec = declared.get(part.table.name)
            if spec is None or spec.store is None:
                continue
            for row in part.rows:
                current = row_id(part.table, row)
                name = file_name(part.table.name, inverse.get(current, current))
                path = self.files.get(name)
                if path is None:
                    continue
                try:
                    spec.store(folder, row, path)
                except ValueError as exc:
                    raise InvalidInterchangeError(f"{name}: {exc}") from exc
                self.report.files += 1

    def _rebuild(self, written: Sequence[_Written]) -> None:
        """Derived data of what was written: time edges and moments (then everything anchored
        to it), search documents, mentions."""
        from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)
        from lore.core.search.indexer import SearchIndexer, contributors  # noqa: PLC0415
        from lore.core.time.dependencies import CalendarNode  # noqa: PLC0415
        from lore.core.time.propagate import TimeWriter  # noqa: PLC0415

        _forget_caches(self.context.vault)
        session = self.session
        by_table: dict[str, list[dict[str, Any]]] = {}
        for part in written:
            by_table.setdefault(part.table.name, []).extend(part.rows)
        writer = TimeWriter(self.context)
        slots = self.context.registry.slot_registry()
        for provider in slots.providers:
            table = getattr(provider.model, "__tablename__", "")
            ids = {row[provider.id_column] for row in by_table.get(table, [])}
            if not ids:
                continue
            keys = [key for key in provider.all_keys(session) if key.id in ids]
            for start in range(0, len(keys), 5000):
                loaded = slots.load(session, provider.record_type, keys[start : start + 5000])
                for key, value in sorted(
                    loaded.items(), key=lambda item: (item[0].id, item[0].slot)
                ):
                    if value.spec is not None:
                        writer.set_spec(provider.record_type, key.id, key.slot, value.spec,
                                        dimension_id=value.dimension_id)  # fmt: skip
        calendars = [row["entity_id"] for row in by_table.get("calendars", [])]
        writer.touch(*(CalendarNode(calendar) for calendar in calendars))
        writer.propagate(strict=False)
        entity_ids = sorted(set(self.report.entities))
        indexer = SearchIndexer(self.context)
        indexer.index_entities(entity_ids)
        others = sorted(
            {
                str(row[primary_key(self.by_name[name])[0]])
                for name, table_rows in by_table.items()
                if name != ENTITIES and len(primary_key(self.by_name[name])) == 1
                for row in table_rows
            }
        )
        for doc_type in contributors(self.context.registry):
            for start in range(0, len(others), _BATCH):
                indexer.index_documents(doc_type, others[start : start + _BATCH])
        entities = EntityService(self.context)
        for start in range(0, len(entity_ids), _BATCH):
            for entity in session.scalars(
                select(Entity).where(Entity.id.in_(entity_ids[start : start + _BATCH]))
            ):
                entities.refresh_mentions(entity)
        session.flush()

    # --- helpers ----------------------------------------------------------------------------------

    def _stored(self, table: Table, values: Mapping[str, Any]) -> dict[str, Any] | None:
        plain = _plain(table.name, list(table.c.keys()))
        found = (
            self.session.execute(
                select(plain).where(
                    and_(*(plain.c[name] == value for name, value in values.items()))
                )
            )
            .mappings()
            .first()
        )
        return None if found is None else dict(found)

    def _stored_by_key(
        self, table: Table, rows: Sequence[Mapping[str, Any]]
    ) -> dict[tuple[Any, ...], dict[str, Any]]:
        """The vault's rows with the same primary keys as these, by key."""
        keys = primary_key(table)
        plain = _plain(table.name, list(table.c.keys()))
        found: dict[tuple[Any, ...], dict[str, Any]] = {}
        if len(keys) == 1:
            values = [row[keys[0]] for row in rows]
            for start in range(0, len(values), _BATCH):
                for stored in self.session.execute(
                    select(plain).where(plain.c[keys[0]].in_(values[start : start + _BATCH]))
                ).mappings():
                    found[(stored[keys[0]],)] = dict(stored)
            return found
        for row in rows:
            stored_row = self._stored(table, {key: row[key] for key in keys})
            if stored_row is not None:
                found[tuple(row[key] for key in keys)] = stored_row
        return found

    def _same(
        self,
        table: Table,
        row: Mapping[str, Any],
        stored: Mapping[str, Any],
        ignore: set[str] | None = None,
    ) -> bool:
        """Whether two rows hold the same record (compared as documents, so a JSON ``null``
        stored as text equals SQL NULL), timestamps and revision aside."""
        skipped = BOOKKEEPING | (ignore or set())
        for name in (column.name for column in table.c):
            if name in skipped:
                continue
            kind = codec(table.c[name])
            if encode_value(kind, row[name]) != encode_value(kind, stored[name]):
                return False
        return True

    def _conflict(
        self, table: Table, row: Mapping[str, Any], reason: str, columns: Sequence[str]
    ) -> None:
        self.conflict_count += 1
        if self.on_conflict == "fail" and len(self.conflicts) < _CONFLICTS_SHOWN:
            item: dict[str, Any] = {
                "table": table.name,
                "id": row_id(table, row),
                "reason": reason,
                "columns": list(columns),
            }
            if "name" in row:
                item["name"] = row["name"]
            self.conflicts.append(item)

    @staticmethod
    def _count(counter: dict[str, int], table: str, n: int = 1) -> None:
        counter[table] = counter.get(table, 0) + n
