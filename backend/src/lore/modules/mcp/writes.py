"""The write tools (``docs/architecture/mcp.md`` §5, Writing): only with ``access = author`` and
``writes = on``, never on a read-only server.

Each call is one transaction and one changeset through the services (rule 6), with ``origin =
"mcp"`` and a label naming the tool and the client; it is never merged into an earlier changeset,
so ``undo_last`` undoes exactly one call. The consistency engine runs at the commit: a refusal
comes back as a tool error with the findings. No tool deletes entities (trash and purge stay in
the app); ``remove_link`` moves a link to the trash.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import and_, or_, select

from lore.chronology.schema import (
    BaseDuration,
    DurationEnd,
    InstantEnd,
    RelativeAnchor,
    SlotRef,
    TimePoint,
    TimePointEnd,
    UnknownEnd,
)
from lore.core.entities.schemas import (
    MAX_NAME_LENGTH,
    AliasIn,
    EntityCreate,
    EntityOut,
    EntityUpdate,
)
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.facts.schemas import FactCreate
from lore.core.facts.service import Facts
from lore.core.history.models import Changeset
from lore.core.history.service import HistoryService
from lore.core.links.catalog import LinkTypeCatalog
from lore.core.links.models import Link
from lore.core.links.schemas import LinkCreate
from lore.core.links.service import LinkService
from lore.core.modules.service import enabled_modules
from lore.core.time.dimensions import DIMENSION, TIMELINE
from lore.core.time.events import EVENT
from lore.core.time.resolve import BASE, Resolver
from lore.modules.mcp.dates import DateIn, Resolved
from lore.modules.mcp.markdown import to_rich_text
from lore.modules.mcp.tools import Arguments, EntityRef, Id, Reads, Tool

MCP = "mcp"

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)
]
Markdown = Annotated[str, Field(max_length=200_000, description="Markdown (stored as rich text).")]
Units = Annotated[str, StringConstraints(pattern=r"^-?(0|[1-9][0-9]*)$", max_length=1000)]
Visibility = Literal["public", "spoiler", "private"]


class RelativeDate(BaseModel):
    """A moment relative to another event's start or end (it moves when that event moves)."""

    model_config = ConfigDict(extra="forbid")

    event: EntityRef = Field(description="The event: id, or exact name or alias.")
    slot: Literal["start", "end"] = "start"
    offset: Units = Field(default="0", description="Base units after it (negative: before).")


type WriteDate = DateIn | RelativeDate


def _point(reads: Reads, value: WriteDate, dimension_id: str, path: str) -> TimePoint:
    """The time point a write stores for a date argument: calendar dates stay calendar anchors
    (typed dates are preserved), relative ones reference the event's slot."""
    if not isinstance(value, RelativeDate):
        point, resolved = reads.dates.point(value, dimension_id=dimension_id, path=path)
        _same_dimension(resolved, dimension_id, path)
        return point
    event = reads.find(value.event)
    if event.kind != EVENT:
        raise _invalid(path, f"{event.name!r} is not an event.")
    anchor = RelativeAnchor(
        kind="relative",
        ref=SlotRef(type=EVENT, id=event.id, slot=value.slot),
        offset=BaseDuration(kind="base", units=value.offset),
    )
    point = TimePoint(anchor=anchor, precision=BASE)
    resolution = Resolver(reads.context, dimension_id, policy=reads.policy).resolve(point)
    if resolution.t is None or resolution.problem is not None:
        message = resolution.problem.message if resolution.problem else "Not a date."
        raise _invalid(path, message)
    return point


def _same_dimension(resolved: Resolved, dimension_id: str, path: str) -> None:
    if resolved.dimension_id not in {None, dimension_id}:
        raise _invalid(path, "The calendar belongs to another dimension.")


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(
        message, errors=[{"path": path, "code": "invalid_value", "message": message}]
    )


def _written(reads: Reads, out: EntityOut) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": out.id,
        "kind": out.kind,
        "name": out.name,
        "uri": reads.uri(out.id),
        "revision": out.revision,
    }
    if out.dimension_id is not None:
        result["dimension_id"] = out.dimension_id
    if out.parent_id is not None:
        result["parent_id"] = out.parent_id
    return result


def _dimension(reads: Reads, ref: str | None) -> str | None:
    return None if ref is None else reads.find_kind(ref, DIMENSION).id


def _timeline(reads: Reads, timeline: str | None, dimension_id: str | None, path: str) -> str:
    """The given timeline (of ``dimension_id``), else the dimension's prime timeline."""
    if timeline is not None:
        found = reads.find_kind(timeline, TIMELINE).id
        if dimension_id is not None and reads.dimension_of_timeline(found) != dimension_id:
            raise _invalid(path, "The timeline belongs to another dimension.")
        return found
    if dimension_id is None:
        raise _invalid(path, "A multiversal entity needs a timeline.")
    prime = reads.timeline_of(None, dimension_id)
    assert prime is not None
    return prime


# --- describe_schema -----------------------------------------------------------------------------


class DescribeSchema(Arguments):
    pass


def describe_schema(reads: Reads, args: DescribeSchema) -> dict[str, Any]:
    """The kinds (with their fields) and link types writes can use."""
    del args
    session, registry = reads.context.session, reads.context.registry
    enabled = enabled_modules(session, registry)
    kinds = []
    for kind in registry.vault_kinds(session, enabled):
        definition = kind.definition
        if definition.capabilities.is_system:
            continue
        kinds.append(
            {
                "key": kind.key,
                "label": definition.label,
                **({"description": definition.description} if definition.description else {}),
                **(
                    {"parents": list(definition.allowed_parents)}
                    if definition.allowed_parents
                    else {}
                ),
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "type": field.type,
                        **({"options": [o.key for o in field.options]} if field.options else {}),
                        **({"multiple": True} if field.multiple else {}),
                        **({"required": True} if field.required else {}),
                        **({"temporal": True} if field.temporal else {}),
                    }
                    for field in kind.fields
                    if not field.archived
                ],
            }
        )
    link_types = []
    for info in LinkTypeCatalog(session, registry, enabled).offered():
        link_type = info.definition
        if link_type.archived:
            continue
        link_types.append(
            {
                "key": link_type.key,
                "label": link_type.label,
                **({"inverse_label": link_type.inverse_label} if link_type.inverse_label else {}),
                "source_kinds": link_type.source_kinds,
                "target_kinds": link_type.target_kinds,
                **({"symmetric": True} if link_type.symmetric else {}),
                "temporal": link_type.temporal,
            }
        )
    return {"kinds": kinds, "link_types": link_types}


# --- create_entity / update_entity ---------------------------------------------------------------


class _EntityFields(Arguments):
    summary: Annotated[str, Field(max_length=2000)] | None = None
    body: Markdown | None = None
    fields: dict[str, Any] | None = Field(
        default=None,
        description="Field values by key (see describe_schema; null removes a value). Temporal "
        "fields change over time: use set_fact.",
    )
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, max_length=100, description="Tag names (replace the entity's tags)."
    )
    aliases: list[Name] | None = Field(
        default=None, max_length=100, description="Other names (replace the entity's aliases)."
    )
    visibility: Visibility | None = None


class CreateEntity(_EntityFields):
    kind: Annotated[str, Field(min_length=1, max_length=100)] = Field(
        description="An entity kind key (see describe_schema). Events: use create_event."
    )
    name: Name
    dimension: EntityRef | None = Field(
        default=None, description="Its dimension (id or name); none: multiversal."
    )
    parent: EntityRef | None = Field(default=None, description="Its parent entity (id or name).")


def _members(reads: Reads, args: _EntityFields) -> dict[str, Any]:
    members: dict[str, Any] = {}
    if args.summary is not None:
        members["summary"] = args.summary
    if args.body is not None:
        members["body"] = to_rich_text(args.body, reads.vault_id)
    if args.fields is not None:
        members["fields"] = args.fields
    if args.tags is not None:
        members["tags"] = args.tags
    if args.aliases is not None:
        members["aliases"] = [AliasIn(alias=alias) for alias in args.aliases]
    if args.visibility is not None:
        members["visibility"] = args.visibility
    return members


def create_entity(reads: Reads, args: CreateEntity) -> dict[str, Any]:
    if args.kind == EVENT:
        raise _invalid("kind", "Create events with create_event.")
    data = EntityCreate(
        kind=args.kind,
        name=args.name,
        dimension_id=_dimension(reads, args.dimension),
        parent_id=None if args.parent is None else reads.find(args.parent).id,
        **_members(reads, args),
    )
    return _written(reads, reads.entities.create(data).entity)


class UpdateEntity(_EntityFields):
    entity: EntityRef = Field(description="The entity: id, or exact name or alias.")
    revision: int = Field(
        description="The revision you read (get_entity): a stale one is a revision_conflict."
    )
    name: Name | None = None
    parent: EntityRef | None = Field(default=None, description="A new parent (id or name).")


def update_entity(reads: Reads, args: UpdateEntity) -> dict[str, Any]:
    entity = reads.find(args.entity)
    members = _members(reads, args)
    if args.name is not None:
        members["name"] = args.name
    if args.parent is not None:
        members["parent_id"] = reads.find(args.parent).id
    data = EntityUpdate(revision=args.revision, **members)
    return _written(reads, reads.entities.update(entity.id, data).entity)


# --- add_link / remove_link ----------------------------------------------------------------------


class AddLink(Arguments):
    link_type: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        description="A link type key or label (see describe_schema)."
    )
    source: EntityRef = Field(description="The source entity: id, or exact name or alias.")
    target: EntityRef = Field(description="The target entity: id, or exact name or alias.")
    role: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    valid_from: WriteDate | None = Field(default=None, description="Holds from then on.")
    valid_to: WriteDate | None = Field(default=None, description="Holds until then (excluded).")
    timeline: EntityRef | None = Field(
        default=None, description="The timeline of the validity (default: the prime timeline)."
    )
    visibility: Visibility = "public"


def _link_type(reads: Reads, wanted: str) -> str:
    session, registry = reads.context.session, reads.context.registry
    offered = LinkTypeCatalog(session, registry, enabled_modules(session, registry)).offered()
    for info in offered:
        if info.key == wanted:
            return info.key
    named = {
        info.key
        for info in offered
        if wanted.casefold()
        in {info.definition.label.casefold(), (info.definition.inverse_label or "").casefold()}
    }
    if len(named) == 1:
        return named.pop()
    if named:
        raise ConflictError(f"Several link types are labelled {wanted!r}: pass a key.")
    raise NotFoundError(f"No link type {wanted!r}: see describe_schema.")


def add_link(reads: Reads, args: AddLink) -> dict[str, Any]:
    source, target = reads.find(args.source), reads.find(args.target)
    members: dict[str, Any] = {}
    if args.valid_from is not None or args.valid_to is not None:
        dimension = source.dimension_id or target.dimension_id
        timeline = _timeline(reads, args.timeline, dimension, "timeline")
        dimension = reads.dimension_of_timeline(timeline)
        members["timeline_id"] = timeline
        for key in ("valid_from", "valid_to"):
            if (value := getattr(args, key)) is not None:
                members[key] = _point(reads, value, dimension, key)
    link = LinkService(
        reads.context.session, reads.context.registry, vault=reads.context.vault
    ).create(
        LinkCreate(
            link_type=_link_type(reads, args.link_type),
            source_id=source.id,
            target_id=target.id,
            role=args.role,
            visibility=args.visibility,
            **members,
        )
    )
    return {
        "id": link.link.id,
        "link_type": link.link.link_type,
        "source_id": link.link.source_id,
        "target_id": link.link.target_id,
    }


class RemoveLink(Arguments):
    link: Id | None = Field(default=None, description="The link's id.")
    link_type: Annotated[str, Field(min_length=1, max_length=200)] | None = Field(
        default=None, description="Or the link's type, source and target."
    )
    source: EntityRef | None = None
    target: EntityRef | None = None


def remove_link(reads: Reads, args: RemoveLink) -> dict[str, Any]:
    service = LinkService(reads.context.session, reads.context.registry, vault=reads.context.vault)
    link_id = args.link
    if link_id is None:
        if args.link_type is None or args.source is None or args.target is None:
            raise _invalid("link", "Pass the link's id, or its link_type, source and target.")
        link_id = _link_between(reads, args.link_type, args.source, args.target)
    removed = service.trash(link_id)
    return {"id": removed.id, "removed": True}


def _link_between(reads: Reads, link_type: str, source: str, target: str) -> str:
    one, other = reads.find(source).id, reads.find(target).id
    ids = list(
        reads.context.session.scalars(
            select(Link.id)
            .where(
                Link.link_type == _link_type(reads, link_type),
                Link.deleted_at.is_(None),
                or_(
                    and_(Link.source_id == one, Link.target_id == other),
                    and_(Link.source_id == other, Link.target_id == one),
                ),
            )
            .limit(11)
        )
    )
    if not ids:
        raise NotFoundError("No such link.")
    if len(ids) > 1:
        raise ConflictError("Several links match: pass the link's id.", context={"ids": ids[:10]})
    return ids[0]


# --- set_fact ------------------------------------------------------------------------------------


class SetFact(Arguments):
    entity: EntityRef = Field(description="The entity: id, or exact name or alias.")
    field: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        description="A temporal field key (see describe_schema), `core.exists` (exists over the "
        "validity) or `core.name` (its name then)."
    )
    value: Any = Field(default=None, description="The value (true for core.exists).")
    valid_from: WriteDate | None = Field(default=None, description="From then (none: always).")
    valid_to: WriteDate | None = Field(default=None, description="Until then, excluded (none: on).")
    timeline: EntityRef | None = Field(
        default=None, description="The timeline it holds in (default: the prime timeline)."
    )
    visibility: Visibility = "public"
    note: Annotated[str, Field(max_length=2000)] | None = None


def set_fact(reads: Reads, args: SetFact) -> dict[str, Any]:
    entity = reads.find(args.entity)
    timeline = _timeline(reads, args.timeline, entity.dimension_id, "timeline")
    dimension = reads.dimension_of_timeline(timeline)
    members: dict[str, Any] = {}
    for key in ("valid_from", "valid_to"):
        if (value := getattr(args, key)) is not None:
            members[key] = _point(reads, value, dimension, key)
    value = True if args.value is None and args.field == "core.exists" else args.value
    data = FactCreate(
        field_key=args.field,
        value=value,
        timeline_id=timeline,
        visibility=args.visibility,
        note=args.note,
        **members,
    )
    fact = Facts(reads.context).create(entity.id, data).fact
    return {
        "id": fact.id,
        "entity_id": entity.id,
        "field": fact.field_key,
        "timeline_id": timeline,
        "valid_from": reads.dates.moment(dimension, _int(fact.valid_from_t)),
        "valid_to": reads.dates.moment(dimension, _int(fact.valid_to_t)),
    }


def _int(value: str | int | None) -> int | None:
    return None if value is None else int(value)


# --- create_event --------------------------------------------------------------------------------


class CreateEvent(Arguments):
    name: Name
    start: WriteDate = Field(
        description='When it starts: a moment, "present", a calendar date, or relative to '
        "another event."
    )
    end: WriteDate | Literal["instant", "unknown"] | None = Field(
        default=None, description="When it ends (excluded); default: an instant."
    )
    duration: Units | None = Field(default=None, description="Or its length in base units.")
    dimension: EntityRef | None = Field(
        default=None, description="Its dimension (default: a calendar date's, or the timeline's)."
    )
    timeline: EntityRef | None = Field(
        default=None, description="Its timeline (default: the dimension's prime)."
    )
    parent: EntityRef | None = Field(default=None, description="The event it is part of.")
    importance: int | None = Field(default=None, ge=1, le=5, description="1-5 (default 3).")
    category: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    summary: Annotated[str, Field(max_length=2000)] | None = None
    body: Markdown | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = None
    visibility: Visibility | None = None


def _event_dimension(reads: Reads, args: CreateEvent) -> str:
    if args.dimension is not None:
        return reads.find_kind(args.dimension, DIMENSION).id
    if args.timeline is not None:
        return reads.dimension_of_timeline(reads.find_kind(args.timeline, TIMELINE).id)
    if args.parent is not None and (parent := reads.find(args.parent)).dimension_id is not None:
        return parent.dimension_id
    if not isinstance(args.start, (str, RelativeDate)):
        calendar = reads.dates.calendar(args.start.calendar, None)
        return calendar.dimension_id
    raise _invalid("dimension", "Pass the event's dimension (or a timeline, or a calendar date).")


def create_event(reads: Reads, args: CreateEvent) -> dict[str, Any]:
    dimension = _event_dimension(reads, args)
    timeline = _timeline(reads, args.timeline, dimension, "timeline")
    ext: dict[str, Any] = {
        "timeline_id": timeline,
        "start": _point(reads, args.start, dimension, "start").model_dump(mode="json"),
    }
    if args.end is not None and args.duration is not None:
        raise _invalid("duration", "Pass an end or a duration, not both.")
    if args.duration is not None:
        end: Any = DurationEnd(
            kind="duration", duration=BaseDuration(kind="base", units=args.duration)
        )
    elif args.end == "unknown":
        end = UnknownEnd(kind="unknown")
    elif args.end is None or args.end == "instant":
        end = InstantEnd(kind="instant")
    else:
        end = TimePointEnd(kind="time_point", time_point=_point(reads, args.end, dimension, "end"))
    ext["end"] = end.model_dump(mode="json")
    if args.importance is not None:
        ext["importance"] = args.importance
    if args.category is not None:
        ext["category"] = args.category
    members: dict[str, Any] = {}
    if args.summary is not None:
        members["summary"] = args.summary
    if args.body is not None:
        members["body"] = to_rich_text(args.body, reads.vault_id)
    if args.tags is not None:
        members["tags"] = args.tags
    if args.visibility is not None:
        members["visibility"] = args.visibility
    data = EntityCreate(
        kind=EVENT,
        name=args.name,
        dimension_id=dimension,
        parent_id=None if args.parent is None else reads.find_kind(args.parent, EVENT).id,
        ext=ext,
        **members,
    )
    out = reads.entities.create(data).entity
    event = out.ext or {}
    return {
        **_written(reads, out),
        "timeline_id": timeline,
        "start": reads.dates.moment(dimension, _int(event.get("start_t"))),
        "end": reads.dates.moment(dimension, _int(event.get("end_t"))),
    }


# --- undo_last -----------------------------------------------------------------------------------


class UndoLast(Arguments):
    pass


def undo_last(reads: Reads, args: UndoLast) -> dict[str, Any]:
    """Undo the newest changeset the MCP tools made that isn't undone yet."""
    del args
    session = reads.context.session
    last = session.scalar(
        select(Changeset)
        .where(Changeset.origin == MCP, Changeset.reverted_by_changeset_id.is_(None))
        .order_by(Changeset.id.desc())
        .limit(1)
    )
    if last is None:
        raise NotFoundError("The MCP tools haven't made a change to undo.")
    summary = last.summary
    result = HistoryService(session, reads.context.registry, reads.context.vault).revert(last.id)
    return {"undone": summary, "changeset_id": last.id, "undo_changeset_id": result.changeset.id}


WRITE_TOOLS: tuple[Tool, ...] = (
    Tool(
        "describe_schema",
        "Describe the schema",
        "The entity kinds (with their fields) and link types the write tools use.",
        DescribeSchema,
        describe_schema,
    ),
    Tool(
        "create_entity",
        "Create an entity",
        "A new entity of a kind (see describe_schema), with its summary, Markdown body, fields, "
        "tags and aliases. Link to entities in the body with [name](lore://…) URIs.",
        CreateEntity,
        create_entity,
        writes=True,
    ),
    Tool(
        "update_entity",
        "Update an entity",
        "Change an entity's name, summary, body, fields, tags, aliases or parent. Pass the "
        "`revision` get_entity gave: a stale one is a revision_conflict.",
        UpdateEntity,
        update_entity,
        writes=True,
    ),
    Tool(
        "add_link",
        "Add a link",
        "A link of a type (see describe_schema) between two entities, optionally valid over a "
        "period of a timeline.",
        AddLink,
        add_link,
        writes=True,
    ),
    Tool(
        "remove_link",
        "Remove a link",
        "Move a link to the trash, by id or by its type, source and target.",
        RemoveLink,
        remove_link,
        writes=True,
    ),
    Tool(
        "set_fact",
        "Set a fact",
        "A value of a temporal field over a period of a timeline (`core.exists`: when the "
        "entity exists; `core.name`: its name then).",
        SetFact,
        set_fact,
        writes=True,
    ),
    Tool(
        "create_event",
        "Create an event",
        "An event on a timeline: its start (a moment, a calendar date, or relative to another "
        "event, which then moves it along), end or duration, parent event, importance, category.",
        CreateEvent,
        create_event,
        writes=True,
    ),
    Tool(
        "undo_last",
        "Undo the last change",
        "Undo the newest change these tools made that isn't undone yet (refused when it was "
        "changed since).",
        UndoLast,
        undo_last,
        writes=True,
    ),
)

__all__ = ["MCP", "WRITE_TOOLS"]
