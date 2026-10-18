"""History compaction (``data-model.md`` §7, Retention; ``lore vault compact-history``).

History older than a cutoff is replaced by **per-entity snapshots**: one changeset (origin
``compaction``) per entity holding the net change of each of its rows over the compacted
period (the first ``before``, the last ``after``; rows that ended where they started are
dropped). A row with several owners (a link) goes to the snapshot of its smallest owner id and
keeps all its owners in ``change_entities``, so it stays in both entities' history. Rows without
an owner (tags, link types, suppressions) share one vault-wide snapshot.

Only a **prefix** of history is compacted: the changesets before the oldest one saved since the
cutoff (a changeset's ``updated_at`` moves when saves merge into it, and changesets are ordered
by id). Snapshots get ids that sort before every kept changeset, so the feed's order and a later
compaction's per-row order stay right. Later undos that reverted a compacted changeset lose
their ``reverts_changeset_id`` (the changeset is gone). Snapshots can't be undone. Only history
tables are written: no world row changes, so nothing is recorded and no rule runs.
"""

import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, true, update
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.history.models import Change, ChangeEntity, Changeset
from lore.core.history.recorder import ENTITY_TABLE

COMPACTION = "compaction"  # the origin of snapshot changesets
VAULT_WIDE = ""  # the snapshot group of rows without an owner
CHUNK = 500  # ids per IN list


@dataclass(frozen=True)
class CompactionReport:
    changesets: int  # compacted (deleted)
    changes: int  # their changes
    snapshots: int  # snapshot changesets written
    snapshot_changes: int


@dataclass
class _Net:
    table_name: str
    row_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    owners: set[str] = field(default_factory=set)


@dataclass
class _Group:
    created_at: datetime
    updated_at: datetime
    rows: list[_Net] = field(default_factory=list)


def compact_history(session: Session, cutoff: datetime) -> CompactionReport:
    """Replace the history older than ``cutoff`` with per-entity snapshots (in ``session``'s
    transaction, which should be a write transaction: ``OpenVault.write_sessions``)."""
    kept_from = session.scalar(select(func.min(Changeset.id)).where(Changeset.updated_at >= cutoff))
    prefix = true() if kept_from is None else Changeset.id < kept_from
    compacted = select(Changeset.id).where(prefix).scalar_subquery()
    changesets = {c.id: c for c in session.scalars(select(Changeset).where(prefix))}
    if not changesets:
        return CompactionReport(0, 0, 0, 0)

    owners: dict[int, set[str]] = defaultdict(set)
    for change_id, entity_id in session.execute(
        select(ChangeEntity.change_id, ChangeEntity.entity_id)
        .join(Change, Change.id == ChangeEntity.change_id)
        .where(Change.changeset_id.in_(compacted))
    ):
        owners[change_id].add(entity_id)
    net: dict[tuple[str, str], _Net] = {}
    times: dict[tuple[str, str], tuple[datetime, datetime]] = {}
    count = 0
    for change in session.scalars(
        select(Change)
        .where(Change.changeset_id.in_(compacted))
        .order_by(Change.changeset_id, Change.id)
        .execution_options(yield_per=1000)
    ):
        count += 1
        key = (change.table_name, change.row_id)
        changeset = changesets[change.changeset_id]
        if key in net:
            net[key].after = change.after
            times[key] = (times[key][0], changeset.updated_at)
        else:
            net[key] = _Net(change.table_name, change.row_id, change.before, change.after)
            times[key] = (changeset.created_at, changeset.updated_at)
        net[key].owners |= owners[change.id]

    groups: dict[str, _Group] = {}
    for key, row in net.items():
        if row.before == row.after:
            continue
        owner = min(row.owners) if row.owners else VAULT_WIDE
        first, last = times[key]
        group = groups.setdefault(owner, _Group(first, last))
        group.created_at, group.updated_at = (
            min(group.created_at, first),
            max(group.updated_at, last),
        )
        group.rows.append(row)

    session.execute(delete(ChangeEntity).where(ChangeEntity.change_id.in_(
        select(Change.id).where(Change.changeset_id.in_(compacted))
    )))  # fmt: skip
    session.execute(delete(Change).where(Change.changeset_id.in_(compacted)))
    session.execute(delete(Changeset).where(prefix))
    if kept_from is not None:
        session.execute(
            update(Changeset)
            .where(Changeset.reverts_changeset_id < kept_from)
            .values(reverts_changeset_id=None)
        )
    ceiling = None if kept_from is None else _milliseconds(kept_from) - 1
    names = _names(session, set(groups) - {VAULT_WIDE})
    written = 0
    # oldest first, so the snapshot ids sort like the history they replace
    for owner, group in sorted(groups.items(), key=lambda item: item[1].updated_at):
        changeset_id = _snapshot_id(group.updated_at, ceiling)
        session.execute(
            insert(Changeset).values(
                id=changeset_id,
                created_at=group.created_at,
                updated_at=group.updated_at,
                origin=COMPACTION,
                summary=_summary(owner, group, names, cutoff),
                request_id=None,
                reverts_changeset_id=None,
                reverted_by_changeset_id=None,
            )
        )
        ids = session.scalars(
            insert(Change).returning(Change.id, sort_by_parameter_order=True),
            [
                {
                    "changeset_id": changeset_id,
                    "table_name": row.table_name,
                    "row_id": row.row_id,
                    "op": _op(row),
                    "before": row.before,
                    "after": row.after,
                }
                for row in group.rows
            ],
        ).all()
        links = [
            {"change_id": change_id, "entity_id": entity_id}
            for change_id, row in zip(ids, group.rows, strict=True)
            for entity_id in sorted(row.owners)
        ]
        if links:
            session.execute(insert(ChangeEntity), links)
        written += len(group.rows)
    session.expire_all()
    return CompactionReport(len(changesets), count, len(groups), written)


def _op(row: _Net) -> str:
    if row.before is None:
        return "insert"
    return "delete" if row.after is None else "update"


def _milliseconds(changeset_id: str) -> int:
    """The Unix time in milliseconds a UUIDv7 id starts with."""
    return uuid.UUID(changeset_id).int >> 80


def _snapshot_id(at: datetime, ceiling: int | None) -> str:
    """A UUIDv7 for ``at`` (at most ``ceiling`` milliseconds, so it sorts before the kept
    history)."""
    milliseconds = int(at.timestamp() * 1000)
    if ceiling is not None:
        milliseconds = min(milliseconds, ceiling)
    random = int.from_bytes(os.urandom(10))
    value = (milliseconds & (2**48 - 1)) << 80 | random & ~(0xF << 76 | 0x3 << 62)
    return str(uuid.UUID(int=value | 0x7 << 76 | 0x2 << 62))


def _names(session: Session, entity_ids: set[str]) -> dict[str, str]:
    """Entity names as they are now (``entities`` rows; purged ones are looked up from the
    snapshot rows by ``_summary``)."""
    ordered, found = sorted(entity_ids), dict[str, str]()
    for start in range(0, len(ordered), CHUNK):
        chunk = ordered[start : start + CHUNK]
        for entity_id, name in session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(chunk))
        ):
            found[entity_id] = name
    return found


def _summary(owner: str, group: _Group, names: dict[str, str], cutoff: datetime) -> str:
    day = cutoff.astimezone(UTC).date().isoformat()
    if owner == VAULT_WIDE:
        return f"Vault-wide changes before {day} (compacted)"
    name = names.get(owner)
    if name is None:
        rows = [r for r in group.rows if r.table_name == ENTITY_TABLE and r.row_id == owner]
        if rows:
            name = (rows[0].after or rows[0].before or {}).get("name")
    who = f"“{name}”" if name else "an entity"
    return f"Changes of {who} before {day} (compacted)"
