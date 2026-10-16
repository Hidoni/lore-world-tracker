"""Published snapshots (``visibility-and-sharing.md`` §4, R-SHR-2): a copy of a vault in which
private data physically doesn't exist, ready for a read-only server.

``publish_vault`` copies the database into a staging folder under the output data directory,
opens the copy with its own ``VaultManager`` and runs the **sanitizer** on it:

1. Time points anchored to what readers can't see are frozen to their resolved moments
   (``ReaderTimes``, as reader responses show them), before anything is deleted.
2. Everything ``READER`` hides is deleted: entities (private, trashed, in hidden dimensions or
   timelines, of kinds no enabled module offers), private aliases, links and facts, facts of
   fields readers can't see, and module rows by their ``VisibilityFilter``\\ s.
3. References left dangling are repaired generically from the database's own foreign keys: a
   few optional references are cleared (a hidden parent, source event…), any other row pointing
   at a deleted record is deleted, until nothing changes.
4. Bodies, rich-text fields and per-timeline notes are filtered for readers; fields readers
   can't see are dropped with their visibility overrides; tags no entity uses are dropped.
5. History, consistency findings and suppressions, and proposals are dropped.
6. Module ``publish_contributors`` run (media files of the items readers see, …).
7. Derived data is rebuilt (``reindex_vault``: search, mentions, time rows…), the file is
   ``VACUUM``\\ ed with ``journal_mode=DELETE``.

Then ``vault.json`` gets ``"published": true`` and the source vault's id, the **leak gate**
(``leak_problems``) checks the result, and the folder replaces any earlier snapshot of the vault
in ``<out>/vaults/``. A failed gate deletes the output.
"""

import shutil
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, MetaData, Table, delete, exists, not_, or_, select, update
from sqlalchemy.orm import Session

from lore.core.db import snapshot
from lore.core.errors import ConflictError, LoreError
from lore.core.modules.spec import VaultContext
from lore.core.vaults.format import DATABASE_NAME, LOCK_NAME, write_manifest
from lore.core.visibility import READER

if TYPE_CHECKING:
    from lore.core.vaults.manager import VaultInfo, VaultManager

# References that become NULL when what they point at is gone (the row stays, as readers see
# it): a hidden parent, the event that caused a fact, a map pin's child map… Every other
# reference to a deleted record deletes the row.
OPTIONAL_REFERENCES = frozenset(
    {
        ("entities", "parent_id"),
        ("entity_facts", "source_event_id"),
        ("dimensions", "default_calendar_id"),
        ("maps_pins", "child_map_id"),
        ("worldline_segments", "arrival_event_id"),
        ("worldline_segments", "departure_event_id"),
    }
)
# Tables a snapshot never holds: history, consistency bookkeeping, pending proposals.
DROPPED_TABLES = (
    "change_entities",
    "changes",
    "changesets",
    "consistency_finding_entities",
    "consistency_findings",
    "consistency_suppressions",
    "proposals",
)


class PublishError(LoreError):
    code = "publish_failed"
    status = 409
    title = "Publish failed"


@dataclass(frozen=True)
class PublishContext:
    """What a module's ``publish_contributors`` get: the snapshot's session (``context``), the
    source vault's folder (its files) and the snapshot's folder."""

    context: VaultContext
    source: Path
    target: Path


def publish_vault(manager: VaultManager, vault_id: str, out: Path) -> VaultInfo:
    """Publish the vault into the data directory ``out`` (``<out>/vaults/<folder>/``), replacing
    an earlier snapshot of it there. Returns the snapshot's ``VaultInfo``."""
    from lore.core.vaults.manager import VaultManager  # noqa: PLC0415 (import cycle)

    info = manager.get(vault_id)
    if info.manifest.published:
        raise ConflictError("A published snapshot can't be published again.")
    out.mkdir(parents=True, exist_ok=True)
    staging = out / f".publishing-{uuid.uuid7()}"
    folder = staging / "vaults" / info.folder
    folder.mkdir(parents=True)
    try:
        snapshot(info.database_path, folder / DATABASE_NAME)
        write_manifest(folder, info.manifest)
        staged = VaultManager(staging, module_registry=manager.module_registry)
        try:
            opened = staged.open(info.id)
            registry = staged.module_registry
            assert registry is not None
            with opened.write_sessions.begin() as session:
                _sanitize(PublishContext(VaultContext(opened, session, registry), info.path,
                                         folder))  # fmt: skip
            from lore.core.maintenance.service import reindex_vault  # noqa: PLC0415

            reindex_vault(opened, registry)
            with opened.write_sessions.begin() as session:
                _drop_bookkeeping(session)
        finally:
            staged.close()
        (folder / LOCK_NAME).unlink(missing_ok=True)
        _compact(folder / DATABASE_NAME)
        write_manifest(
            folder,
            info.manifest.model_copy(
                update={
                    "published": True,
                    "source_vault_id": info.id,
                    "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            ),
        )
        problems = leak_problems(folder)
        if problems:
            raise PublishError(
                "The snapshot still holds private data; nothing was published.",
                context={"problems": problems[:20]},
            )
        target = out / "vaults" / info.folder
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            replaced = out / f".replaced-{uuid.uuid7()}"
            target.rename(replaced)
            shutil.rmtree(replaced, ignore_errors=True)
        folder.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    from lore.core.vaults.manager import VaultManager as Manager  # noqa: PLC0415

    return Manager(out, read_only=True).get(info.id)


# --- the sanitizer -------------------------------------------------------------------------------


def _sanitize(publish: PublishContext) -> None:
    from lore.core.consistency.engine import record_only  # noqa: PLC0415 (import cycle)

    context = publish.context
    session = context.session
    record_only(session)
    session.execute(select(1))  # the transaction is open
    session.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
    _freeze_time_points(context)
    _delete_hidden(context)
    _repair_references(session)
    _filter_content(context)
    for module in context.registry.modules:
        for contributor in module.publish_contributors:
            if callable(contributor):
                contributor(publish)
    _repair_references(session)
    _drop_bookkeeping(session)


def _drop_bookkeeping(session: Session) -> None:
    for name in DROPPED_TABLES:
        session.execute(_table(session, name).delete())


def _tables(session: Session) -> MetaData:
    metadata = session.info.get("lore_publish_metadata")
    if metadata is None:
        metadata = MetaData()
        metadata.reflect(bind=session.connection())
        session.info["lore_publish_metadata"] = metadata
    assert isinstance(metadata, MetaData)
    return metadata


def _table(session: Session, name: str) -> Table:
    return _tables(session).tables[name]


# --- 1. time points ------------------------------------------------------------------------------


def _freeze_time_points(context: VaultContext) -> None:
    """Every stored time point anchored to a record readers can't see becomes the absolute
    moment readers are shown (``ReaderTimes``); a recurrence rule in a hidden calendar is
    dropped (readers see no rule; the series keeps its stored occurrences' moments)."""
    from lore.core.entities.models import Entity  # noqa: PLC0415
    from lore.core.time.events import reader_end, reader_rule  # noqa: PLC0415
    from lore.core.time.models import Event  # noqa: PLC0415
    from lore.core.time.redact import ReaderTimes  # noqa: PLC0415
    from lore.core.time.specs import dump_spec  # noqa: PLC0415

    session = context.session
    times = ReaderTimes(context, READER)
    dimensions = dict(session.execute(select(Entity.id, Entity.dimension_id)).all())
    for event in session.scalars(select(Event)):
        dimension = dimensions.get(event.entity_id)
        if dimension is None:
            continue
        start = times.point(dump_spec(event.start_spec), dimension, owner=event.entity_id)
        if start is not None and start != dump_spec(event.start_spec):
            event.start_spec = start
        end = reader_end(times, event, dimension)
        if end is not None and end != dump_spec(event.end_spec):
            event.end_spec = end
        if event.recurrence is not None:
            rule = reader_rule(times, event, dimension)
            if rule != event.recurrence:
                event.recurrence = rule
    _freeze_time_point_fields(context, times)
    for table, columns, dimension_of in _point_columns(context):
        row: Any
        for row in session.scalars(select(table)):
            dimension = dimension_of(row, dimensions)
            for column in columns:
                document = getattr(row, column)
                if document is None:
                    continue
                stored = dump_spec(document)
                shown = times.point(stored, dimension, owner=getattr(row, "id", None))
                if shown != stored:
                    setattr(row, column, shown)
    session.flush()


def _freeze_time_point_fields(context: VaultContext, times: Any) -> None:
    """``time_point`` field values as readers get them (``EntityService.shown_fields``)."""
    from lore.core.entities.models import Entity  # noqa: PLC0415
    from lore.core.entities.service import EntityService  # noqa: PLC0415
    from lore.core.facts.models import EntityFact  # noqa: PLC0415

    service = EntityService(context, READER)
    for entity in context.session.scalars(select(Entity)):
        kind = service.kinds.get(entity.kind)
        if kind is None or not entity.fields:
            continue
        active = service.kind_fields(kind).active
        fields = dict(entity.fields)
        for key, value in entity.fields.items():
            if key not in active or active[key].type != "time_point" or value is None:
                continue
            values = value if isinstance(value, list) else [value]
            shown = [times.point(v, entity.dimension_id) for v in values]
            shown = [v for v in shown if v is not None]
            if isinstance(value, list):
                fields[key] = shown
            elif shown:
                fields[key] = shown[0]
            else:
                del fields[key]
        if fields != entity.fields:
            entity.fields = fields
    session = context.session
    timelines = _timeline_dimensions(session)
    facts = session.execute(
        select(EntityFact, Entity).join(Entity, Entity.id == EntityFact.entity_id)
    ).all()
    for fact, entity in facts:
        kind = service.kinds.get(entity.kind)
        field = None if kind is None else service.kind_fields(kind).active.get(fact.field_key)
        if field is None or field.type != "time_point" or fact.value is None:
            continue
        dimension = timelines.get(fact.timeline_id)
        if isinstance(fact.value, list):
            shown_list = [times.point(v, dimension, owner=fact.id) for v in fact.value]
            value: Any = [v for v in shown_list if v is not None]
        else:
            value = times.point(fact.value, dimension, owner=fact.id)
        if value != fact.value:
            fact.value = value
    session.flush()


def _point_columns(
    context: VaultContext,
) -> Iterator[tuple[type, tuple[str, ...], Callable[[Any, dict[str, str | None]], str | None]]]:
    """The tables with stored time points, their point columns, and each row's dimension."""
    from lore.core.facts.models import EntityFact  # noqa: PLC0415
    from lore.core.links.models import Link  # noqa: PLC0415
    from lore.core.time.fields import FACT_PREFIX  # noqa: PLC0415
    from lore.core.time.models import (  # noqa: PLC0415
        CorrespondencePoint,
        Dimension,
        EntityTimeField,
        Timeline,
        WorldlineSegment,
    )

    def of_timeline(row: Any, _dimensions: dict[str, str | None]) -> str | None:
        return _timeline_dimensions(context.session).get(row.timeline_id)

    def of_slot(row: Any, dimensions: dict[str, str | None]) -> str | None:
        if row.field_key.startswith(FACT_PREFIX):
            fact = context.session.get(EntityFact, row.field_key.removeprefix(FACT_PREFIX))
            return None if fact is None else of_timeline(fact, dimensions)
        return dimensions.get(row.entity_id)

    yield EntityTimeField, ("spec",), of_slot
    yield EntityFact, ("valid_from_spec", "valid_to_spec"), of_timeline
    yield Link, ("valid_from_spec", "valid_to_spec"), of_timeline
    yield Timeline, ("branch_point_spec",), lambda row, _d: row.dimension_id
    yield Dimension, ("present_spec",), lambda row, _d: row.entity_id
    yield WorldlineSegment, ("start_spec", "end_spec"), lambda row, _d: row.dimension_id
    yield CorrespondencePoint, ("a_spec",), lambda row, _d: row.a_dimension_id
    yield CorrespondencePoint, ("b_spec",), lambda row, _d: row.b_dimension_id
    for module in context.registry.modules:
        for model in module.models:
            names = tuple(
                name for name in ("valid_from_spec", "valid_to_spec") if hasattr(model, name)
            )
            if names and hasattr(model, "timeline_id"):
                yield model, names, of_timeline


def _timeline_dimensions(session: Session) -> dict[str, str]:
    from lore.core.time.models import Timeline  # noqa: PLC0415

    cached = session.info.get("lore_publish_timelines")
    if cached is None:
        cached = dict(session.execute(select(Timeline.entity_id, Timeline.dimension_id)).all())
        session.info["lore_publish_timelines"] = cached
    assert isinstance(cached, dict)
    return cached


# --- 2. what readers can't see -------------------------------------------------------------------


def _delete_hidden(context: VaultContext) -> None:
    from lore.core.entities.models import Entity, EntityAlias  # noqa: PLC0415
    from lore.core.facts.models import EntityFact  # noqa: PLC0415
    from lore.core.links.models import Link  # noqa: PLC0415
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415

    session = context.session
    enabled = enabled_modules(session, context.registry)
    kinds = context.registry.vault_kind_keys(session, enabled)
    visible = set(
        session.scalars(
            select(Entity.id).where(*READER.entities(Entity), Entity.kind.in_(sorted(kinds)))
        )
    )
    session.execute(delete(Entity).where(Entity.id.not_in(_listed(session, visible))))
    session.execute(delete(EntityAlias).where(not_(*READER.rows(EntityAlias))))
    session.execute(delete(Link).where(or_(Link.deleted_at.is_not(None), not_(_all(
        READER.links(Link))))))  # fmt: skip
    session.execute(
        delete(EntityFact).where(
            or_(
                EntityFact.deleted_at.is_not(None),
                not_(_all(READER.rows(EntityFact))),
                not_(_all(READER.entity_ref(EntityFact.timeline_id))),
            )
        )
    )
    _delete_hidden_field_facts(context)
    present = _tables(session).tables
    for module in context.registry.modules:
        if module.id not in enabled:
            continue
        for spec in module.visibility_filters:
            model: Any = spec.model
            if model.__tablename__ not in present:
                continue
            hidden = not_(_all(READER.module_rows(spec)))
            if hasattr(model, "deleted_at"):
                hidden = or_(hidden, model.deleted_at.is_not(None))
            session.execute(delete(model).where(hidden))
    session.flush()
    # Any other table: its private rows and its trash.
    for table in _tables(session).sorted_tables:
        if "visibility" in table.c:
            session.execute(delete(table).where(table.c.visibility == "private"))
        if "deleted_at" in table.c:
            session.execute(delete(table).where(table.c.deleted_at.is_not(None)))


def _listed(session: Session, ids: set[str]) -> Any:
    """``ids`` as a temporary table's rows (too many for an ``IN`` list in a large vault)."""
    connection = session.connection()
    connection.exec_driver_sql("CREATE TEMP TABLE IF NOT EXISTS publish_kept (id TEXT PRIMARY KEY)")
    connection.exec_driver_sql("DELETE FROM publish_kept")
    if ids:
        connection.exec_driver_sql(
            "INSERT INTO publish_kept (id) VALUES (?)", [(i,) for i in sorted(ids)]
        )
    kept = Table("publish_kept", MetaData(), Column("id"), prefixes=["TEMP"])
    return select(kept.c.id)


def _all(conditions: list[Any]) -> Any:
    from sqlalchemy import and_, true  # noqa: PLC0415

    return and_(true(), *conditions)


def _delete_hidden_field_facts(context: VaultContext) -> None:
    """Facts of fields readers can't see on their entity (by the field's default or the
    entity's override), and of fields the entity's kind doesn't offer."""
    from lore.core.entities.models import Entity  # noqa: PLC0415
    from lore.core.entities.service import EntityService  # noqa: PLC0415
    from lore.core.facts.models import EntityFact  # noqa: PLC0415
    from lore.core.facts.schemas import EXISTS, NAME  # noqa: PLC0415

    session = context.session
    entities = EntityService(context, READER)
    rows = session.execute(
        select(EntityFact.id, EntityFact.field_key, Entity)
        .join(Entity, Entity.id == EntityFact.entity_id)
        .where(EntityFact.field_key.not_in([EXISTS, NAME]))
    ).all()
    hidden: list[str] = []
    for fact_id, key, entity in rows:
        kind = entities.kinds.get(entity.kind)
        field = None if kind is None else entities.kind_fields(kind).active.get(key)
        if field is None or not READER.shows(READER.field_level(field, entity.field_visibility)):
            hidden.append(fact_id)
    for start in range(0, len(hidden), 500):
        session.execute(delete(EntityFact).where(EntityFact.id.in_(hidden[start : start + 500])))


# --- 3. dangling references ----------------------------------------------------------------------


def _repair_references(session: Session) -> None:
    """Clear optional references to deleted rows and delete rows with any other dangling
    reference, until nothing changes (deleting a row can orphan others)."""
    session.flush()
    metadata = _tables(session)
    while True:
        changed = 0
        for table in metadata.sorted_tables:
            for fk in table.foreign_keys:
                column = fk.parent
                # Aliased: a self-reference (entities.dimension_id) must not correlate.
                target = fk.column.table.alias().c[fk.column.name]
                dangling = (column.is_not(None), ~exists().where(target == column))
                if (table.name, column.name) in OPTIONAL_REFERENCES and column.nullable:
                    statement: Any = update(table).where(*dangling).values({column.name: None})
                else:
                    statement = delete(table).where(*dangling)
                result: Any = session.execute(statement)
                changed += result.rowcount or 0
        if not changed:
            return


# --- 4. content -----------------------------------------------------------------------------------


def _filter_content(context: VaultContext) -> None:
    """Bodies, fields (readers' fields only, rich text filtered) and per-timeline notes as
    readers get them; tags no entity uses go."""
    from lore.core.entities.models import Entity, EntityTag, Tag  # noqa: PLC0415
    from lore.core.entities.service import EntityService  # noqa: PLC0415
    from lore.core.time.models import EntityTimelineNote  # noqa: PLC0415

    session = context.session
    service = EntityService(context, READER)
    for entity in session.scalars(select(Entity)):
        kind = service.kinds.get(entity.kind)
        active = {} if kind is None else service.kind_fields(kind).active
        body = READER.filter_richtext(session, entity.body, service.richtext)
        fields, overrides = READER.fields(
            session, active, entity.fields, entity.field_visibility, service.richtext
        )
        if body != entity.body:
            entity.body = body
        if fields != entity.fields:
            entity.fields = fields
        if overrides != entity.field_visibility:
            entity.field_visibility = overrides
    for note in session.scalars(select(EntityTimelineNote)):
        body = READER.filter_richtext(session, note.body, service.richtext)
        if body is not None and body != note.body:
            note.body = body
    session.flush()
    session.execute(delete(Tag).where(~exists().where(EntityTag.tag_id == Tag.id)))


# --- finishing -----------------------------------------------------------------------------------


def _compact(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("VACUUM")
        connection.execute("PRAGMA journal_mode=DELETE")
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).unlink(missing_ok=True)


def leak_problems(folder: Path) -> list[str]:
    """The publish gate (``visibility-and-sharing.md`` §4, step 5): what a snapshot must not
    hold. Rows marked private in any table with a ``visibility`` column, private blocks in any
    stored document, history and consistency bookkeeping, and SQLite side files. Empty when the
    snapshot is clean."""
    problems: list[str] = []
    database = folder / DATABASE_NAME
    for suffix in ("-wal", "-shm", "-journal"):
        if database.with_name(database.name + suffix).exists():
            problems.append(f"side file {DATABASE_NAME}{suffix}")
    uri = f"file:{database}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for name in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')]
            if name in DROPPED_TABLES:
                count = connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                if count:
                    problems.append(f"{name}: {count} rows")
                continue
            if "visibility" in columns:
                count = connection.execute(
                    f"SELECT count(*) FROM \"{name}\" WHERE visibility = 'private'"
                ).fetchone()[0]
                if count:
                    problems.append(f"{name}: {count} private rows")
            for column in columns:
                count = connection.execute(
                    f'SELECT count(*) FROM "{name}" WHERE typeof("{column}") = \'text\' '
                    f"AND \"{column}\" LIKE '%visibilityBlock%' "
                    f'AND "{column}" LIKE \'%"level":%"private"%\''
                ).fetchone()[0]
                if count:
                    problems.append(f"{name}.{column}: {count} private blocks")
    return problems
