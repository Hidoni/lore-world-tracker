"""Test helpers for history: snapshot every recorded table and check that a write produced exactly
one changeset whose changes are the difference (``data-model.md`` §7)."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine

from lore.core.vaults import VaultManager

type Snapshot = dict[tuple[str, str], dict[str, Any]]


def _engine(app: FastAPI, vault_id: str) -> Engine:
    manager: VaultManager = app.state.vaults
    return manager.open(vault_id).engine


def recorded_table_keys(app: FastAPI, vault_id: str) -> dict[str, list[str]]:
    manager: VaultManager = app.state.vaults
    tables = manager.open(vault_id).history_tables
    return {t.name: [c.name for c in t.table.primary_key.columns] for t in tables if not t.derived}


def snapshot(app: FastAPI, vault_id: str) -> Snapshot:
    """Every row of every recorded table, raw, keyed by (table, row id as history stores it)."""
    rows: Snapshot = {}
    with _engine(app, vault_id).connect() as connection:
        for table, keys in recorded_table_keys(app, vault_id).items():
            for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"').mappings():
                row_id = str(row[keys[0]]) if len(keys) == 1 else json.dumps([row[k] for k in keys])
                rows[(table, row_id)] = dict(row)
    return rows


def changesets(app: FastAPI, vault_id: str) -> list[dict[str, Any]]:
    with _engine(app, vault_id).connect() as connection:
        return [
            dict(r)
            for r in connection.exec_driver_sql("SELECT * FROM changesets ORDER BY id").mappings()
        ]


def changes_of(app: FastAPI, vault_id: str, changeset_id: str) -> list[dict[str, Any]]:
    with _engine(app, vault_id).connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT * FROM changes WHERE changeset_id = ? ORDER BY id", (changeset_id,)
        ).mappings()
        return [
            {
                **r,
                "before": json.loads(r["before"]) if r["before"] else None,
                "after": json.loads(r["after"]) if r["after"] else None,
            }
            for r in rows
        ]


@dataclass
class Recorded:
    changeset: dict[str, Any] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def one_changeset(app: FastAPI, vault_id: str) -> Iterator[Recorded]:
    """Assert the block wrote exactly one new changeset covering every touched row."""
    before_rows, before_sets = snapshot(app, vault_id), changesets(app, vault_id)
    recorded = Recorded()
    yield recorded
    after_rows, after_sets = snapshot(app, vault_id), changesets(app, vault_id)
    assert len(after_sets) == len(before_sets) + 1, "expected exactly one new changeset"
    recorded.changeset = after_sets[-1]
    recorded.changes = changes_of(app, vault_id, recorded.changeset["id"])
    expected = {
        key: (before_rows.get(key), after_rows.get(key))
        for key in before_rows.keys() | after_rows.keys()
        if before_rows.get(key) != after_rows.get(key)
    }
    actual = {(c["table_name"], c["row_id"]): (c["before"], c["after"]) for c in recorded.changes}
    assert actual == expected


def no_changeset(app: FastAPI, vault_id: str, action: Callable[[], Any]) -> Any:
    before_rows, count = snapshot(app, vault_id), len(changesets(app, vault_id))
    result = action()
    assert len(changesets(app, vault_id)) == count
    assert snapshot(app, vault_id) == before_rows
    return result


def without_bookkeeping(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """A raw row without ``revision`` and ``updated_at`` (which move on after an undo)."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in {"revision", "updated_at"}}
