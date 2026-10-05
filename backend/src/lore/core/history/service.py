"""History reads and undo (``data-model.md`` §7).

Undo (``revert``) inverts a changeset's changes in reverse order **only if** every affected row
still equals its ``after`` snapshot (ignoring ``revision`` and ``updated_at``, which undos move on);
otherwise ``409 revert_conflict`` lists the rows. The rows get
their ``before`` values back, except that ``revision`` moves on and ``updated_at`` is now (decided
2026-10-04), so a client still holding the undone revision gets a conflict instead of silently
overwriting the undo. The undo is itself a changeset (origin ``undo``), which can be reverted
(redo). Derived data is recomputed: core's (mentions, entity search documents) here, modules'
by ``REVERT_HOOKS``.

An undo is a save like any other: the reverted state must keep every rule a normal write enforces
(link kinds, uniqueness and cardinality, validity, parent kinds/cycles/dimensions, required fields,
custom link types against their links) and must not leave references to rows it removes (e.g.
undoing a creation after the entity got children or links). Otherwise ``409 revert_conflict``
lists the ``problems`` and nothing changes.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import JSON, Table, func, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.history import recorder
from lore.core.history.models import Change, ChangeEntity, Changeset
from lore.core.history.recorder import record_bulk, recorded_tables, stored_row
from lore.core.history.schemas import (
    ChangedEntity,
    ChangeOut,
    ChangesetDetail,
    ChangesetPage,
    ChangesetSummary,
    RevertResult,
)
from lore.core.links.catalog import custom_definition
from lore.core.links.models import CustomLinkType, Link
from lore.core.links.service import LinkService
from lore.core.links.types_service import LinkTypeService
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import ModuleDisabledError, enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import LinkTypeDef
from lore.core.search.indexer import SearchIndexer
from lore.core.types import Affected
from lore.core.vaults import OpenVault

type RevertHook = Callable[[VaultContext, Sequence[Change]], None]

REVERT_HOOKS: list[RevertHook] = []
"""Called after a revert with the reverted changes, to recompute derived data (extension
point: modules re-index their search documents and time propagation (M3) appends here; core
refreshes mentions and entity search documents itself)."""


SHOWN_PROBLEMS = 3  # in the detail message; context.problems lists all


class RevertConflictError(ConflictError):
    code = "revert_conflict"
    title = "Revert conflict"


class HistoryService:
    def __init__(self, session: Session, registry: ModuleRegistry, vault: OpenVault) -> None:
        self.session = session
        self.registry = registry
        self.vault = vault

    # --- reads ----------------------------------------------------------------------------------

    def feed(self, *, cursor: str | None = None, limit: int = 50) -> ChangesetPage:
        """Recent changesets, newest first."""
        return self._page(select(Changeset), cursor, limit)

    def entity_history(
        self, entity_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> ChangesetPage:
        """Changesets touching the entity (incl. its aliases, tags and links), newest first.
        Purged entities keep their history (decided 2026-10-04)."""
        touching = (
            select(Change.changeset_id)
            .join(ChangeEntity, ChangeEntity.change_id == Change.id)
            .where(ChangeEntity.entity_id == entity_id)
        )
        entity = self.session.get(Entity, entity_id)
        if entity is not None:
            kinds = {
                k.key for k in self.registry.kinds_for(enabled_modules(self.session, self.registry))
            }
            if entity.kind not in kinds:
                raise ModuleDisabledError(f"The module of kind {entity.kind!r} is disabled.")
        elif self.session.scalar(select(func.count()).select_from(touching.subquery())) == 0:
            raise NotFoundError(f"No entity {entity_id}.")
        return self._page(select(Changeset).where(Changeset.id.in_(touching)), cursor, limit)

    def detail(self, changeset_id: str) -> ChangesetDetail:
        changeset = self._load(changeset_id)
        [summary] = self._summaries([changeset])
        changes = list(
            self.session.scalars(
                select(Change).where(Change.changeset_id == changeset.id).order_by(Change.id)
            )
        )
        owners: dict[int, list[str]] = defaultdict(list)
        for change_id, entity_id in self.session.execute(
            select(ChangeEntity.change_id, ChangeEntity.entity_id).where(
                ChangeEntity.change_id.in_([c.id for c in changes])
            )
        ):
            owners[change_id].append(entity_id)
        tables = recorded_tables(self.session)
        return ChangesetDetail(
            **summary.model_dump(),
            changes=[
                ChangeOut(
                    id=c.id,
                    table_name=c.table_name,
                    row_id=c.row_id,
                    op=c.op,  # type: ignore[arg-type]
                    before=_decoded(tables[c.table_name].table, c.before)
                    if c.table_name in tables
                    else c.before,
                    after=_decoded(tables[c.table_name].table, c.after)
                    if c.table_name in tables
                    else c.after,
                    entity_ids=sorted(owners[c.id]),
                )
                for c in changes
            ],
        )

    def _load(self, changeset_id: str) -> Changeset:
        changeset = self.session.get(Changeset, changeset_id)
        if changeset is None:
            raise NotFoundError(f"No changeset {changeset_id}.")
        return changeset

    def _page(self, statement: Any, cursor: str | None, limit: int) -> ChangesetPage:
        if cursor is not None:
            statement = statement.where(Changeset.id < cursor)
        rows = list(self.session.scalars(statement.order_by(Changeset.id.desc()).limit(limit + 1)))
        page = rows[:limit]
        return ChangesetPage(
            items=self._summaries(page),
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    def _summaries(self, changesets: Sequence[Changeset]) -> list[ChangesetSummary]:
        ids = [c.id for c in changesets]
        counts = dict(
            self.session.execute(
                select(Change.changeset_id, func.count())
                .where(Change.changeset_id.in_(ids))
                .group_by(Change.changeset_id)
            ).all()
        )
        touched: dict[str, list[str]] = defaultdict(list)
        for changeset_id, entity_id in self.session.execute(
            select(Change.changeset_id, ChangeEntity.entity_id)
            .join(ChangeEntity, ChangeEntity.change_id == Change.id)
            .where(Change.changeset_id.in_(ids))
            .distinct()
            .order_by(Change.changeset_id, ChangeEntity.entity_id)
        ):
            touched[changeset_id].append(entity_id)
        entities = self._entities({e for found in touched.values() for e in found})
        return [
            ChangesetSummary(
                id=c.id,
                created_at=c.created_at,
                updated_at=c.updated_at,
                origin=c.origin,
                summary=c.summary,
                reverts_changeset_id=c.reverts_changeset_id,
                reverted_by_changeset_id=c.reverted_by_changeset_id,
                change_count=counts.get(c.id, 0),
                entities=[entities[e] for e in touched[c.id]],
            )
            for c in changesets
        ]

    def _entities(self, ids: set[str]) -> dict[str, ChangedEntity]:
        found = {
            row.id: ChangedEntity(id=row.id, name=row.name, kind=row.kind, exists=True)
            for row in self.session.execute(
                select(Entity.id, Entity.name, Entity.kind).where(Entity.id.in_(ids))
            )
        }
        for entity_id in ids - set(found):  # purged: the last snapshot of its row
            last = self.session.scalar(
                select(Change)
                .where(Change.table_name == "entities", Change.row_id == entity_id)
                .order_by(Change.id.desc())
                .limit(1)
            )
            row = (last.before if last.after is None else last.after) if last else None
            found[entity_id] = ChangedEntity(
                id=entity_id,
                name=(row or {}).get("name"),
                kind=(row or {}).get("kind"),
                exists=False,
            )
        return found

    # --- undo -----------------------------------------------------------------------------------

    def _vet(
        self, changes: Sequence[Change], replaced: dict[int, dict[str, Any] | None]
    ) -> list[dict[str, str]]:
        """What the reverted state breaks: references to rows that are gone and the rules a
        normal save enforces (links, parents, required fields, link types against their links).
        ``replaced``: each changed row as it was before the revert."""
        problems = self._dangling_references()
        entities = EntityService(VaultContext(self.vault, self.session, self.registry))
        tables = recorded_tables(self.session)
        owners: set[str] = set()  # entities owning changed extension rows (dimensions, …)
        links = LinkService(self.session, self.registry)
        link_types = LinkTypeService(self.session, self.registry)
        for change in changes:
            if change.before is None:  # the revert deleted the row
                if change.table_name == "link_type_defs":
                    used = self.session.scalar(
                        select(func.count())
                        .select_from(Link)
                        .where(Link.link_type == change.row_id)
                    )
                    if used:
                        problems.append(
                            _problem(
                                change.table_name,
                                change.row_id,
                                f"{used} links use the link type {change.row_id!r} now.",
                            )
                        )
                continue
            found: list[str] = []
            if change.table_name not in {"entities", "links", "link_type_defs"}:
                table = tables.get(change.table_name)
                if table is not None:
                    owners.update(table.owners(change.before))
            if change.table_name == "entities":
                entity = self.session.get(Entity, change.row_id)
                found = entities.stored_problems(entity) if entity else []
            elif change.table_name == "links":
                link = self.session.get(Link, change.row_id)
                found = links.stored_problems(link) if link and link.deleted_at is None else []
            elif change.table_name == "link_type_defs":
                row = self.session.get(CustomLinkType, change.row_id)
                if row is not None:
                    after = custom_definition(row)
                    previous = replaced[change.id]
                    before = after if previous is None else self._definition(previous)
                    conflicts = link_types.conflicts(before, after)
                    found = (
                        [
                            f"Existing links break the link type {row.key!r}: "
                            + ", ".join(f"{k} ({v})" for k, v in conflicts.items())
                        ]
                        if conflicts
                        else []
                    )
            problems += [_problem(change.table_name, change.row_id, m) for m in found]
        vetted = {c.row_id for c in changes if c.table_name == "entities"}
        for owner_id in sorted(owners - vetted):
            owner = self.session.get(Entity, owner_id)
            if owner is not None:
                problems += [
                    _problem("entities", owner_id, m) for m in entities.stored_problems(owner)
                ]
        unique = {(p["table_name"], p["row_id"], p["message"]): p for p in problems}
        return list(unique.values())

    def _refresh_derived(self, context: VaultContext, changes: Sequence[Change]) -> None:
        """Core derived data of the reverted rows: mentions of every entity whose row changed,
        and the search documents of the entities whose row or aliases changed."""
        entities = EntityService(context)
        for entity_id in {c.row_id for c in changes if c.table_name == "entities"}:
            entity = self.session.get(Entity, entity_id)
            if entity is not None:
                entities.refresh_mentions(entity)
        searched = {c.row_id for c in changes if c.table_name == "entities"}
        for change in changes:
            if change.table_name == "entity_aliases":
                searched |= {row["entity_id"] for row in (change.before, change.after) if row}
        SearchIndexer(context).index_entities(searched)

    def _dangling_references(self) -> list[dict[str, str]]:
        """Foreign keys left pointing at rows the revert removed (checks are deferred until the
        commit, so they're looked up here to answer with a conflict instead of failing)."""
        connection = self.session.connection()
        problems = []
        tables = recorded_tables(self.session)
        for table, rowid, parent, _fk in connection.exec_driver_sql("PRAGMA foreign_key_check"):
            row_id = str(rowid)
            if table in tables:
                keys = [c.name for c in tables[table].table.primary_key.columns]
                row = (
                    connection.exec_driver_sql(f'SELECT * FROM "{table}" WHERE rowid = ?', (rowid,))
                    .mappings()
                    .first()
                )
                if row is not None:
                    row_id = (
                        str(row[keys[0]]) if len(keys) == 1 else json.dumps([row[k] for k in keys])
                    )
            problems.append(
                _problem(
                    table,
                    row_id,
                    f"A row of {table} added or changed later still refers to it ({parent}): "
                    "undo or delete that first.",
                )
            )
        return problems

    def _definition(self, raw: dict[str, Any]) -> LinkTypeDef:
        table = recorded_tables(self.session)["link_type_defs"].table
        decoded = _decoded(table, raw) or {}
        columns = {c.name for c in table.columns}
        return custom_definition(
            CustomLinkType(**{k: v for k, v in decoded.items() if k in columns})
        )

    def revert(self, changeset_id: str) -> RevertResult:
        changeset = self._load(changeset_id)
        if changeset.reverted_by_changeset_id is not None:
            raise ConflictError("This changeset was already undone.")
        tables = recorded_tables(self.session)
        changes = list(
            self.session.scalars(
                select(Change).where(Change.changeset_id == changeset.id).order_by(Change.id)
            )
        )
        unknown = sorted({c.table_name for c in changes if c.table_name not in tables})
        if unknown:
            raise InvalidInputError(f"Changes of {', '.join(unknown)} can't be undone.")
        recorder.write_now(self.session)  # earlier writes of this transaction stay separate
        conflicts = []
        current: dict[int, dict[str, Any] | None] = {}
        for change in changes:
            current[change.id] = stored_row(
                self.session, tables[change.table_name].table, change.row_id
            )
            if _content(current[change.id]) != _content(change.after):
                conflicts.append(
                    {"table_name": change.table_name, "row_id": change.row_id, "op": change.op}
                )
        if conflicts:
            raise RevertConflictError(
                f"{len(conflicts)} rows changed since: undo the later changes first.",
                context={"rows": conflicts},
            )

        history = recorder.context(self.session)
        history.origin, history.reverts_changeset_id = recorder.UNDO, changeset.id
        history.summary = f"Undid: {changeset.summary}"
        connection = self.session.connection()
        connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")  # until the commit
        for change in reversed(changes):
            table = tables[change.table_name].table
            now = current[change.id]
            target = None if change.before is None else _moved_on(change.before, now)
            _write_row(self.session, table, change.row_id, now, target)
            record_bulk(self.session, table, [now] if now else [], [target] if target else [])
        self.session.expire_all()
        problems = self._vet(changes, current)
        if problems:
            raise RevertConflictError(
                "Undoing this would break rules: "
                + "; ".join(p["message"] for p in problems[:SHOWN_PROBLEMS])
                + (
                    f" (and {len(problems) - SHOWN_PROBLEMS} more)"
                    if len(problems) > SHOWN_PROBLEMS
                    else ""
                ),
                context={"rows": [], "problems": problems},
            )
        undo_id = recorder.write_now(self.session)
        history.origin, history.reverts_changeset_id, history.summary = "system", None, None
        assert undo_id is not None
        changeset.reverted_by_changeset_id = undo_id
        self.session.flush()
        context = VaultContext(self.vault, self.session, self.registry)
        self._refresh_derived(context, changes)
        for hook in REVERT_HOOKS:
            hook(context, changes)
        detail = self.detail(undo_id)
        entity_ids = sorted({e for c in detail.changes for e in c.entity_ids})
        dimensions = self.session.scalars(
            select(Entity.dimension_id).where(
                Entity.id.in_(entity_ids), Entity.dimension_id.is_not(None)
            )
        )
        return RevertResult(
            changeset=detail,
            affected=Affected(
                entities=entity_ids,
                dimensions=sorted({d for d in dimensions if d is not None}),
                time_changed=False,
                search_changed=True,
            ),
        )


BOOKKEEPING = frozenset({"revision", "updated_at"})


def _content(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """A row without the bookkeeping columns that an undo itself moves on."""
    return None if row is None else {k: v for k, v in row.items() if k not in BOOKKEEPING}


def _problem(table: str, row_id: str, message: str) -> dict[str, str]:
    return {"table_name": table, "row_id": row_id, "message": message}


def _moved_on(before: dict[str, Any], now: dict[str, Any] | None) -> dict[str, Any]:
    """The ``before`` row, with ``revision`` past the current one and ``updated_at`` now."""
    target = dict(before)
    if "revision" in target:
        base = now["revision"] if now is not None else target["revision"]
        target["revision"] = int(base) + 1
    if "updated_at" in target:
        target["updated_at"] = recorder.now_key()
    return target


def _write_row(
    session: Session,
    table: Table,
    row_id: str,
    now: dict[str, Any] | None,
    target: dict[str, Any] | None,
) -> None:
    """Set the stored row to ``target`` (raw values; None deletes it)."""
    connection = session.connection()
    keys = [column.name for column in table.primary_key.columns]
    pk = dict(zip(keys, [row_id] if len(keys) == 1 else json.loads(row_id), strict=True))
    where = " AND ".join(f'"{key}" = ?' for key in keys)
    if target is None:
        connection.exec_driver_sql(f'DELETE FROM "{table.name}" WHERE {where}', tuple(pk.values()))
    elif now is None:
        columns = list(target)
        connection.exec_driver_sql(
            f'INSERT INTO "{table.name}" ({", ".join(f'"{c}"' for c in columns)}) '
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(target[c] for c in columns),
        )
    else:
        columns = [c for c in target if c not in keys]
        connection.exec_driver_sql(
            f'UPDATE "{table.name}" SET {", ".join(f'"{c}" = ?' for c in columns)} WHERE {where}',
            (*(target[c] for c in columns), *pk.values()),
        )


def _decoded(table: Table, row: dict[str, Any] | None) -> dict[str, Any] | None:
    """A raw row with its JSON columns parsed (for display)."""
    if row is None:
        return None
    result = dict(row)
    for column in table.columns:
        value = result.get(column.name)
        if isinstance(column.type, JSON) and isinstance(value, str):
            result[column.name] = json.loads(value)
    return result
