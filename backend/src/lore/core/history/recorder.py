"""History capture (ADR-0010, ``data-model.md`` §7): one transaction = one changeset.

``install(factory, tables)`` adds session hooks to a vault's session factory:

- ``before_flush`` snapshots the stored row of every modified or deleted object of a recorded
  table, ``after_flush`` snapshots the row after the flush (inserts too). Snapshots are full rows
  as SQLite stores them (raw values: JSON as text, sortable keys and timestamps as their keys), so
  a revert writes back exactly what was there.
- Within the transaction the first ``before`` and the last ``after`` per row are kept. Code that
  writes with Core statements must call ``record_bulk``.
- ``before_commit`` writes the net changes (rows whose ``before`` equals ``after`` are dropped) as
  one changeset with ``change_entities``, or merges them into the previous changeset (below). A
  transaction without changes writes nothing.

**Merging** (decided 2026-10-04): consecutive saves of one entity by the same client within
``MERGE_WINDOW``, with nothing recorded in between, are merged into the previous changeset, so an
editing session (autosave) is one history entry and one undo. Both changesets must be plain edits
of the same single entity: no entity row inserted or deleted, no trash or restore, no undo.
"""

import copy
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Table, delete, event, insert, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import instance_state

from lore.core.db.types import utc_now
from lore.core.history.models import Change, ChangeEntity, Changeset
from lore.core.history.tables import HistoryTable, Row

MERGE_WINDOW = timedelta(minutes=2)
ENTITY_TABLE = "entities"
UNDO = "undo"

_TABLES = "lore_history_tables"
_PENDING = "lore_history_pending"
_CONTEXT = "lore_history_context"
_DISABLED = "lore_history_disabled"

type RowKey = tuple[str, str]  # (table, row id)


@dataclass
class HistoryContext:
    """Who writes: ``origin`` (``ui``, ``api``, ``cli``, ``system``, ``undo``, …), the request id
    and an optional summary set by the service (otherwise generated from the changes)."""

    origin: str = "system"
    request_id: str | None = None
    summary: str | None = None
    reverts_changeset_id: str | None = None
    changeset_id: str | None = None  # set when the changeset is written


@dataclass
class _Pending:
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    table: str
    row_id: str


@dataclass
class _Net:
    changes: list[_Pending] = field(default_factory=list)


def install(factory: sessionmaker[Session], tables: Iterable[HistoryTable]) -> None:
    recorded = {t.name: t for t in tables if not t.derived}
    factory.kw.setdefault("info", {})[_TABLES] = recorded
    event.listen(factory, "before_flush", _before_flush)
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "before_commit", _before_commit)
    event.listen(factory, "after_rollback", _after_rollback)


def context(session: Session) -> HistoryContext:
    """The session's history context (created on first use)."""
    current = session.info.get(_CONTEXT)
    if current is None:
        current = session.info[_CONTEXT] = HistoryContext()
    return current


def describe(session: Session, summary: str) -> None:
    """Set the summary of the changeset this transaction writes."""
    context(session).summary = summary


@contextmanager
def discarded(session: Session) -> Iterator[None]:
    """Changes made inside are rolled back by the caller (a SAVEPOINT dry run, e.g. a calendar
    proposal's preview): afterwards, history's pending changes are what they were before."""
    saved = copy.deepcopy(session.info.get(_PENDING))
    try:
        yield
    finally:
        if saved is None:
            session.info.pop(_PENDING, None)
        else:
            session.info[_PENDING] = saved


def record_bulk(
    session: Session,
    table: Table,
    rows_before: Sequence[Row],
    rows_after: Sequence[Row],
) -> None:
    """Record rows changed with Core statements (raw stored values, full rows, matched by
    primary key; a row only in ``rows_before`` was deleted, only in ``rows_after`` inserted)."""
    keys = [column.name for column in table.primary_key.columns]
    pending = _pending(session)
    befores = {_row_id(keys, row): dict(row) for row in rows_before}
    afters = {_row_id(keys, row): dict(row) for row in rows_after}
    for row_id in [*befores, *(k for k in afters if k not in befores)]:
        key = (table.name, row_id)
        if key not in pending:
            pending[key] = _Pending(befores.get(row_id), None, table.name, row_id)
        pending[key].after = afters.get(row_id)


def stored_row(session: Session, table: Table, row_id: str) -> dict[str, Any] | None:
    """The row as SQLite stores it (raw values), or None."""
    keys = [column.name for column in table.primary_key.columns]
    values = _pk_values(keys, row_id)
    where = " AND ".join(f'"{key}" = ?' for key in keys)
    result = session.connection().exec_driver_sql(
        f'SELECT * FROM "{table.name}" WHERE {where}', tuple(values)
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


def recorded_tables(session: Session) -> Mapping[str, HistoryTable]:
    tables: Mapping[str, HistoryTable] = session.info.get(_TABLES, {})
    return tables


# --- row ids --------------------------------------------------------------------------------------


def _row_id(keys: Sequence[str], row: Row) -> str:
    if len(keys) == 1:
        return str(row[keys[0]])
    return json.dumps([row[key] for key in keys])


def _pk_values(keys: Sequence[str], row_id: str) -> list[Any]:
    return [row_id] if len(keys) == 1 else list(json.loads(row_id))


# --- hooks ----------------------------------------------------------------------------------------


def _pending(session: Session) -> dict[RowKey, _Pending]:
    pending = session.info.get(_PENDING)
    if pending is None:
        pending = session.info[_PENDING] = {}
    return pending


def _object_key(session: Session, obj: object) -> tuple[HistoryTable, str] | None:
    state = instance_state(obj)
    table = recorded_tables(session).get(getattr(state.mapper.local_table, "name", ""))
    if table is None:
        return None
    # Not state.identity: a new object only gets it after after_flush.
    identity = state.mapper.primary_key_from_instance(obj)
    if any(value is None for value in identity):
        return None
    keys = [column.name for column in table.table.primary_key.columns]
    return table, _row_id(keys, dict(zip(keys, identity, strict=True)))


def _before_flush(session: Session, _context: object, _instances: object) -> None:
    if session.info.get(_DISABLED):
        return
    pending = _pending(session)
    dirty = set(session.dirty)  # each access walks the identity map: once per flush
    for obj in [*dirty, *session.deleted]:
        if obj in dirty and not session.is_modified(obj):
            continue
        found = _object_key(session, obj)
        if found is None:
            continue
        table, row_id = found
        key = (table.name, row_id)
        if key not in pending:
            pending[key] = _Pending(
                stored_row(session, table.table, row_id), None, table.name, row_id
            )


def _after_flush(session: Session, _context: object) -> None:
    if session.info.get(_DISABLED):
        return
    pending = _pending(session)
    new, deleted = set(session.new), set(session.deleted)
    for obj in [*new, *session.dirty, *deleted]:
        found = _object_key(session, obj)
        if found is None:
            continue
        table, row_id = found
        key = (table.name, row_id)
        if key not in pending:
            if obj not in new:
                continue  # an unmodified dirty object
            pending[key] = _Pending(None, None, table.name, row_id)
        pending[key].after = None if obj in deleted else stored_row(session, table.table, row_id)


def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)


def _before_commit(session: Session) -> None:
    if not session.info.get(_DISABLED):
        write_now(session)


def write_now(session: Session) -> str | None:
    """Write the transaction's changes as a changeset now (normally done at commit) and return
    its id; None when nothing changed. Later writes in the transaction start a new one."""
    session.flush()  # the commit's own flush runs after the before_commit hook
    pending = session.info.pop(_PENDING, None)
    changes = [p for p in (pending or {}).values() if p.before != p.after]
    if not changes:
        return None
    session.info[_DISABLED] = True  # writing history must not record itself
    try:
        _write(session, changes)
        session.flush()
    finally:
        session.info.pop(_DISABLED, None)
    return context(session).changeset_id


# --- writing --------------------------------------------------------------------------------------


def _op(change: _Pending) -> str:
    if change.before is None:
        return "insert"
    return "delete" if change.after is None else "update"


def _owners(session: Session, change: _Pending) -> list[str]:
    table = recorded_tables(session)[change.table]
    owners = [*table.owners(change.before or {}), *table.owners(change.after or {})]
    return list(dict.fromkeys(owners))


def _is_edit(changes: Sequence[_Pending]) -> bool:
    """Plain edits only: no entity row inserted or deleted, no trash or restore."""
    for change in changes:
        if change.table != ENTITY_TABLE:
            continue
        if change.before is None or change.after is None:
            return False
        if change.before.get("deleted_at") != change.after.get("deleted_at"):
            return False
    return True


def _write(session: Session, changes: list[_Pending]) -> None:
    ctx = context(session)
    owners = {(c.table, c.row_id): _owners(session, c) for c in changes}
    entities = {owner for found in owners.values() for owner in found}
    previous = _merge_target(session, ctx, changes, entities)
    now = utc_now()
    if previous is not None:
        changes = _combine(session, previous, changes)
        if not changes:  # back to where the previous changeset started
            session.delete(previous)
            return
        previous.updated_at = now
        previous.summary = ctx.summary or summarize(session, changes)
        changeset = previous
        session.execute(delete(Change).where(Change.changeset_id == previous.id))
        session.flush()
    else:
        changeset = Changeset(
            created_at=now,
            updated_at=now,
            origin=ctx.origin,
            summary=ctx.summary or summarize(session, changes),
            request_id=ctx.request_id,
            reverts_changeset_id=ctx.reverts_changeset_id,
        )
        session.add(changeset)
        session.flush()
    ctx.changeset_id = changeset.id
    values = [
        {
            "changeset_id": changeset.id,
            "table_name": change.table,
            "row_id": change.row_id,
            "op": _op(change),
            "before": change.before,
            "after": change.after,
        }
        for change in changes
    ]
    ids = session.scalars(
        insert(Change).returning(Change.id, sort_by_parameter_order=True), values
    ).all()
    owners_of = [
        {"change_id": change_id, "entity_id": entity_id}
        for change_id, change in zip(ids, changes, strict=True)
        for entity_id in _owners(session, change)
    ]
    if owners_of:
        session.execute(insert(ChangeEntity), owners_of)


def _merge_target(
    session: Session, ctx: HistoryContext, changes: list[_Pending], entities: set[str]
) -> Changeset | None:
    if (
        ctx.origin == UNDO
        or ctx.reverts_changeset_id
        or len(entities) != 1
        or not _is_edit(changes)
    ):
        return None
    previous = session.scalar(select(Changeset).order_by(Changeset.id.desc()).limit(1))
    if (
        previous is None
        or previous.origin != ctx.origin
        or previous.reverts_changeset_id is not None
        or previous.reverted_by_changeset_id is not None
        or utc_now() - previous.updated_at.astimezone(UTC) > MERGE_WINDOW
    ):
        return None
    earlier = [
        _Pending(c.before, c.after, c.table_name, c.row_id)
        for c in session.scalars(
            select(Change).where(Change.changeset_id == previous.id).order_by(Change.id)
        )
    ]
    owners = {owner for c in earlier for owner in _owners(session, c)}
    if owners != entities or not _is_edit(earlier):
        return None
    return previous


def _combine(session: Session, previous: Changeset, changes: list[_Pending]) -> list[_Pending]:
    """The previous changeset's changes followed by ``changes``, as net changes."""
    combined: dict[RowKey, _Pending] = {}
    earlier = session.scalars(
        select(Change).where(Change.changeset_id == previous.id).order_by(Change.id)
    )
    for row in earlier:
        combined[(row.table_name, row.row_id)] = _Pending(
            row.before, row.after, row.table_name, row.row_id
        )
    for change in changes:
        key = (change.table, change.row_id)
        if key in combined:
            combined[key].after = change.after
        else:
            combined[key] = change
    return [c for c in combined.values() if c.before != c.after]


# --- summaries ------------------------------------------------------------------------------------


def _quoted(row: Mapping[str, Any] | None) -> str:
    name = (row or {}).get("name")
    return f"“{name}”" if name else "an entity"


def _entity_summary(change: _Pending) -> str:
    before, after = change.before, change.after
    if before is None:
        return f"Created {(after or {}).get('kind', 'entity')} {_quoted(after)}"
    if after is None:
        return f"Purged {_quoted(before)}"
    verbs = {(True, False): "Trashed", (False, True): "Restored"}
    trashed = (before.get("deleted_at") is None, after.get("deleted_at") is None)
    return f"{verbs.get(trashed, 'Edited')} {_quoted(after)}"


def _links_summary(changes: Sequence[_Pending]) -> str:
    ops = {_op(c) for c in changes}
    trashed = all(
        c.before and c.after and c.after.get("deleted_at") and not c.before.get("deleted_at")
        for c in changes
    )
    verb = "Added" if ops == {"insert"} else "Removed" if trashed else "Changed"
    return f"{verb} {len(changes)} link{'s' if len(changes) != 1 else ''}"


def summarize(session: Session, changes: Sequence[_Pending]) -> str:
    """A default summary from the changes (English, for the history UI)."""
    entity_changes = [c for c in changes if c.table == ENTITY_TABLE]
    tables = {c.table for c in changes}
    if len(entity_changes) == 1:
        summary = _entity_summary(entity_changes[0])
    elif entity_changes:
        summary = f"Changed {len(entity_changes)} entities"
    elif tables <= {"links"}:
        summary = _links_summary(changes)
    elif tables <= {"link_type_defs"}:
        summary = "Changed link types"
    else:
        owners = {owner for change in changes for owner in _owners(session, change)}
        name = None
        if len(owners) == 1:
            name = (
                session.connection()
                .exec_driver_sql('SELECT name FROM "entities" WHERE id = ?', (next(iter(owners)),))
                .scalar()
            )
        summary = f"Edited “{name}”" if name else f"{len(changes)} changes"
    return summary


def now_key() -> str:
    """``updated_at`` as stored (fixed-width ISO-8601 UTC, ``UTCDateTime``)."""
    return datetime.now(UTC).isoformat(timespec="microseconds")
