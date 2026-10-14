"""Unlinked mentions (R-LNK-3, ``api.md`` §2): where other entities' bodies name an entity, by its
name or an alias, without linking to it.

Candidates come from the full-text index (a phrase query over the body columns, which ignores
case and diacritics like the search does). Each candidate's body is then walked as the request
may see it (``filter_richtext`` for readers): a match is a whole-word occurrence, ignoring case and
diacritics, inside one text node that isn't already an ``entityLink`` to the entity. Positions are
the text node's path and UTF-16 offsets, which the editor's documents use.
"""

import unicodedata
from collections.abc import Callable, Collection, Iterator, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity, EntityAlias
from lore.core.links.schemas import (
    LinkedEntity,
    UnlinkedMentions,
    UnlinkedOccurrence,
    UnlinkedSource,
)
from lore.core.modules.registry import ModuleRegistry
from lore.core.visibility import VisibilityPolicy

CONTEXT = 40
MIN_TERM = 2


def _fold(value: str) -> tuple[str, list[int]]:
    """``value`` without case or diacritics, and for each folded character the index of the
    original character it came from."""
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(value):
        base = "".join(
            c for c in unicodedata.normalize("NFD", char) if not unicodedata.combining(c)
        ).casefold()
        folded.append(base)
        origin.extend([index] * len(base))
    return "".join(folded), origin


def _utf16(value: str, index: int) -> int:
    """The UTF-16 offset of a character index (the editor counts in code units)."""
    return len(value[:index].encode("utf-16-le")) // 2


def find_occurrences(value: str, terms: Sequence[str]) -> Iterator[tuple[int, int]]:
    """Whole-word occurrences of any term (case and diacritics ignored) in ``value``, as
    character ``(start, end)``, longest term first where they overlap."""
    folded, origin = _fold(value)
    taken: list[tuple[int, int]] = []
    for term in sorted({_fold(t)[0] for t in terms}, key=len, reverse=True):
        if len(term) < MIN_TERM:
            continue
        start = folded.find(term)
        while start != -1:
            end = start + len(term)
            before = folded[start - 1] if start > 0 else " "
            after = folded[end] if end < len(folded) else " "
            first, last = origin[start], origin[end - 1] + 1
            while last < len(value) and unicodedata.combining(value[last]):
                last += 1  # a decomposed accent belongs to the match
            if (not before.isalnum() and not after.isalnum()
                    and all(last <= a or first >= b for a, b in taken)):  # fmt: skip
                taken.append((first, last))
            start = folded.find(term, start + 1)
    yield from sorted(taken)


def _linked_to(node: dict[str, Any], entity_id: str) -> bool:
    return any(
        isinstance(mark, dict)
        and mark.get("type") == "entityLink"
        and (mark.get("attrs") or {}).get("entityId") == entity_id
        for mark in node.get("marks") or []
    )


def _walk(node: Any, path: list[int]) -> Iterator[tuple[list[int], dict[str, Any]]]:
    if not isinstance(node, dict):
        return
    if node.get("type") == "text" and isinstance(node.get("text"), str):
        yield path, node
        return
    for index, child in enumerate(node.get("content") or []):
        yield from _walk(child, [*path, index])


def occurrences_in(doc: Any, entity_id: str, terms: Sequence[str]) -> list[UnlinkedOccurrence]:
    """The unlinked occurrences of the terms in a rich-text document."""
    found: list[UnlinkedOccurrence] = []
    for path, node in _walk(doc, []):
        if _linked_to(node, entity_id):
            continue
        value: str = node["text"]
        for start, end in find_occurrences(value, terms):
            found.append(
                UnlinkedOccurrence(
                    path=path,
                    offset=_utf16(value, start),
                    length=_utf16(value, end) - _utf16(value, start),
                    text=value[start:end],
                    before=value[max(0, start - CONTEXT) : start],
                    after=value[end : end + CONTEXT],
                )
            )
    return found


def _phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class UnlinkedMentionFinder:
    def __init__(
        self,
        session: Session,
        registry: ModuleRegistry,
        policy: VisibilityPolicy,
        kinds: Collection[str],
    ) -> None:
        self.session = session
        self.registry = registry
        self.policy = policy
        self.kinds = kinds

    def terms(self, entity: Entity) -> list[str]:
        """The entity's name and the aliases the policy shows."""
        aliases = self.session.scalars(
            select(EntityAlias.alias)
            .where(EntityAlias.entity_id == entity.id, *self.policy.rows(EntityAlias))
            .order_by(EntityAlias.alias)
        )
        terms = (t.strip() for t in [entity.name, *aliases])
        return [t for t in dict.fromkeys(terms) if len(t) >= MIN_TERM]

    def _candidates(self, entity_id: str, terms: Sequence[str], limit: int) -> list[str]:
        query = "{body_public body_restricted} : (" + " OR ".join(map(_phrase, terms)) + ")"
        rows = self.session.execute(
            text(
                "SELECT d.entity_id FROM search_fts "
                "JOIN search_docs d ON d.rowid = search_fts.rowid "
                "WHERE search_fts MATCH :q AND d.doc_type = 'entity' AND d.deleted = 0 "
                "AND d.entity_id != :target LIMIT :limit"
            ),
            {"q": query, "target": entity_id, "limit": limit},
        )
        return [row[0] for row in rows]

    def find(
        self, entity: Entity, *, limit: int, linked: Callable[[Entity], LinkedEntity]
    ) -> UnlinkedMentions:
        terms = self.terms(entity)
        if not terms:
            return UnlinkedMentions(terms=[], items=[], truncated=False)
        # More candidates than asked: some match only where the request can't see, or only
        # inside existing links.
        cap = limit * 4 + 1
        candidates = self._candidates(entity.id, terms, cap)
        sources = self.session.scalars(
            select(Entity).where(
                Entity.id.in_(candidates),
                Entity.deleted_at.is_(None),
                Entity.kind.in_(self.kinds),
                *self.policy.entities(Entity),
            )
        ).all()
        handlers = self.registry.richtext_handlers()
        items: list[UnlinkedSource] = []
        for source in sorted(sources, key=lambda e: (e.sort_name, e.id)):
            body = self.policy.filter_richtext(self.session, source.body, handlers)
            found = occurrences_in(body, entity.id, terms)
            if found:
                items.append(UnlinkedSource(entity=linked(source), occurrences=found))
        return UnlinkedMentions(
            terms=terms,
            items=items[:limit],
            truncated=len(items) > limit or len(candidates) == cap,
        )
