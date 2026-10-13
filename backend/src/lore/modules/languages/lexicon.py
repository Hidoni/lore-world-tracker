"""The lexicon service (``docs/modules/languages.md``): entries of a language, sorted by its own
alphabet, with optional attestation periods, search documents and CSV import/export.

Writes run in the request's transaction (one changeset) and keep derived data in step: the
collation key, the time slots (``TimeWriter``) and the search documents. Reads go through the
request's ``VisibilityPolicy`` (``LEXICON_VISIBILITY``): an entry is hidden when it is private or
its language is hidden.
"""

import base64
import binascii
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import exists, func, or_, select, tuple_
from sqlalchemy.orm import Session

from lore.chronology.schema import TimePoint
from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.history.models import Change
from lore.core.modules.spec import VaultContext
from lore.core.search import SearchContributor, SearchDocument
from lore.core.search.indexer import SearchIndexer
from lore.core.time import SlotDef, SlotProvider
from lore.core.time.changes import report as report_time
from lore.core.time.dimensions import TIMELINE
from lore.core.time.propagate import TimeWriter
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityFilter, VisibilityPolicy
from lore.modules.languages.collation import Alphabet
from lore.modules.languages.kinds import LANGUAGE
from lore.modules.languages.lexicon_schemas import (
    Definition,
    Etymology,
    LexiconEntryCreate,
    LexiconEntryOut,
    LexiconEntryUpdate,
    LexiconPage,
    LexiconSort,
    LexiconWriteResult,
)
from lore.modules.languages.models import LexiconEntry

RECORD = "languages.lexicon_entry"
DOC_TYPE = RECORD
ALPHABET_FIELD = "alphabet_order"
SLOTS = ("valid_from", "valid_to")

LEXICON_VISIBILITY = VisibilityFilter(LexiconEntry, entity_columns=("language_id",))
LEXICON_SLOTS = SlotProvider(
    RECORD,
    LexiconEntry,
    (SlotDef("valid_from"), SlotDef("valid_to")),
    timeline_column="timeline_id",
)


def entry_out(entry: LexiconEntry) -> LexiconEntryOut:
    return LexiconEntryOut(
        id=entry.id,
        language_id=entry.language_id,
        headword=entry.headword,
        romanization=entry.romanization,
        pronunciation=entry.pronunciation,
        part_of_speech=entry.part_of_speech,
        definitions=[Definition.model_validate(d) for d in entry.definitions],
        etymology=Etymology.model_validate(entry.etymology or {}),
        notes=entry.notes,
        tags=list(entry.tags),
        collation_key=entry.collation_key,
        visibility=entry.visibility,
        timeline_id=entry.timeline_id,
        valid_from=entry.valid_from_spec,
        valid_to=entry.valid_to_spec,
        valid_from_t=entry.valid_from_t,
        valid_to_t=entry.valid_to_t,
        time_status=entry.time_status,
        sort_key=entry.sort_key,
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        deleted_at=entry.deleted_at,
    )


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- cursors ------------------------------------------------------------------------------------


def _encode_cursor(values: Sequence[Any]) -> str:
    raw = json.dumps([str(value) for value in values]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, size: int) -> list[str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise _invalid("cursor", "The cursor is not valid.") from error
    if not isinstance(values, list) or len(values) != size:
        raise _invalid("cursor", "The cursor is not valid.")
    return [str(value) for value in values]


# --- the service ----------------------------------------------------------------------------


@dataclass
class Lexicon:
    context: VaultContext
    policy: VisibilityPolicy = AUTHOR

    def __post_init__(self) -> None:
        self.session: Session = self.context.session
        self.entities = EntityService(self.context, self.policy)

    # --- lookups ----------------------------------------------------------------------------

    def language(self, language_id: str) -> Entity:
        """A language the request sees (``404`` otherwise, also for other kinds)."""
        entity = self.entities.load_visible(language_id)
        if entity.kind != LANGUAGE:
            raise NotFoundError(f"No language {language_id}.")
        return entity

    def entry(self, entry_id: str, *, include_deleted: bool = False) -> LexiconEntry:
        """An entry the request sees (its language visible too)."""
        statement = select(LexiconEntry).where(
            LexiconEntry.id == entry_id, *self.policy.module_rows(LEXICON_VISIBILITY)
        )
        entry = self.session.scalar(statement)
        if entry is None or (entry.deleted_at is not None and not include_deleted):
            raise NotFoundError(f"No lexicon entry {entry_id}.")
        self.language(entry.language_id)
        return entry

    def alphabet(self, language: Entity) -> Alphabet:
        order = (language.fields or {}).get(ALPHABET_FIELD)
        return Alphabet.parse(order if isinstance(order, str) else None)

    # --- reads ------------------------------------------------------------------------------

    def page(
        self,
        language_id: str,
        *,
        q: str | None = None,
        pos: str | None = None,
        tag: str | None = None,
        sort: LexiconSort = "collation",
        cursor: str | None = None,
        limit: int = 100,
    ) -> LexiconPage:
        """A page of the language's live entries the request sees: ``q`` matches the start of
        the headword or romanization, or any gloss; ``pos`` and ``tag`` filter."""
        self.language(language_id)
        e = LexiconEntry
        statement = select(e).where(
            e.language_id == language_id,
            e.deleted_at.is_(None),
            *self.policy.module_rows(LEXICON_VISIBILITY),
        )
        if q and q.strip():
            text = _like(q.strip().lower())
            glosses = func.json_each(e.definitions).table_valued("value")
            gloss = func.lower(func.json_extract(glosses.c.value, "$.gloss"))
            statement = statement.where(
                or_(
                    func.lower(e.headword).like(f"{text}%", escape="\\"),
                    func.lower(e.romanization).like(f"{text}%", escape="\\"),
                    exists(
                        select(1).select_from(glosses).where(gloss.like(f"%{text}%", escape="\\"))
                    ),
                )
            )
        if pos:
            statement = statement.where(e.part_of_speech == pos)
        if tag:
            tags = func.json_each(e.tags).table_valued("value")
            statement = statement.where(
                exists(select(1).select_from(tags).where(tags.c.value == tag))
            )
        if sort == "collation":
            keys: Any = (e.collation_key, e.id)
        elif sort == "headword":
            keys = (e.headword, e.id)
        else:
            keys = (e.updated_at, e.id)
        descending = sort == "recent"
        if cursor is not None:
            after: list[Any] = _decode_cursor(cursor, 2)
            values = [_parse_time(after[0]), after[1]] if sort == "recent" else after
            row = tuple_(*keys)
            statement = statement.where(
                row < tuple_(*values) if descending else row > tuple_(*values)
            )
        order = [key.desc() for key in keys] if descending else list(keys)
        entries = list(self.session.scalars(statement.order_by(*order).limit(limit + 1)))
        next_cursor = None
        if len(entries) > limit:
            entries = entries[:limit]
            last = entries[-1]
            first_key = {
                "collation": last.collation_key,
                "headword": last.headword,
                "recent": last.updated_at.isoformat(),
            }[sort]
            next_cursor = _encode_cursor([first_key, last.id])
        return LexiconPage(items=[entry_out(entry) for entry in entries], next_cursor=next_cursor)

    def visible_entries(self, language_id: str) -> list[LexiconEntry]:
        """Every live entry of the language the request sees, in collation order (export)."""
        self.language(language_id)
        return list(
            self.session.scalars(
                select(LexiconEntry)
                .where(
                    LexiconEntry.language_id == language_id,
                    LexiconEntry.deleted_at.is_(None),
                    *self.policy.module_rows(LEXICON_VISIBILITY),
                )
                .order_by(LexiconEntry.collation_key, LexiconEntry.id)
            )
        )

    # --- writes -----------------------------------------------------------------------------

    def create(self, language_id: str, data: LexiconEntryCreate) -> LexiconWriteResult:
        entry = self.add(self.language(language_id), data)
        writer = TimeWriter(self.context)
        self._write_validity(writer, entry, set(SLOTS))
        writer.propagate(path="valid_from")
        SearchIndexer(self.context).index_documents(DOC_TYPE, [entry.id])
        return LexiconWriteResult(entry=entry_out(entry), affected=self.affected([entry]))

    def add(self, language: Entity, data: LexiconEntryCreate) -> LexiconEntry:
        """A new entry of ``language`` (validated and flushed; slots and search are the
        caller's: ``create`` and the CSV import batch them)."""
        self._check_validity(language, data.timeline_id, data.valid_from, data.valid_to)
        entry = LexiconEntry(
            language_id=language.id,
            headword=data.headword,
            romanization=data.romanization,
            pronunciation=data.pronunciation,
            part_of_speech=data.part_of_speech,
            definitions=[d.model_dump(exclude_none=True) for d in data.definitions],
            etymology=data.etymology.model_dump(exclude_none=True),
            notes=data.notes,
            tags=list(dict.fromkeys(data.tags)),
            collation_key=self.alphabet(language).key(data.headword),
            visibility=data.visibility,
            timeline_id=data.timeline_id,
            valid_from_spec=data.valid_from,
            valid_to_spec=data.valid_to,
            sort_key=data.sort_key,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def update(self, entry_id: str, data: LexiconEntryUpdate) -> LexiconWriteResult:
        entry = self.entry(entry_id)
        if data.revision != entry.revision:
            raise RevisionConflictError(
                f"The entry was changed meanwhile (revision {entry.revision}, the edit is based "
                f"on {data.revision}).",
                context={"current": entry_out(entry).model_dump(mode="json")},
            )
        language = self.language(entry.language_id)
        sent = data.model_fields_set - {"revision", "suppress"}
        if "headword" in sent and data.headword is None:
            raise _invalid("headword", "A headword is required.")
        timeline_id = data.timeline_id if "timeline_id" in sent else entry.timeline_id
        valid_from = data.valid_from if "valid_from" in sent else entry.valid_from_spec
        valid_to = data.valid_to if "valid_to" in sent else entry.valid_to_spec
        self._check_validity(language, timeline_id, valid_from, valid_to)
        for name in ("headword", "romanization", "pronunciation", "part_of_speech", "notes",
                     "visibility", "timeline_id", "sort_key"):  # fmt: skip
            if name in sent:
                setattr(entry, name, getattr(data, name))
        if "definitions" in sent:
            entry.definitions = [d.model_dump(exclude_none=True) for d in data.definitions or []]
        if "etymology" in sent:
            entry.etymology = (data.etymology or Etymology()).model_dump(exclude_none=True)
        if "tags" in sent:
            entry.tags = list(dict.fromkeys(data.tags or []))
        if "valid_from" in sent:
            entry.valid_from_spec = data.valid_from
        if "valid_to" in sent:
            entry.valid_to_spec = data.valid_to
        if "visibility" in sent and data.visibility is None:
            raise _invalid("visibility", "A visibility is required.")
        entry.collation_key = self.alphabet(language).key(entry.headword)
        self.session.flush()
        changed = {slot for slot in SLOTS if slot in sent or "timeline_id" in sent}
        if changed:
            writer = TimeWriter(self.context)
            self._write_validity(writer, entry, changed)
            writer.propagate(path="valid_from")
        SearchIndexer(self.context).index_documents(DOC_TYPE, [entry.id])
        return LexiconWriteResult(entry=entry_out(entry), affected=self.affected([entry]))

    def delete(self, entry_id: str) -> LexiconWriteResult:
        """Move the entry to the trash (its search document goes)."""
        entry = self.entry(entry_id)
        entry.deleted_at = utc_now()
        self.session.flush()
        SearchIndexer(self.context).remove_documents(DOC_TYPE, [entry.id])
        return LexiconWriteResult(entry=entry_out(entry), affected=self.affected([entry]))

    def affected(self, entries: Iterable[LexiconEntry]) -> Affected:
        ids = sorted({entry.language_id for entry in entries})
        dimensions = self.session.scalars(
            select(Entity.dimension_id).where(Entity.id.in_(ids), Entity.dimension_id.is_not(None))
        )
        affected = Affected(
            entities=ids,
            dimensions=sorted({d for d in dimensions if d is not None}),
            time_changed=False,
            search_changed=True,
        )
        return report_time(self.session, self.context.registry, affected)

    # --- time -------------------------------------------------------------------------------

    def _check_validity(
        self,
        language: Entity,
        timeline_id: str | None,
        valid_from: TimePoint | None,
        valid_to: TimePoint | None,
    ) -> None:
        """An attestation bound needs a timeline the request sees, of the language's dimension
        (any for a multiversal language)."""
        if valid_from is None and valid_to is None:
            return
        if timeline_id is None:
            raise _invalid("timeline_id", "An attestation period needs a timeline.", "required")
        try:
            timeline = self.entities.load_visible(timeline_id)
        except NotFoundError as error:
            raise _invalid("timeline_id", f"No timeline {timeline_id}.") from error
        if timeline.kind != TIMELINE or timeline.deleted_at is not None:
            raise _invalid("timeline_id", f"{timeline_id} is not a timeline.")
        if language.dimension_id is not None and timeline.dimension_id != language.dimension_id:
            raise _invalid("timeline_id", "The timeline is not in the language's dimension.")

    def _write_validity(self, writer: TimeWriter, entry: LexiconEntry, slots: set[str]) -> None:
        for slot in sorted(slots):
            spec = entry.valid_from_spec if slot == "valid_from" else entry.valid_to_spec
            writer.set_spec(RECORD, entry.id, slot, spec)

    # --- collation --------------------------------------------------------------------------

    def recollate(self, language: Entity) -> int:
        """Recompute the collation keys of every entry of the language (its alphabet changed).
        Returns how many keys changed."""
        alphabet = self.alphabet(language)
        changed = 0
        for entry in self.session.scalars(
            select(LexiconEntry).where(LexiconEntry.language_id == language.id)
        ):
            key = alphabet.key(entry.headword)
            if key != entry.collation_key:
                entry.collation_key = key
                changed += 1
        if changed:
            self.session.flush()
        return changed


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise _invalid("cursor", "The cursor is not valid.") from error


# --- search and history --------------------------------------------------------------------------


def lexicon_documents(context: VaultContext, ids: Sequence[str] | None) -> list[SearchDocument]:
    """Search documents of entries (``languages.lexicon_entry``): headword, romanization and
    pronunciation as names, glosses as the summary. Found only while the language is visible."""
    statement = select(LexiconEntry, Entity.dimension_id).join(
        Entity, Entity.id == LexiconEntry.language_id
    )
    if ids is not None:
        statement = statement.where(LexiconEntry.id.in_(list(ids)))
    documents = []
    for entry, dimension_id in context.session.execute(statement):
        glosses = [str(d.get("gloss", "")) for d in entry.definitions if isinstance(d, dict)]
        documents.append(
            SearchDocument(
                doc_id=entry.id,
                entity_id=entry.language_id,
                dimension_id=dimension_id,
                visibility=entry.visibility,
                name=entry.headword,
                deleted=entry.deleted_at is not None,
                aliases_public="\n".join(
                    value for value in (entry.romanization, entry.pronunciation) if value
                ),
                summary="; ".join(glosses),
                extra_public="\n".join(entry.tags),
            )
        )
    return documents


LEXICON_SEARCH = SearchContributor(DOC_TYPE, lexicon_documents, "Lexicon entry", "book")


def reindex_after_revert(context: VaultContext, changes: Sequence[Change]) -> None:
    """After an undo or redo: re-index the entries it touched."""
    ids = [change.row_id for change in changes if change.table_name == LexiconEntry.__tablename__]
    if ids:
        SearchIndexer(context).index_documents(DOC_TYPE, ids)


def purge_entries(context: VaultContext, entity: Entity) -> None:
    """Before a language is purged: its entries go with it (the trash keeps them until then)."""
    if entity.kind != LANGUAGE:
        return
    session = context.session
    entries = list(
        session.scalars(select(LexiconEntry).where(LexiconEntry.language_id == entity.id))
    )
    for entry in entries:
        session.delete(entry)
    if entries:
        session.flush()
        SearchIndexer(context).remove_documents(DOC_TYPE, [entry.id for entry in entries])


type ImportField = Literal[
    "headword",
    "romanization",
    "pronunciation",
    "part_of_speech",
    "definitions",
    "tags",
    "etymology",
    "notes",
]
