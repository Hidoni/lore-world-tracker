"""Keeps ``search_docs`` (and through its triggers the FTS tables) up to date, inside the writing
transaction (``data-model.md`` §9).

- The entity service indexes an entity on every create, update, trash and restore. A purge
  cascades to the entity's documents (and module documents belonging to it).
- Modules index their documents with ``index_documents`` from their services.
- Undo re-indexes the entities it touched (``HistoryService``); modules re-index their documents
  from a ``REVERT_HOOKS`` hook.
- Enabling or disabling modules re-indexes the entities whose fields they change
  (``reindex_for_modules``).
- ``reindex`` rebuilds everything (``lore vault reindex``), and so does the first author-mode
  open of a vault whose index was built by another ``INDEX_VERSION`` (or never).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity, EntityAlias
from lore.core.fields import KindFields
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.search.documents import (
    SearchContributor,
    SearchDocument,
    entity_document,
    field_texts,
)
from lore.core.search.models import ENTITY_DOC, SearchDoc
from lore.core.vaults.meta import get_meta, set_meta

# Bump when what gets indexed changes: vaults are re-indexed on their next author-mode open.
INDEX_VERSION = 1
INDEX_META_KEY = "search_index"
BATCH = 500


def contributors(registry: ModuleRegistry) -> dict[str, SearchContributor]:
    """The search contributors of **every** module, by document type (documents of disabled
    modules stay indexed and are filtered out by queries)."""
    return {
        contributor.doc_type: contributor
        for module in registry.modules
        for contributor in module.search_contributors
        if isinstance(contributor, SearchContributor)
    }


class SearchIndexer:
    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session: Session = context.session
        registry = context.registry
        enabled = enabled_modules(self.session, registry)
        field_types = registry.field_types_for(enabled)
        self.texts = field_texts(field_types)
        self.richtext = registry.richtext_handlers()
        self.kind_fields = {
            kind.key: KindFields.build(kind.fields, field_types)
            for kind in registry.kinds_for(enabled)
        }

    # --- entities -------------------------------------------------------------------------------

    def index_entities(self, entity_ids: Iterable[str]) -> None:
        """(Re)index these entities; ids of entities that no longer exist are dropped."""
        ids = sorted(set(entity_ids))
        for start in range(0, len(ids), BATCH):
            chunk = ids[start : start + BATCH]
            entities = list(self.session.scalars(select(Entity).where(Entity.id.in_(chunk))))
            self._put(ENTITY_DOC, self.entity_documents(entities))
            gone = set(chunk) - {entity.id for entity in entities}
            if gone:
                self._remove(ENTITY_DOC, gone)

    def entity_documents(self, entities: Sequence[Entity]) -> list[SearchDocument]:
        """The current search documents of these entities (what the index should hold)."""
        return [self._entity_document(e, a) for e, a in self._with_aliases(entities)]

    def _with_aliases(
        self, entities: Sequence[Entity]
    ) -> list[tuple[Entity, list[tuple[str, str]]]]:
        aliases: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for alias in self.session.scalars(
            select(EntityAlias)
            .where(EntityAlias.entity_id.in_([e.id for e in entities]))
            .order_by(EntityAlias.entity_id, EntityAlias.sort_key, EntityAlias.id)
        ):
            aliases[alias.entity_id].append((alias.alias, alias.visibility))
        return [(entity, aliases[entity.id]) for entity in entities]

    def _entity_document(self, entity: Entity, aliases: list[tuple[str, str]]) -> SearchDocument:
        return entity_document(
            entity,
            aliases,  # type: ignore[arg-type]
            self.kind_fields.get(entity.kind),
            self.texts,
            self.richtext,
        )

    # --- module documents -----------------------------------------------------------------------

    def index_documents(self, doc_type: str, doc_ids: Iterable[str]) -> None:
        """(Re)index a module's documents by id: the contributor supplies the current documents;
        ids it doesn't return are removed from the index."""
        contributor = self._contributor(doc_type)
        ids = sorted(set(doc_ids))
        if not ids:
            return
        documents = list(contributor.documents(self.context, ids))
        self._put(doc_type, documents)
        gone = set(ids) - {doc.doc_id for doc in documents}
        if gone:
            self._remove(doc_type, gone)

    def remove_documents(self, doc_type: str, doc_ids: Iterable[str]) -> None:
        self._remove(self._contributor(doc_type).doc_type, set(doc_ids))

    def _contributor(self, doc_type: str) -> SearchContributor:
        found = contributors(self.context.registry).get(doc_type)
        if found is None:
            raise ValueError(f"No search contributor for {doc_type!r}.")
        return found

    # --- rebuilds -------------------------------------------------------------------------------

    def reindex(self) -> int:
        """Rebuild the whole index; returns the number of documents."""
        # The external-content FTS tables are first rebuilt from search_docs: an index that went
        # out of sync would make the delete triggers below fail ("database disk image is
        # malformed"). Then they are rebuilt from the emptied table, which clears them.
        self._rebuild_fts()
        self.session.execute(delete(SearchDoc))
        self._rebuild_fts()
        count = 0
        last = ""
        while True:
            entities = list(
                self.session.scalars(
                    select(Entity).where(Entity.id > last).order_by(Entity.id).limit(BATCH)
                )
            )
            if not entities:
                break
            self._put(ENTITY_DOC, self.entity_documents(entities))
            count += len(entities)
            last = entities[-1].id
        for doc_type, contributor in contributors(self.context.registry).items():
            documents = list(contributor.documents(self.context, None))
            self._put(doc_type, documents)
            count += len(documents)
        set_meta(self.session, INDEX_META_KEY, {"version": INDEX_VERSION})
        self.session.flush()
        return count

    def _rebuild_fts(self) -> None:
        self.session.execute(text("INSERT INTO search_fts(search_fts) VALUES ('rebuild')"))
        self.session.execute(text("INSERT INTO search_trigram(search_trigram) VALUES ('rebuild')"))

    def reindex_for_modules(self, module_ids: Iterable[str]) -> None:
        """After modules were enabled or disabled: re-index the entities of the kinds they own
        or contribute fields to, and the documents they contribute (whose text may depend on
        other modules)."""
        changed = set(module_ids)
        if not changed:
            return
        registry = self.context.registry
        kinds: set[str] = set()
        for module_id in changed:
            module = registry.get(module_id)
            if module is None:
                continue
            kinds |= {kind.key for kind in module.kinds}
            kinds |= {contribution.kind for contribution in module.field_contributions}
        last = ""
        while kinds:
            ids = list(
                self.session.scalars(
                    select(Entity.id)
                    .where(Entity.kind.in_(kinds), Entity.id > last)
                    .order_by(Entity.id)
                    .limit(BATCH)
                )
            )
            if not ids:
                break
            self.index_entities(ids)
            last = ids[-1]
        for doc_type, contributor in contributors(registry).items():
            if doc_type.split(".", 1)[0] in changed:
                self.session.execute(delete(SearchDoc).where(SearchDoc.doc_type == doc_type))
                self._put(doc_type, list(contributor.documents(self.context, None)))

    # --- rows -----------------------------------------------------------------------------------

    def _put(self, doc_type: str, documents: Sequence[SearchDocument]) -> None:
        """Insert or update rows (an update keeps the rowid; the triggers re-index its text)."""
        if not documents:
            return
        existing = {
            doc.doc_id: doc
            for doc in self.session.scalars(
                select(SearchDoc).where(
                    SearchDoc.doc_type == doc_type,
                    SearchDoc.doc_id.in_([d.doc_id for d in documents]),
                )
            )
        }
        for document in documents:
            values = asdict(document)
            kind = self._kind_of(document.entity_id) if doc_type == ENTITY_DOC else doc_type
            row = existing.get(document.doc_id)
            if row is None:
                row = SearchDoc(doc_type=doc_type, kind=kind)
                self.session.add(row)
            row.kind = kind
            for key, value in values.items():
                setattr(row, key, value)
        self.session.flush()

    def _kind_of(self, entity_id: str) -> str:
        entity = self.session.get(Entity, entity_id)
        assert entity is not None
        return entity.kind

    def _remove(self, doc_type: str, doc_ids: set[str]) -> None:
        self.session.execute(
            delete(SearchDoc).where(SearchDoc.doc_type == doc_type, SearchDoc.doc_id.in_(doc_ids))
        )


def index_is_current(session: Session) -> bool:
    meta = get_meta(session, INDEX_META_KEY)
    return isinstance(meta, dict) and meta.get("version") == INDEX_VERSION


def ensure_index(context: VaultContext) -> int | None:
    """Rebuild the index when it was built by another ``INDEX_VERSION`` (or never, e.g. right
    after the migration that created the tables). Returns the document count when it rebuilt."""
    if index_is_current(context.session):
        return None
    return SearchIndexer(context).reindex()
