"""Search documents and the text they are made of (``data-model.md`` §9).

A ``SearchDocument`` is what gets indexed: filters plus text split into **public** columns
(content readers may see: public and spoiler) and **restricted** columns (private content).
Entities become documents of type ``entity`` (``entity_document``). Modules contribute their own
document types through ``SearchContributor``s (``ModuleSpec.search_contributors``).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from lore.core.db.base import Visibility
from lore.core.entities.models import Entity
from lore.core.fields import KindFields
from lore.core.registry.types import FieldDef, FieldTypeDef
from lore.core.richtext.extract import extract
from lore.core.richtext.handlers import RichTextNodeHandler

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext


@dataclass(frozen=True)
class SearchDocument:
    """One searchable document. ``entity_id`` is the entity the document is or belongs to (a
    lexicon entry's language): a module document is only found while that entity is visible and
    not in the trash. Lines of multi-valued text (aliases, field values) are joined with
    newlines."""

    doc_id: str
    entity_id: str
    dimension_id: str | None
    visibility: Visibility
    name: str
    deleted: bool = False
    aliases_public: str = ""
    aliases_restricted: str = ""
    summary: str = ""
    body_public: str = ""
    body_restricted: str = ""
    fields_public: str = ""
    fields_restricted: str = ""
    extra_public: str = ""
    extra_restricted: str = ""


@dataclass(frozen=True)
class SearchContributor:
    """A module's document type (``modules.md`` §2.1).

    - ``doc_type``: ``<module id>.<type>`` (e.g. ``languages.lexicon_entry``); also the
      document's ``kind`` in search filters.
    - ``documents(context, doc_ids)``: the current documents with these ids (ids without a
      document are removed from the index), or every document when ``doc_ids`` is ``None``
      (reindex).
    - ``icon``: shown next to hits (the quick switcher).

    The module's services call ``SearchIndexer.index_documents`` in their write transactions.
    """

    doc_type: str
    documents: Callable[[VaultContext, Sequence[str] | None], Iterable[SearchDocument]]
    label: str
    icon: str


type FieldText = Callable[[Any, FieldDef], str]


def _plain(value: Any, _field: FieldDef) -> str:
    return str(value)


def _option_labels(value: Any, field: FieldDef) -> str:
    labels = {option.key: option.label for option in field.options}
    keys = value if isinstance(value, list) else [value]
    return "\n".join(labels.get(str(key), str(key)) for key in keys)


def _measurement(value: Any, _field: FieldDef) -> str:
    if not isinstance(value, dict):
        return ""
    return f"{value.get('value', '')} {value.get('unit', '')}".strip()


def _decimal(value: Any, _field: FieldDef) -> str:
    try:
        return str(Decimal(str(value)).normalize()) if value is not None else ""
    except InvalidOperation:
        return str(value)


def _nothing(_value: Any, _field: FieldDef) -> str:
    return ""


# How the value of each core field type reads in the index. Types without meaningful words
# (booleans, colors, media ids) and time values (rendered by calendars, M3) add nothing.
CORE_FIELD_TEXT: Mapping[str, FieldText] = {
    "text": _plain,
    "long_text": _plain,
    "url": _plain,
    "integer": _plain,
    "decimal": _decimal,
    "enum": _option_labels,
    "multi_enum": _option_labels,
    "measurement": _measurement,
    "boolean": _nothing,
    "color": _nothing,
    "duration": _nothing,
    "time_point": _nothing,
    "media": _nothing,
}


def field_texts(field_types: Sequence[FieldTypeDef]) -> dict[str, FieldText]:
    """The text renderer of each available field type: core's, or the module type's
    ``search_text`` (nothing when it has none). ``rich_text`` is handled separately."""
    return {t.key: CORE_FIELD_TEXT.get(t.key, t.search_text or _nothing) for t in field_types}


def _lines(texts: Iterable[str]) -> str:
    return "\n".join(text for text in texts if text)


def entity_document(
    entity: Entity,
    aliases: Iterable[tuple[str, Visibility]],
    kind_fields: KindFields | None,
    texts: Mapping[str, FieldText],
    richtext: Mapping[str, RichTextNodeHandler],
) -> SearchDocument:
    """The document of an entity. Private aliases, private field values and private rich-text
    blocks go to the restricted columns. ``kind_fields`` is ``None`` for entities of disabled
    modules: their fields aren't indexed until the module is enabled again."""
    aliases = list(aliases)
    body = extract(entity.body, richtext)
    public_fields: list[str] = []
    restricted_fields: list[str] = []
    for key, field in (kind_fields.active if kind_fields else {}).items():
        value = entity.fields.get(key)
        if value is None or not field.searchable:
            continue
        level: Visibility = entity.field_visibility.get(key, field.default_visibility)
        values = value if field.multiple and isinstance(value, list) else [value]
        if field.type == "rich_text":
            for doc in values:
                found = extract(doc, richtext, visibility=level)
                public_fields.append(found.public_text)
                restricted_fields.append(found.restricted_text)
            continue
        render = texts.get(field.type, _nothing)
        rendered = _lines(render(item, field) for item in values)
        (restricted_fields if level == "private" else public_fields).append(rendered)
    return SearchDocument(
        doc_id=entity.id,
        entity_id=entity.id,
        dimension_id=entity.dimension_id,
        visibility=entity.visibility,
        deleted=entity.deleted_at is not None,
        name=entity.name,
        aliases_public=_lines(a for a, level in aliases if level != "private"),
        aliases_restricted=_lines(a for a, level in aliases if level == "private"),
        summary=entity.summary,
        body_public=body.public_text,
        body_restricted=body.restricted_text,
        fields_public=_lines(public_fields),
        fields_restricted=_lines(restricted_fields),
    )
