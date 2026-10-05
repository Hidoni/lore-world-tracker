"""The derived-data checkers (``persistence-and-migrations.md`` §2): each verifies one kind of
derived data against its sources and can rebuild it from them.

``lore vault check`` runs every checker in ``DERIVED_DATA`` and ``lore vault reindex`` runs
every rebuild. Later issues add theirs to the tuple (time propagation, dependencies, resolved
times).
"""

from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import exc, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.modules.spec import VaultContext
from lore.core.richtext.mentions import mention_rows
from lore.core.richtext.models import Mention
from lore.core.search.documents import SearchDocument
from lore.core.search.indexer import BATCH, SearchIndexer, contributors, index_is_current
from lore.core.search.models import ENTITY_DOC, SearchDoc

FTS_TABLES = ("search_fts", "search_trigram")


@dataclass(frozen=True)
class Problem:
    """Something wrong in a vault: the check that found it, a stable code and a message."""

    check: str
    code: str
    message: str


@dataclass(frozen=True)
class DerivedDataCheck:
    """Derived data that can be verified (``verify`` yields problems; it may read only) and
    rebuilt (``rebuild`` returns how many ``unit`` it rebuilt)."""

    id: str
    description: str
    verify: Callable[[VaultContext], Iterator[Problem]]
    rebuild: Callable[[VaultContext], int]
    unit: str


def _entity_batches(session: Session) -> Iterator[list[Entity]]:
    last = ""
    while True:
        entities = list(
            session.scalars(select(Entity).where(Entity.id > last).order_by(Entity.id).limit(BATCH))
        )
        if not entities:
            return
        yield entities
        last = entities[-1].id


# --- search -----------------------------------------------------------------------------------


def _row_values(row: SearchDoc) -> dict[str, Any]:
    return {name: getattr(row, name) for name in SearchDocument.__dataclass_fields__} | {
        "kind": row.kind
    }


def _compare_documents(
    doc_type: str,
    expected: dict[str, dict[str, Any]],
    stored: dict[str, SearchDoc],
) -> Iterator[Problem]:
    for doc_id in sorted(expected.keys() - stored.keys()):
        yield Problem(
            "search", "search_document_missing", f"{doc_type} {doc_id} is missing from the index"
        )
    for doc_id in sorted(expected.keys() & stored.keys()):
        if _row_values(stored[doc_id]) != expected[doc_id]:
            yield Problem(
                "search", "search_document_stale", f"{doc_type} {doc_id} is indexed out of date"
            )
    for doc_id in sorted(stored.keys() - expected.keys()):
        yield Problem(
            "search",
            "search_document_orphaned",
            f"{doc_type} {doc_id} is indexed but no longer exists",
        )


def _stored(session: Session, doc_type: str, doc_ids: list[str] | None) -> dict[str, SearchDoc]:
    query = select(SearchDoc).where(SearchDoc.doc_type == doc_type)
    if doc_ids is not None:
        query = query.where(SearchDoc.doc_id.in_(doc_ids))
    return {row.doc_id: row for row in session.scalars(query)}


def verify_search(context: VaultContext) -> Iterator[Problem]:
    """``search_docs`` against the entities and the module contributors, then each FTS index
    against ``search_docs`` (FTS5's ``integrity-check``, which needs a writable connection: it
    is skipped for vaults opened read-only)."""
    session = context.session
    if not index_is_current(session):
        yield Problem(
            "search",
            "search_index_outdated",
            "the index was built by another index version (or never)",
        )
    indexer = SearchIndexer(context)
    for entities in _entity_batches(session):
        expected = {
            document.doc_id: asdict(document) | {"kind": entity.kind}
            for entity, document in zip(entities, indexer.entity_documents(entities), strict=True)
        }
        stored = _stored(session, ENTITY_DOC, [entity.id for entity in entities])
        yield from _compare_documents(ENTITY_DOC, expected, stored)
    orphans = session.scalars(
        select(SearchDoc.doc_id)
        .where(SearchDoc.doc_type == ENTITY_DOC, SearchDoc.doc_id.not_in(select(Entity.id)))
        .order_by(SearchDoc.doc_id)
    )
    for doc_id in orphans:
        yield Problem(
            "search", "search_document_orphaned", f"entity {doc_id} is indexed but doesn't exist"
        )
    known = contributors(context.registry)
    for doc_type, contributor in known.items():
        expected = {
            document.doc_id: asdict(document) | {"kind": doc_type}
            for document in contributor.documents(context, None)
        }
        yield from _compare_documents(doc_type, expected, _stored(session, doc_type, None))
    unknown = session.scalars(
        select(SearchDoc.doc_type)
        .where(SearchDoc.doc_type.not_in([ENTITY_DOC, *known]))
        .distinct()
        .order_by(SearchDoc.doc_type)
    )
    for doc_type in unknown:
        yield Problem(
            "search",
            "search_document_orphaned",
            f"documents of type {doc_type} are indexed but no module contributes them",
        )
    if context.vault.read_only:
        return
    for table in FTS_TABLES:
        try:
            with session.begin_nested():
                session.connection().exec_driver_sql(
                    f"INSERT INTO {table}({table}, rank) VALUES ('integrity-check', 1)"
                )
        except exc.DatabaseError as error:
            yield Problem(
                "search",
                "search_fts_corrupt",
                f"the full-text index {table} doesn't match search_docs ({error.orig})",
            )


def rebuild_search(context: VaultContext) -> int:
    return SearchIndexer(context).reindex()


# --- mentions ---------------------------------------------------------------------------------


def verify_mentions(context: VaultContext) -> Iterator[Problem]:
    """``mentions`` against the bodies and rich-text fields they are extracted from. Entities of
    disabled modules are skipped (their mentions are kept as they are)."""
    session = context.session
    entities_service = EntityService(context)
    for entities in _entity_batches(session):
        stored: dict[str, dict[str, tuple[int, int, int]]] = {e.id: {} for e in entities}
        for row in session.scalars(
            select(Mention).where(Mention.source_entity_id.in_(list(stored)))
        ):
            stored[row.source_entity_id][row.target_entity_id] = (
                row.count_public,
                row.count_spoiler,
                row.count_private,
            )
        for entity in entities:
            counts = entities_service.mention_counts(entity)
            if counts is None:
                continue
            expected = {
                target: (c.public, c.spoiler, c.private)
                for target, c in mention_rows(session, entity.id, counts).items()
            }
            if expected != stored[entity.id]:
                yield Problem(
                    "mentions",
                    "mentions_stale",
                    f"the mentions of entity {entity.id} don't match its text",
                )


def rebuild_mentions(context: VaultContext) -> int:
    """Refresh every entity's mentions; returns the number of entities."""
    entities_service = EntityService(context)
    count = 0
    for entities in _entity_batches(context.session):
        for entity in entities:
            entities_service.refresh_mentions(entity)
        count += len(entities)
    return count


SEARCH = DerivedDataCheck(
    "search", "search index vs. entities and module documents", verify_search, rebuild_search,
    "documents",
)  # fmt: skip
MENTIONS = DerivedDataCheck(
    "mentions", "mentions vs. bodies and rich-text fields", verify_mentions, rebuild_mentions,
    "entities",
)  # fmt: skip

# Every derived-data checker, in the order they run (rebuilds too).
DERIVED_DATA: tuple[DerivedDataCheck, ...] = (SEARCH, MENTIONS)
