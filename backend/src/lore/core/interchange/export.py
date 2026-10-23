"""The interchange export (``interchange.md`` §3): the vault's authored tables, or one dimension's
part of them, as a document in a zip with the files its rows have.

Everything runs on a copy of the database (``snapshot``) opened in a staging folder, like a
published snapshot (``lore.core.vaults.publish``), so the vault is never written:

1. A dimension export first freezes the time points of its records that are anchored to
   records it doesn't hold (another dimension's, through correspondences) to their resolved
   moments (``TimeWriter.freeze``, as before a purge).
2. A readers' export runs the publish sanitizer: what ``READER`` hides is gone.
3. The tables are read, and a dimension export keeps its part (``select_dimension``).
"""

import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from sqlalchemy import Table, or_, select
from sqlalchemy.orm import Session

from lore import __version__
from lore.core.db import snapshot
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.interchange.format import (
    FORMAT,
    FORMAT_VERSION,
    ID,
    Audience,
    encode_row,
    file_name,
    sha256_of,
    write_archive,
)
from lore.core.interchange.spec import CORE_TABLES, InterchangeTable
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.time.dimensions import DIMENSION
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.vaults.format import DATABASE_NAME, write_manifest
from lore.core.vaults.publish import OPTIONAL_REFERENCES, PublishContext, sanitize

if TYPE_CHECKING:
    from lore.core.vaults.manager import VaultInfo, VaultManager

ENTITIES = "entities"
# Tables a dimension export leaves out: suppressions name findings by a hash of their subjects,
# which can't tell which dimension they belong to.
VAULT_ONLY = frozenset({"consistency_suppressions"})

type Rows = dict[str, list[dict[str, Any]]]  # table → raw stored rows


@dataclass(frozen=True)
class ExportInfo:
    entities: int
    rows: int
    files: int
    references: int


def exported_tables(registry: ModuleRegistry) -> list[Table]:
    """Every authored table (what history records), parents before children."""
    recorded = {table.name: table.table for table in registry.history_tables() if not table.derived}
    tables = list(recorded.values())
    order = {table.name: i for i, table in enumerate(tables[0].metadata.sorted_tables)}
    return sorted(tables, key=lambda table: order.get(table.name, len(order)))


def interchange_tables(registry: ModuleRegistry) -> dict[str, InterchangeTable]:
    """Core's and every module's ``InterchangeTable`` declarations, by table."""
    declared = (*CORE_TABLES, *(t for m in registry.modules for t in m.interchange_tables))
    return {table.table: table for table in declared}


def primary_key(table: Table) -> list[str]:
    return [column.name for column in table.primary_key.columns]


def row_id(table: Table, row: Mapping[str, Any]) -> str:
    """A row's id: its primary key, joined with ``/`` when it has several columns."""
    return "/".join(str(row[name]) for name in primary_key(table))


def dump_tables(session: Session, tables: Iterable[Table]) -> Rows:
    """Every row of these tables as SQLite stores it, in primary key order (a table the
    database doesn't have, of a module without migrations, has none)."""
    connection = session.connection()
    present = {name for (name,) in connection.exec_driver_sql("SELECT name FROM sqlite_master")}
    rows: Rows = {}
    for table in tables:
        if table.name not in present:
            rows[table.name] = []
            continue
        order = ", ".join(f'"{name}"' for name in primary_key(table))
        result = connection.exec_driver_sql(f'SELECT * FROM "{table.name}" ORDER BY {order}')
        rows[table.name] = [dict(row) for row in result.mappings()]
    return rows


# --- one dimension ------------------------------------------------------------------------------


@dataclass
class Selection:
    rows: Rows
    references: list[dict[str, Any]]  # entity rows the kept rows refer to without holding them


def _foreign_keys(table: Table) -> list[tuple[str, str, str]]:
    return sorted(
        (fk.parent.name, fk.column.table.name, fk.column.name) for fk in table.foreign_keys
    )


def ids_in(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every id-shaped string anywhere in these rows (JSON documents included)."""
    found: set[str] = set()
    for row in rows:
        for value in row.values():
            if isinstance(value, str):
                found.update(ID.findall(value))
    return found


def select_dimension(tables: Sequence[Table], rows: Rows, dimension_id: str) -> Selection:
    """The rows of one dimension (``interchange.md`` §3.2): its entities (itself included),
    and every other row that refers to one of the kept rows and to nothing else than kept rows
    and multiversal entities, until nothing changes. Optional references to rows not kept are
    cleared (``OPTIONAL_REFERENCES``). Rows of tables without foreign keys come along when a
    kept row names them (tags, media items); definitions (tables whose key isn't an id: custom
    link types, custom kinds) always do. Multiversal entities named anywhere in the kept rows
    become ``references``."""
    return _Closure(tables, rows, dimension_id).selection()


class _Closure:
    """``select_dimension``'s fixed point."""

    def __init__(self, tables: Sequence[Table], rows: Rows, dimension_id: str) -> None:
        self.tables = tables
        self.rows = rows
        entities = rows[ENTITIES]
        self.inside = {e["id"] for e in entities if dimension_id in (e["id"], e["dimension_id"])}
        self.multiversal = {
            e["id"] for e in entities if e["dimension_id"] is None and e["kind"] != DIMENSION
        }
        self.foreign = {table.name: _foreign_keys(table) for table in tables}
        self.standalone = {name for name, fks in self.foreign.items() if not fks}
        self.kept: Rows = {ENTITIES: [dict(e) for e in entities if e["id"] in self.inside]}
        for table in tables:
            if table.name != ENTITIES and table.name not in self.standalone:
                self.kept[table.name] = [dict(row) for row in rows.get(table.name, [])]

    def _values(self, table: str, column: str) -> set[Any]:
        source = self.rows.get(table, []) if table in self.standalone else self.kept[table]
        return {row[column] for row in source}

    def _keeps(self, table: Table, row: dict[str, Any], targets: dict[Any, set[Any]]) -> bool:
        """Whether a row stays: it refers to a kept row (not only to standalone ones) and to
        nothing missing (an optional reference to something missing is cleared)."""
        touches = False
        for column, target, target_column in self.foreign[table.name]:
            value = row[column]
            if value is None or (target == ENTITIES and value in self.multiversal):
                continue
            if target == ENTITIES and value in self.inside:
                touches = True
            elif target != ENTITIES and value in targets[(target, target_column)]:
                touches = touches or target not in self.standalone
            elif (table.name, column) in OPTIONAL_REFERENCES and table.c[column].nullable:
                row[column] = None
            else:
                return False
        return touches

    def selection(self) -> Selection:
        changed = True
        while changed:
            changed = False
            for table in self.tables:
                name = table.name
                if name == ENTITIES or name in self.standalone:
                    continue
                targets = {
                    (t, c): self._values(t, c) for _col, t, c in self.foreign[name] if t != ENTITIES
                }
                still = [row for row in self.kept[name] if self._keeps(table, row, targets)]
                if len(still) != len(self.kept[name]):
                    self.kept[name] = still
                    changed = True
        named = ids_in(row for table_rows in self.kept.values() for row in table_rows)
        for table in self.tables:
            if table.name in self.standalone:
                self.kept[table.name] = self._standalone(table, named)
        references = [
            e for e in self.rows[ENTITIES] if e["id"] in self.multiversal and e["id"] in named
        ]
        return Selection({table.name: self.kept[table.name] for table in self.tables}, references)

    def _standalone(self, table: Table, named: set[str]) -> list[dict[str, Any]]:
        rows = self.rows.get(table.name, [])
        keys = primary_key(table)
        if table.name in VAULT_ONLY:
            return []
        if len(keys) == 1 and _is_id_column(rows, keys[0]):
            return [dict(row) for row in rows if row[keys[0]] in named]
        return [dict(row) for row in rows]


def _is_id_column(rows: list[dict[str, Any]], column: str) -> bool:
    """Whether a table's key holds ids (an empty table: assumed to)."""
    return all(isinstance(row[column], str) and ID.fullmatch(row[column]) for row in rows)


def _freeze_outside(context: VaultContext, selection: Selection, rows: Rows) -> int:
    """Freeze the kept records' time points anchored to records the export doesn't hold (or
    to calendars and dimensions it doesn't) at their resolved moments. Records of multiversal
    entities stay: they travel as references."""
    from lore.core.time.models import TimeDependency  # noqa: PLC0415
    from lore.core.time.propagate import TimeWriter  # noqa: PLC0415

    slots = context.registry.slot_registry()
    multiversal = {
        e["id"] for e in rows[ENTITIES] if e["dimension_id"] is None and e["kind"] != DIMENSION
    }
    kept_entities = {e["id"] for e in selection.rows[ENTITIES]}
    records: dict[str, set[str]] = {}
    for provider in slots.providers:
        table = getattr(provider.model, "__tablename__", "")
        ids = {row[provider.id_column] for row in selection.rows.get(table, [])}
        if provider.entity_column is not None and provider.entity_column == provider.id_column:
            ids |= multiversal
        records[provider.record_type] = ids

    def holds(kind: str, type_: str | None, id_: str | None, calendar: str | None) -> bool:
        if kind == "slot":
            return id_ in records.get(type_ or "", set())
        if kind == "calendar":
            return calendar == ABSOLUTE_CALENDAR_ID or calendar in kept_entities
        if kind == "dimension":
            return id_ in kept_entities
        return True  # the correspondences: an anchor crossing them names a slot too

    from lore.core.time.dependencies import SlotNode  # noqa: PLC0415

    outside: set[SlotNode] = set()
    for edge in context.session.scalars(select(TimeDependency)):
        if edge.dependent_id not in records.get(edge.dependent_type, set()):
            continue
        if not holds(edge.target_kind, edge.target_type, edge.target_id, edge.target_calendar_id):
            outside.add(SlotNode(edge.dependent_type, edge.dependent_id, edge.dependent_slot))
    frozen = TimeWriter(context).freeze(outside)
    context.session.flush()
    return frozen


def find_dimension(session: Session, dimension: str) -> Entity:
    """A dimension by id or exact name (``NotFoundError``; ``InvalidInputError`` when several
    share the name)."""
    found = list(
        session.scalars(
            select(Entity).where(
                Entity.kind == DIMENSION, or_(Entity.id == dimension, Entity.name == dimension)
            )
        )
    )
    if not found:
        raise NotFoundError(f"No dimension {dimension!r}.")
    if len(found) > 1:
        raise InvalidInputError(f"Several dimensions are named {dimension!r}; give its id.")
    return found[0]


# --- the export --------------------------------------------------------------------------------


@dataclass
class _Read:
    rows: Rows
    scope: dict[str, Any]
    modules: list[str]
    dimension_id: str | None


def _read(
    manager: VaultManager, info: VaultInfo, folder: Path, audience: Audience, dimension: str | None
) -> _Read:
    """Copy the database into ``folder`` (a vault folder in a staging data directory), prepare
    the copy (steps 1 and 2 of the module docstring) and read its tables."""
    from lore.core.consistency.engine import record_only  # noqa: PLC0415 (import cycle)
    from lore.core.vaults.manager import VaultManager  # noqa: PLC0415 (import cycle)

    registry = manager.module_registry
    assert registry is not None
    tables = exported_tables(registry)
    snapshot(info.database_path, folder / DATABASE_NAME)
    write_manifest(folder, info.manifest)
    staged = VaultManager(folder.parent.parent, module_registry=registry)
    try:
        opened = staged.open(info.id)
        with opened.write_sessions() as session:
            try:
                context = VaultContext(opened, session, registry)
                record_only(session)
                session.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
                read = _Read(
                    {}, {"kind": "vault"}, sorted(enabled_modules(session, registry)), None
                )
                if dimension is not None:
                    found = find_dimension(session, dimension)
                    read.dimension_id = found.id
                    read.scope = {"kind": "dimension", "dimension_id": found.id, "name": found.name}
                    rows = dump_tables(session, tables)
                    _freeze_outside(context, select_dimension(tables, rows, found.id), rows)
                if audience == "readers":
                    sanitize(PublishContext(context, info.path, folder))
                    session.flush()
                read.rows = dump_tables(session, tables)
                return read
            finally:
                session.rollback()
    finally:
        staged.close()


def _files(
    registry: ModuleRegistry, selection: Selection, folder: Path
) -> tuple[dict[str, Path], dict[str, str]]:
    """The files of the selected rows (in the vault folder ``folder``), by archive name, and
    their checksums."""
    by_name = {table.name: table for table in exported_tables(registry)}
    files: dict[str, Path] = {}
    checksums: dict[str, str] = {}
    for name, spec in sorted(interchange_tables(registry).items()):
        if spec.file is None or name not in by_name:
            continue
        for row in selection.rows.get(name, []):
            path = spec.file(folder, row)
            if path is not None and path.is_file():
                archive_name = file_name(name, row_id(by_name[name], row))
                files[archive_name] = path
                checksums[archive_name] = sha256_of(path)
    return files, checksums


def export_interchange(
    manager: VaultManager,
    vault_id: str,
    out: IO[bytes],
    *,
    audience: Audience = "author",
    dimension: str | None = None,
) -> ExportInfo:
    """Write the vault (or one ``dimension``: its id or exact name) as an interchange zip to
    ``out``. ``audience="readers"`` leaves out everything readers can't see; ``author`` holds
    everything, private content included."""
    registry = manager.module_registry
    if registry is None:
        raise ValueError("an interchange export needs the module registry")
    info = manager.get(vault_id)
    if info.manifest.published:
        raise ConflictError("Export the vault itself, not a published snapshot of it.")
    tables = exported_tables(registry)
    by_name = {table.name: table for table in tables}
    with tempfile.TemporaryDirectory(prefix="lore-interchange-") as scratch:
        folder = Path(scratch) / "vaults" / info.folder
        folder.mkdir(parents=True)
        read = _read(manager, info, folder, audience, dimension)
        selection = Selection(read.rows, [])
        if read.dimension_id is not None:
            if not any(e["id"] == read.dimension_id for e in read.rows[ENTITIES]):
                raise NotFoundError(f"No dimension {dimension!r} readers can see.")
            selection = select_dimension(tables, read.rows, read.dimension_id)
        files, checksums = _files(
            registry, selection, folder if audience == "readers" else info.path
        )
        document = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "schema_revision": manager.migrator.head(),
            "exported_at": datetime.now(UTC).isoformat(),
            "source": {"vault_id": info.id, "name": info.name},
            "audience": audience,
            "scope": read.scope,
            "modules": read.modules,
            "references": [
                {"id": e["id"], "kind": e["kind"], "name": e["name"]} for e in selection.references
            ],
            "tables": {
                name: [encode_row(by_name[name], row) for row in table_rows]
                for name, table_rows in selection.rows.items()
            },
            "files": checksums,
        }
        write_archive(out, document, files)
    return ExportInfo(
        entities=len(selection.rows[ENTITIES]),
        rows=sum(len(table_rows) for table_rows in selection.rows.values()),
        files=len(files),
        references=len(selection.references),
    )
