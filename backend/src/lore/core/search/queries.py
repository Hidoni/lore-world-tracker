"""Search queries (``data-model.md`` §9, ``api.md`` §2): full-text search with ranking and
snippets, and the quick switcher.

Documents are found when they aren't trashed, their kind (entities) or type (module documents) is
available (its module enabled), and, for module documents, the entity they belong to is shown
too. **Readers** (``VisibilityPolicy.reader``) only search the public columns, through an FTS5
column filter, never see private documents or documents whose entity the policy hides (effective
visibility: e.g. an entity in a private dimension), and get snippets from public columns only.
"""

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, exists, literal_column, select, text
from sqlalchemy.orm import Session, aliased

from lore.core.entities.models import Entity, fold_text
from lore.core.errors import InvalidInputError
from lore.core.modules.registry import ModuleRegistry, RegisteredKind
from lore.core.modules.service import enabled_modules
from lore.core.search import highlight
from lore.core.search.documents import SearchContributor
from lore.core.search.expression import ExpressionError, parse
from lore.core.search.highlight import Term
from lore.core.search.indexer import contributors
from lore.core.search.models import ENTITY_DOC, PUBLIC_COLUMNS, TEXT_COLUMNS, SearchDoc
from lore.core.search.schemas import (
    QuickHit,
    QuickResults,
    SearchHit,
    SearchPage,
    Snippet,
    SnippetPart,
    SnippetSource,
)
from lore.core.visibility import AUTHOR, VisibilityPolicy

DIMENSION_KIND = "dimension"
QUICK_LIMIT = 20
TRIGRAM_MIN = 3

# Ranking: name > aliases > summary > body > fields (module text ranks like body).
WEIGHTS: Mapping[str, float] = {
    "name": 10.0,
    "aliases_public": 6.0,
    "aliases_restricted": 6.0,
    "summary": 4.0,
    "body_public": 2.0,
    "body_restricted": 2.0,
    "fields_public": 1.0,
    "fields_restricted": 1.0,
    "extra_public": 2.0,
    "extra_restricted": 2.0,
}
# Where snippets come from, in order of preference (the first one with a match wins).
SNIPPET_COLUMNS: tuple[tuple[str, SnippetSource], ...] = (
    ("body_public", "body"),
    ("body_restricted", "body"),
    ("summary", "summary"),
    ("extra_public", "extra"),
    ("extra_restricted", "extra"),
    ("fields_public", "fields"),
    ("fields_restricted", "fields"),
    ("aliases_public", "aliases"),
    ("aliases_restricted", "aliases"),
)
_BM25 = "bm25(search_fts, " + ", ".join(str(WEIGHTS[c]) for c in TEXT_COLUMNS) + ")"
_QUICK_BM25 = "bm25(search_fts, " + ", ".join(
    str(WEIGHTS[c]) if c in ("name", "aliases_public", "aliases_restricted") else "0.0"
    for c in TEXT_COLUMNS
) + ")"  # fmt: skip


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[{"path": path, "code": "invalid_value",
                                               "message": message}])  # fmt: skip


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        offset = json.loads(raw)["offset"]
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise _invalid("cursor", "The cursor is invalid.") from exc
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise _invalid("cursor", "The cursor is invalid.")
    return offset


def _columns_filter(columns: Sequence[str], expression: str) -> str:
    return "{" + " ".join(columns) + "} : (" + expression + ")"


class SearchQueries:
    def __init__(
        self, session: Session, registry: ModuleRegistry, policy: VisibilityPolicy = AUTHOR
    ) -> None:
        self.session = session
        self.registry = registry
        self.policy = policy
        self.reader = policy.reader
        enabled = enabled_modules(session, registry)
        self.kinds: dict[str, RegisteredKind] = {k.key: k for k in registry.kinds_for(enabled)}
        self.contributors: dict[str, SearchContributor] = {
            doc_type: contributor
            for doc_type, contributor in contributors(registry).items()
            if doc_type.split(".", 1)[0] in enabled
        }

    # --- shared conditions ----------------------------------------------------------------------

    def _conditions(
        self,
        params: dict[str, Any],
        kinds: Sequence[str] | None,
        dimension: str | None,
        include_multiversal: bool,
    ) -> str:
        """The WHERE conditions on ``d`` (search_docs) besides the MATCH."""
        shown = [*self.kinds, *self.contributors]
        conditions = ["d.deleted = 0", "d.kind IN :shown"]
        params["shown"] = shown
        params["entity_kinds"] = list(self.kinds)
        owner = "e.id = d.entity_id AND e.deleted_at IS NULL AND e.kind IN :entity_kinds"
        conditions.append(f"(d.doc_type = '{ENTITY_DOC}' OR EXISTS "
                          f"(SELECT 1 FROM entities e WHERE {owner}))")  # fmt: skip
        if self.reader:
            conditions += ["d.visibility != 'private'", self._visible_owner()]
        if kinds:
            known = self.registry.all_kind_keys() | set(contributors(self.registry))
            unknown = [kind for kind in kinds if kind not in known]
            if unknown:
                raise _invalid("kind", f"Unknown kind {unknown[0]!r}.")
            conditions.append("d.kind IN :kinds")
            params["kinds"] = list(kinds)
        if dimension is not None:
            params["dimension"] = dimension
            if include_multiversal:
                conditions.append("(d.dimension_id = :dimension OR (d.dimension_id IS NULL "
                                  f"AND d.kind != '{DIMENSION_KIND}'))")  # fmt: skip
            else:
                conditions.append("d.dimension_id = :dimension")
        return " AND ".join(conditions)

    def _visible_owner(self) -> str:
        """SQL: the policy shows the document's entity (the policy's own conditions, compiled
        with literal values: they hold no user input)."""
        owner = aliased(Entity, name="vis_owner")
        condition = exists().where(
            owner.id == literal_column("d.entity_id"), *self.policy.entities(owner)
        )
        dialect = self.session.get_bind().dialect
        return str(condition.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))

    def _execute(self, sql: str, params: dict[str, Any]) -> Sequence[Any]:
        statement = text(sql)
        for name in ("shown", "entity_kinds", "kinds"):
            if name in params:
                statement = statement.bindparams(bindparam(name, expanding=True))
        return self.session.execute(statement, params).all()

    # --- full-text search -----------------------------------------------------------------------

    def search(
        self,
        q: str,
        *,
        kinds: Sequence[str] | None = None,
        dimension: str | None = None,
        include_multiversal: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> SearchPage:
        """Ranked hits (bm25: name > aliases > summary > body > fields) with snippets."""
        try:
            expression = parse(q)
        except ExpressionError as exc:
            raise _invalid("q", str(exc)) from exc
        match = expression.fts
        if self.reader:
            match = _columns_filter(PUBLIC_COLUMNS, match)
        offset = _decode_cursor(cursor) if cursor else 0
        params: dict[str, Any] = {"match": match, "limit": limit + 1, "offset": offset}
        where = self._conditions(params, kinds, dimension, include_multiversal)
        rows = self._execute(
            "SELECT d.rowid FROM search_fts JOIN search_docs d ON d.rowid = search_fts.rowid "
            f"WHERE search_fts MATCH :match AND {where} "
            f"ORDER BY {_BM25}, d.rowid LIMIT :limit OFFSET :offset",
            params,
        )
        rowids = [row[0] for row in rows[:limit]]
        docs = self._docs(rowids)
        items = [
            SearchHit(**hit, snippet=self._snippet(docs[rowid], expression.terms))
            for rowid, hit in zip(rowids, self._hits(docs, rowids), strict=True)
        ]
        next_cursor = _encode_cursor(offset + limit) if len(rows) > limit else None
        return SearchPage(items=items, next_cursor=next_cursor)

    def _snippet(self, doc: SearchDoc, terms: Sequence[Term]) -> Snippet | None:
        """From the first column (in ``SNIPPET_COLUMNS`` order) with a match; readers' snippets
        come from public columns only."""
        for column, source in SNIPPET_COLUMNS:
            if self.reader and column.endswith("_restricted"):
                continue
            parts = highlight.snippet(getattr(doc, column), terms)
            if parts is not None:
                return Snippet(
                    source=source, parts=[SnippetPart(text=p.text, match=p.match) for p in parts]
                )
        return None

    def _docs(self, rowids: Sequence[int]) -> dict[int, SearchDoc]:
        return {
            doc.rowid: doc
            for doc in self.session.scalars(select(SearchDoc).where(SearchDoc.rowid.in_(rowids)))
        }

    def _hits(self, docs: Mapping[int, SearchDoc], rowids: Sequence[int]) -> list[dict[str, Any]]:
        """Hit members of these documents, in this order."""
        entities = {
            entity.id: entity
            for entity in self.session.scalars(
                select(Entity).where(Entity.id.in_({d.entity_id for d in docs.values()}))
            )
        }
        hits = []
        for rowid in rowids:
            doc = docs[rowid]
            icon: str | None
            color: str | None
            if doc.doc_type == ENTITY_DOC:
                entity = entities[doc.entity_id]
                definition = self.kinds[doc.kind].definition
                icon, color = entity.icon or definition.icon, entity.color or definition.color
            else:
                icon, color = self.contributors[doc.doc_type].icon, None
            hits.append(
                {
                    "doc_type": doc.doc_type,
                    "doc_id": doc.doc_id,
                    "entity_id": doc.entity_id,
                    "kind": doc.kind,
                    "name": doc.name,
                    "icon": icon,
                    "color": color,
                    "dimension_id": doc.dimension_id,
                    "visibility": doc.visibility,
                }
            )
        return hits

    # --- quick switcher -------------------------------------------------------------------------

    def quick(
        self,
        q: str,
        *,
        kinds: Sequence[str] | None = None,
        dimension: str | None = None,
        include_multiversal: bool = True,
    ) -> QuickResults:
        """Up to 20 documents whose name or an alias has words starting with every typed word
        (best first), then documents whose name or a public alias contains the typed text
        (3 characters or more). Typed text is never interpreted as an expression."""
        words = re.findall(r"\w+", q)
        if not words:
            return QuickResults(items=[])
        columns = ["name", "aliases_public"] + ([] if self.reader else ["aliases_restricted"])
        prefix = " AND ".join('"' + word + '"*' for word in words[:16])
        params: dict[str, Any] = {"match": _columns_filter(columns, prefix), "limit": QUICK_LIMIT}
        where = self._conditions(params, kinds, dimension, include_multiversal)
        rowids = [
            row[0]
            for row in self._execute(
                "SELECT d.rowid FROM search_fts JOIN search_docs d ON d.rowid = search_fts.rowid "
                f"WHERE search_fts MATCH :match AND {where} "
                f"ORDER BY {_QUICK_BM25}, length(d.name), d.rowid LIMIT :limit",
                params,
            )
        ]
        needle = q.strip()
        if len(rowids) < QUICK_LIMIT and len(needle) >= TRIGRAM_MIN:
            params["match"] = '"' + needle.replace('"', '""') + '"'
            params["limit"] = QUICK_LIMIT * 2
            for (rowid,) in self._execute(
                "SELECT d.rowid FROM search_trigram "
                "JOIN search_docs d ON d.rowid = search_trigram.rowid "
                f"WHERE search_trigram MATCH :match AND {where} "
                "ORDER BY length(d.name), d.rowid LIMIT :limit",
                params,
            ):
                if rowid not in rowids:
                    rowids.append(rowid)
                if len(rowids) == QUICK_LIMIT:
                    break
        docs = self._docs(rowids)
        items = [
            QuickHit(**hit, alias=self._matched_alias(docs[hit_rowid], words, needle))
            for hit_rowid, hit in zip(rowids, self._hits(docs, rowids), strict=True)
        ]
        return QuickResults(items=items)

    def _matched_alias(self, doc: SearchDoc, words: Sequence[str], needle: str) -> str | None:
        """The first alias that matches when the name doesn't."""
        if _matches(doc.name, words, needle):
            return None
        aliases = doc.aliases_public.splitlines()
        if not self.reader:
            aliases += doc.aliases_restricted.splitlines()
        return next((alias for alias in aliases if _matches(alias, words, needle)), None)


def _matches(text_: str, words: Sequence[str], needle: str) -> bool:
    folded = fold_text(text_)
    tokens = re.findall(r"\w+", folded)
    prefixes = all(any(t.startswith(fold_text(w)) for t in tokens) for w in words)
    return prefixes or (len(needle) >= TRIGRAM_MIN and fold_text(needle) in folded)
