"""Per-timeline notes and the branch diff (``time-model.md`` §4.4, §4.6; #115). The branches
module is the API (``/m/branches/notes``, ``/m/branches/timelines/{id}/diff``).

- **Notes:** a branch's own rich text about an entity, next to the shared page body: one per
  entity and branch (not a prime timeline), for an entity the branch shows (§4.6, of its
  dimension or multiversal). Reading one that doesn't exist gives an empty note (revision 0).
  Writing checks the revision (``409 revision_conflict``) and an empty body deletes the note.
  Readers see the body filtered (``filter_richtext``) and ``404`` for an entity or timeline they
  can't see.
- **Diff against the parent:** what the branch created (its own records), what it overrode
  (before and after) and the inherited records spanning its cut-off it didn't override, for
  events, facts and links. Records whose entity, timeline or row the policy hides are left out.
  Each list is capped at ``limit`` (``truncated``).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.facts.models import EntityFact
from lore.core.links.models import Link
from lore.core.richtext import SCHEMA_VERSION as RICHTEXT_SCHEMA_VERSION
from lore.core.richtext.schema import validate_document
from lore.core.time.models import EntityTimelineNote, Event, Timeline
from lore.core.time.timeline_view import TimelineView
from lore.core.types import MomentStr
from lore.core.visibility import VisibilityPolicy


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code="invalid_value",
                                                        message=message)])  # fmt: skip


def _timeline(session: Session, policy: VisibilityPolicy, timeline_id: str) -> Timeline:
    """A live timeline the policy shows (``404`` otherwise)."""
    entity = session.get(Entity, timeline_id)
    row = session.get(Timeline, timeline_id)
    if (
        entity is None
        or row is None
        or entity.deleted_at is not None
        or not policy.visible_ids(session, [timeline_id])
    ):
        raise NotFoundError(f"No timeline {timeline_id}.")
    return row


# --- notes ---------------------------------------------------------------------------------------


class NoteOut(BaseModel):
    entity_id: str
    timeline_id: str
    body: dict[str, Any] | None = Field(description="Rich text; null when there is no note.")
    revision: int = Field(description="0 when there is no note yet.")
    updated_at: datetime | None = None


class NoteIn(BaseModel):
    body: dict[str, Any] | None = Field(description="Rich text; null or empty deletes the note.")
    revision: int = Field(description="The revision the edit is based on (0 for a new note).")


def _note_target(context: Any, policy: VisibilityPolicy, entity_id: str, timeline_id: str
                 ) -> tuple[Entity, Timeline]:  # fmt: skip
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    entity = EntityService(context, policy).load_visible(entity_id)
    timeline = _timeline(context.session, policy, timeline_id)
    if timeline.parent_timeline_id is None:
        raise _invalid("timeline_id", "Notes belong to branches: the prime is the page itself.")
    if entity.dimension_id is not None and entity.dimension_id != timeline.dimension_id:
        raise _invalid("timeline_id", "The timeline isn't one of the entity's dimension.")
    if not TimelineView.for_timeline(context.session, timeline_id).shows_entity(
        entity.origin_timeline_id
    ):
        raise NotFoundError(f"No entity {entity_id} in that timeline.")
    return entity, timeline


def _note_out(
    context: Any, policy: VisibilityPolicy, entity_id: str, timeline_id: str,
    row: EntityTimelineNote | None,
) -> NoteOut:  # fmt: skip
    if row is None:
        return NoteOut(entity_id=entity_id, timeline_id=timeline_id, body=None, revision=0)
    handlers = context.registry.richtext_handlers()
    body = policy.filter_richtext(context.session, row.body, handlers)
    return NoteOut(entity_id=entity_id, timeline_id=timeline_id, body=body,
                   revision=row.revision, updated_at=row.updated_at)  # fmt: skip


def _find(session: Session, entity_id: str, timeline_id: str) -> EntityTimelineNote | None:
    return session.scalar(
        select(EntityTimelineNote).where(
            EntityTimelineNote.entity_id == entity_id,
            EntityTimelineNote.timeline_id == timeline_id,
        )
    )


def read_note(context: Any, policy: VisibilityPolicy, entity_id: str, timeline_id: str
              ) -> NoteOut:  # fmt: skip
    _note_target(context, policy, entity_id, timeline_id)
    row = _find(context.session, entity_id, timeline_id)
    return _note_out(context, policy, entity_id, timeline_id, row)


def _empty(body: dict[str, Any] | None) -> bool:
    if body is None:
        return True
    content = body.get("content") or []
    return all(node.get("type") == "paragraph" and not node.get("content") for node in content)


def write_note(context: Any, policy: VisibilityPolicy, entity_id: str, timeline_id: str,
               data: NoteIn) -> NoteOut:  # fmt: skip
    session = context.session
    _note_target(context, policy, entity_id, timeline_id)
    row = _find(session, entity_id, timeline_id)
    current = 0 if row is None else row.revision
    if data.revision != current:
        raise RevisionConflictError(
            f"The note was changed meanwhile (revision {current}, the edit is based on "
            f"{data.revision}).",
            context={"current": _note_out(context, policy, entity_id, timeline_id, row)
                     .model_dump(mode="json")},
        )  # fmt: skip
    if _empty(data.body):
        if row is not None:
            session.delete(row)
            session.flush()
        return _note_out(context, policy, entity_id, timeline_id, None)
    body = validate_document(data.body, context.registry.richtext_handlers(), path="body")
    if row is None:
        row = EntityTimelineNote(
            entity_id=entity_id,
            timeline_id=timeline_id,
            body=body,
            body_schema_version=RICHTEXT_SCHEMA_VERSION,
            revision=1,
        )
        session.add(row)
    else:
        row.body = body
        row.body_schema_version = RICHTEXT_SCHEMA_VERSION
        row.revision += 1
        row.updated_at = utc_now()
    session.flush()
    return _note_out(context, policy, entity_id, timeline_id, row)


# --- the diff ------------------------------------------------------------------------------------


class DiffRecord(BaseModel):
    record_type: str = Field(description="`event`, `fact` or `link`.")
    id: str = Field(description="The row (for an override: the override row).")
    root_id: str | None = Field(description="An override's root row; null otherwise.")
    entity_id: str = Field(description="The event, the fact's entity, the link's source.")
    name: str = Field(description="That entity's name.")
    detail: str | None = Field(description="A fact's field key, a link's type.")
    start_t: MomentStr | None
    end_t: MomentStr | None
    before: dict[str, Any] | None = Field(
        default=None, description="Overrides: what the root has (only what differs)."
    )
    after: dict[str, Any] | None = Field(
        default=None, description="Overrides: what the branch has instead."
    )


class BranchDiff(BaseModel):
    timeline_id: str
    against_id: str = Field(description="The parent timeline.")
    branch_t: MomentStr | None
    created: list[DiffRecord]
    overridden: list[DiffRecord]
    inherited_spanning: list[DiffRecord] = Field(
        description="Inherited records spanning the branch point that the branch didn't override."
    )
    truncated: bool


@dataclass(frozen=True)
class _Table:
    record_type: str
    model: Any
    start: str
    end: str
    owner: str
    detail: str | None
    compared: tuple[str, ...]
    open_bounds: bool = True


_TABLES = (
    _Table("event", Event, "start_t", "end_t", "entity_id", None,
           ("end_t", "recurrence", "series_end_t"), open_bounds=False),
    _Table("fact", EntityFact, "valid_from_t", "valid_to_t", "entity_id", "field_key",
           ("value", "valid_to_t")),
    _Table("link", Link, "valid_from_t", "valid_to_t", "source_id", "link_type",
           ("role", "data", "valid_to_t")),
)  # fmt: skip


def _str(value: Any) -> Any:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


@dataclass
class _Lists:
    limit: int
    created: list[DiffRecord] = field(default_factory=list)
    overridden: list[DiffRecord] = field(default_factory=list)
    spanning: list[DiffRecord] = field(default_factory=list)
    truncated: bool = False

    def add(self, target: list[DiffRecord], record: DiffRecord) -> None:
        if len(target) >= self.limit:
            self.truncated = True
        else:
            target.append(record)


def _compared(table: _Table, row: Any, entity: Entity, facts: Any) -> dict[str, Any]:
    """The compared values of a row, as the request may see them (a fact's value as the facts
    API shows it: rich text filtered, time points as moments for readers)."""
    values = {k: _str(getattr(row, k)) for k in table.compared}
    if table.record_type == "fact":
        [out] = facts.out_many(entity, [row])
        values["value"] = out.value
    return values


def _shown_rows(session: Session, policy: VisibilityPolicy, table: _Table, statement: Any,
                facts: Any) -> Iterator[tuple[Any, Entity]]:  # fmt: skip
    """Rows of ``statement`` the policy shows, with their owning entity (facts: of a field
    the request sees)."""
    model = table.model
    owner = getattr(model, table.owner)
    statement = statement.join(Entity, Entity.id == owner).where(
        Entity.deleted_at.is_(None), *policy.entities(Entity)
    ).add_columns(Entity)  # fmt: skip
    if hasattr(model, "deleted_at"):
        statement = statement.where(model.deleted_at.is_(None))
    statement = statement.where(*policy.entity_ref(model.timeline_id))
    if table.record_type == "fact":
        statement = statement.where(*policy.rows(model))
    elif table.record_type == "link":
        statement = statement.where(*policy.links(model))
    for row, entity in session.execute(statement):
        if table.record_type != "fact" or facts.field_shown(entity, row.field_key):
            yield row, entity


def _record(table: _Table, row: Any, entity: Entity, **extra: Any) -> DiffRecord:
    return DiffRecord(
        record_type=table.record_type,
        id=row.id,
        root_id=getattr(row, "overrides_id", None),
        entity_id=entity.id,
        name=entity.name,
        detail=None if table.detail is None else getattr(row, table.detail),
        start_t=getattr(row, table.start),
        end_t=getattr(row, table.end),
        **extra,
    )


def _spans(table: _Table, row: Any, cutoff: int) -> bool:
    start, end = getattr(row, table.start), getattr(row, table.end)
    if table.record_type == "event" and row.recurrence is not None:
        end = row.series_end_t
    starts_before = start is None or start < cutoff
    return starts_before and (end is None or end > cutoff)


def branch_diff(
    context: Any, policy: VisibilityPolicy, timeline_id: str, *, limit: int = 500
) -> BranchDiff:
    session = context.session
    timeline = _timeline(session, policy, timeline_id)
    if timeline.parent_timeline_id is None:
        raise _invalid("timeline_id", "A prime timeline has no parent to compare with.")
    view = TimelineView.for_timeline(session, timeline_id)
    lists = _Lists(limit)
    from lore.core.facts.service import Facts  # noqa: PLC0415 (import cycle)

    facts = Facts(context, policy)
    for table in _TABLES:
        model = table.model
        own = select(model).where(model.timeline_id == timeline_id)
        if table.record_type == "event":
            own = own.where(model.occurrence_key.is_(None))
        for row, entity in _shown_rows(session, policy, table, own, facts):
            if row.overrides_id is None:
                lists.add(lists.created, _record(table, row, entity))
                continue
            root = session.get(model, row.overrides_id)
            if root is None:
                continue
            before = _compared(table, root, entity, facts)
            after = _compared(table, row, entity, facts)
            changed = [k for k in table.compared if before[k] != after[k]]
            lists.add(lists.overridden, _record(
                table, row, entity, before={k: before[k] for k in changed},
                after={k: after[k] for k in changed},
            ))  # fmt: skip
        # Winners from ancestors (not overridden in this branch) spanning their cut-off.
        cutoffs = {e.timeline_id: e.cutoff for e in view.lineage if e.depth > 0}
        inherited = view.select(model).where(model.timeline_id.in_(list(cutoffs)))
        if table.record_type == "event":
            inherited = inherited.where(model.occurrence_key.is_(None))
        for row, entity in _shown_rows(session, policy, table, inherited, facts):
            cutoff = cutoffs.get(row.timeline_id)
            if cutoff is not None and _spans(table, row, cutoff):
                lists.add(lists.spanning, _record(table, row, entity))
    for found in (lists.created, lists.overridden, lists.spanning):
        found.sort(key=lambda r: (r.record_type, r.start_t is not None, r.start_t or 0, r.name))
    return BranchDiff(
        timeline_id=timeline_id,
        against_id=str(timeline.parent_timeline_id),
        branch_t=timeline.branch_t,
        created=lists.created,
        overridden=lists.overridden,
        inherited_spanning=lists.spanning,
        truncated=lists.truncated,
    )


def notes_of_timeline(session: Session, timeline_ids: Iterable[str]) -> int:
    """How many notes the timelines have (for the delete confirmation)."""
    return len(
        session.scalars(
            select(EntityTimelineNote.id).where(
                EntityTimelineNote.timeline_id.in_(list(timeline_ids))
            )
        ).all()
    )


__all__ = [
    "BranchDiff",
    "DiffRecord",
    "NoteIn",
    "NoteOut",
    "branch_diff",
    "read_note",
    "write_note",
]
