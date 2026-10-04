"""API schemas of the search endpoints (``docs/architecture/api.md`` §2, Search)."""

from typing import Literal

from pydantic import BaseModel

from lore.core.db.base import Visibility

type SnippetSource = Literal["aliases", "summary", "body", "fields", "extra"]


class SnippetPart(BaseModel):
    """A piece of a snippet; ``match`` pieces are highlighted."""

    text: str
    match: bool


class Snippet(BaseModel):
    """Text around the matches, from one column (``source``). ``parts`` joined is the text."""

    source: SnippetSource
    parts: list[SnippetPart]


class SearchHit(BaseModel):
    """A matching document: an entity (``doc_type`` ``entity``, ``doc_id`` = ``entity_id``) or a
    module document (``doc_type`` ``<module>.<type>``, belonging to ``entity_id``)."""

    doc_type: str
    doc_id: str
    entity_id: str
    kind: str  # the entity's kind, or the module document's type
    name: str
    icon: str | None
    color: str | None
    dimension_id: str | None
    visibility: Visibility
    snippet: Snippet | None  # None when only the name matched


class SearchPage(BaseModel):
    items: list[SearchHit]
    next_cursor: str | None


class QuickHit(BaseModel):
    """A quick-switcher entry. ``alias`` is the alias that matched when the name didn't."""

    doc_type: str
    doc_id: str
    entity_id: str
    kind: str
    name: str
    alias: str | None
    icon: str | None
    color: str | None
    dimension_id: str | None
    visibility: Visibility


class QuickResults(BaseModel):
    items: list[QuickHit]
