"""Search of the static export (#377, ADR 0016): the documents readers can search, for the
browser to match, rank and quote like the server (``frontend/src/data/static-search.ts``, a port
of ``lore.core.search.expression``, ``queries`` and ``highlight``).

``static/search`` holds each document a reader can search in any timeline (by rowid, as the
server orders ties), with its hit members, its entity's branch origin (branch-only entities are
found only in their branch's lineage), and its public text columns: the columns a reader's search
reads, from a published snapshot. The browser loads it on the first search.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.modules.registry import ModuleRegistry
from lore.core.search.models import PUBLIC_COLUMNS, SearchDoc
from lore.core.search.queries import SearchQueries
from lore.core.visibility import READER
from lore.static_export.entities import TimelineInfo


def search_index(
    session: Session, registry: ModuleRegistry, timelines: dict[str, TimelineInfo]
) -> dict[str, Any]:
    docs: dict[int, dict[str, Any]] = {}
    queries = None
    for timeline in [None, *(t.id for t in timelines.values() if not t.prime)]:
        queries = SearchQueries(session, registry, READER, timeline)
        for row, hit in queries.documents():
            docs[row.rowid] = {
                "rowid": row.rowid,
                "hit": hit,
                "text": {column: getattr(row, column) for column in PUBLIC_COLUMNS},
            }
    origins = dict(
        session.execute(
            select(Entity.id, Entity.origin_timeline_id).where(
                Entity.id.in_({d["hit"]["entity_id"] for d in docs.values()})
            )
        ).all()
    )
    for found in docs.values():
        found["origin"] = origins.get(found["hit"]["entity_id"])
    assert queries is not None
    return {
        "docs": [docs[rowid] for rowid in sorted(docs)],
        "kinds": queries.known_kinds(),
        # bm25 statistics are over every row of the FTS table.
        "rows": session.scalar(select(func.count()).select_from(SearchDoc)) or 0,
    }
