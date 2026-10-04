"""Full-text search (``data-model.md`` §9): the derived ``search_docs`` table and its FTS5
indexes (``models``), documents and module contributors (``documents``), the indexer that services
call in their write transactions (``indexer``), search expressions (``expression``) and the search
and quick-switcher queries (``queries``).

Only the document types are re-exported here: the module registry imports them, and the indexer
and queries import the registry."""

from lore.core.search.documents import SearchContributor, SearchDocument

__all__ = ["SearchContributor", "SearchDocument"]
