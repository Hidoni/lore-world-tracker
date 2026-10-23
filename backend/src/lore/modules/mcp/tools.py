"""The read tools (``docs/architecture/mcp.md`` §5): what an assistant can ask of the vault.

Every tool reads through the services with the call's ``VisibilityPolicy`` (the readers' one
unless the author grants more), so it sees what the API would show the same reader. Results are
compact JSON, capped at ``limit`` (at most ``MAX_LIMIT``) and paged with ``cursor``.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lore.core.entities.models import Entity
from lore.core.entities.queries import EntityQueries
from lore.core.entities.schemas import ID_PATTERN, EntitySummary
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.facts.state import EntityStates, existence_of
from lore.core.links.service import LinkService
from lore.core.markdown.export import entity_note
from lore.core.modules.spec import VaultContext
from lore.core.search.queries import SearchQueries
from lore.core.search.schemas import Snippet
from lore.core.time.calendars import CALENDAR
from lore.core.time.dimensions import DIMENSION, TIMELINE, prime_timeline, timeline_tree
from lore.core.time.events import EVENT
from lore.core.time.models import Timeline
from lore.core.time.schemas import TimelineNode
from lore.core.time.state import resolve_as_of
from lore.core.time.window import WindowItem, WindowQuery, timeline_window
from lore.core.visibility import VisibilityPolicy
from lore.modules.mcp.dates import CalendarDate, DateIn, Dates

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
# events_between reads one timeline window this wide (its items are capped at 2000).
WINDOW_PX = 8000

EntityRef = Annotated[str, Field(min_length=1, max_length=500)]
Id = Annotated[str, Field(pattern=ID_PATTERN)]
Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT, description="Results at most.")]
Cursor = Annotated[
    str | None, Field(max_length=4096, description="`next_cursor` of the previous page.")
]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Reads:
    """What a tool call works with: the vault (a read transaction, or a write transaction for
    the write tools) and the call's policy."""

    context: VaultContext
    policy: VisibilityPolicy
    dates: Dates = field(init=False)

    def __post_init__(self) -> None:
        self.dates = Dates(self.context, self.policy)
        self.entities = EntityService(self.context, self.policy)

    @property
    def vault_id(self) -> str:
        return self.context.vault.id

    def uri(self, entity_id: str) -> str:
        return entity_uri(self.vault_id, entity_id)

    def queries(self, *, timeline: str | None = None, **existence: Any) -> EntityQueries:
        reader = None
        if existence.get("at") is not None:
            reader = existence_of(self.context, self.policy, timeline_id=timeline, **existence)
        return EntityQueries(self.entities, reader, timeline)

    def visible(self, entity_id: str, kind: str | None = None) -> Entity:
        """A live entity the policy shows (of ``kind``), else ``404``."""
        entity = self.entities.load_visible(entity_id)
        if entity.deleted_at is not None or (kind is not None and entity.kind != kind):
            raise NotFoundError(f"No {kind or 'entity'} {entity_id}.")
        return entity

    def find(self, ref: str) -> Entity:
        """An entity by id, or by exact name or alias (ignoring case); ``409 ambiguous`` when
        several entities have it."""
        if self._is_id(ref):
            try:
                return self.visible(ref)
            except NotFoundError:
                pass
        wanted = ref.strip().casefold()
        candidates = self.queries().list_entities(q=ref.strip(), limit=MAX_LIMIT).items
        named = [c for c in candidates if c.name.casefold() == wanted]
        if not named:
            named = [
                c
                for c in candidates
                if any(
                    alias.alias.casefold() == wanted
                    for alias in self.entities.to_out(self.visible(c.id)).aliases
                )
            ]
        if not named:
            raise NotFoundError(f"No entity is named {ref!r}: try search.")
        if len(named) > 1:
            listed = ", ".join(f"{c.name} ({c.kind}, {c.id})" for c in named[:10])
            raise ConflictError(
                f"Several entities are named {ref!r}: {listed}. Pass an id.",
                context={"ids": [c.id for c in named]},
            )
        return self.visible(named[0].id)

    def find_kind(self, ref: str, kind: str) -> Entity:
        """``find`` among the entities of ``kind``."""
        if self._is_id(ref):
            return self.visible(ref, kind)
        candidates = self.queries().list_entities(kinds=[kind], q=ref.strip(), limit=MAX_LIMIT)
        named = [c for c in candidates.items if c.name.casefold() == ref.strip().casefold()]
        if not named:
            return self.visible(self.find(ref).id, kind)
        if len(named) > 1:
            raise ConflictError(
                f"Several {kind}s are named {ref!r}: pass an id.",
                context={"ids": [c.id for c in named]},
            )
        return self.visible(named[0].id)

    @staticmethod
    def _is_id(ref: str) -> bool:
        return re.match(ID_PATTERN, ref) is not None

    def timeline_of(self, timeline: str | None, dimension: str | None) -> str | None:
        """The timeline a time-bound read uses: the given one, else the prime timeline of
        ``dimension``."""
        if timeline is not None:
            return self.visible(timeline, TIMELINE).id
        if dimension is None:
            return None
        prime = prime_timeline(self.context.session, dimension)
        if prime is None or not self.policy.visible_ids(self.context.session, [prime.id]):
            raise NotFoundError(f"The dimension {dimension} has no timeline you can see.")
        return prime.id

    def dimension_of_timeline(self, timeline_id: str) -> str:
        dimension = self.context.session.scalar(
            select(Timeline.dimension_id).where(Timeline.entity_id == timeline_id)
        )
        assert dimension is not None
        return dimension


def entity_uri(vault_id: str, entity_id: str) -> str:
    return f"lore://{vault_id}/entities/{entity_id}"


def _page(limit: int) -> int:
    return min(limit, MAX_LIMIT)


def _summary(item: EntitySummary) -> dict[str, Any]:
    out: dict[str, Any] = {"id": item.id, "kind": item.kind, "name": item.name}
    if item.dimension_id is not None:
        out["dimension_id"] = item.dimension_id
    if item.parent_id is not None:
        out["parent_id"] = item.parent_id
    if item.summary:
        out["summary"] = item.summary
    if item.existence is not None:
        out["existence"] = item.existence
    return out


def _snippet(snippet: Snippet | None) -> str | None:
    if snippet is None:
        return None
    return "".join(f"**{part.text}**" if part.match else part.text for part in snippet.parts)


# --- list_dimensions -----------------------------------------------------------------------------


class ListDimensions(Arguments):
    limit: Limit = DEFAULT_LIMIT
    cursor: Cursor = None


def _timelines(nodes: Sequence[TimelineNode]) -> Iterator[TimelineNode]:
    for node in nodes:
        yield node
        yield from _timelines(node.children)


def list_dimensions(reads: Reads, args: ListDimensions) -> dict[str, Any]:
    page = reads.queries().list_entities(
        kinds=[DIMENSION], cursor=args.cursor, limit=_page(args.limit)
    )
    items: list[dict[str, Any]] = []
    for item in page.items:
        entity = reads.visible(item.id, DIMENSION)
        ext = reads.entities.to_out(entity).ext or {}
        present = ext.get("present_t")
        calendars = reads.queries().list_entities(
            kinds=[CALENDAR], dimension=item.id, include_multiversal=False, limit=MAX_LIMIT
        )
        tree = timeline_tree(reads.context, reads.policy, item.id)
        items.append(
            {
                **_summary(item),
                "base_unit": ext.get("base_unit"),
                "duration": ext.get("duration"),
                "present": reads.dates.moment(item.id, None if present is None else int(present)),
                "default_calendar_id": ext.get("default_calendar_id"),
                "calendars": [{"id": c.id, "name": c.name} for c in calendars.items],
                "timelines": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "prime": node.is_prime,
                        **(
                            {"parent_timeline_id": node.parent_timeline_id}
                            if node.parent_timeline_id
                            else {}
                        ),
                        **(
                            {"branch_point": reads.dates.moment(item.id, node.branch_t)}
                            if node.branch_t is not None
                            else {}
                        ),
                    }
                    for node in _timelines(tree.items)
                    if not node.trashed
                ],
            }
        )
    return {"items": items, "next_cursor": page.next_cursor}


# --- search --------------------------------------------------------------------------------------


class Search(Arguments):
    query: Annotated[str, Field(min_length=1, max_length=500)] = Field(
        description='Words match word beginnings; "quoted phrases" match exactly; OR between '
        "alternatives; -word or NOT word leaves out; parentheses group."
    )
    kinds: list[str] | None = Field(default=None, description="Entity kinds (any of them).")
    dimension: Id | None = Field(default=None, description="Entities of this dimension.")
    timeline: Id | None = Field(
        default=None, description="A branch timeline: also its branch-only entities."
    )
    limit: Limit = DEFAULT_LIMIT
    cursor: Cursor = None


def search(reads: Reads, args: Search) -> dict[str, Any]:
    queries = SearchQueries(
        reads.context.session, reads.context.registry, reads.policy, args.timeline
    )
    page = queries.search(
        args.query,
        kinds=args.kinds,
        dimension=args.dimension,
        cursor=args.cursor,
        limit=_page(args.limit),
    )
    items = []
    for hit in page.items:
        out: dict[str, Any] = {"entity_id": hit.entity_id, "kind": hit.kind, "name": hit.name}
        if hit.doc_type != "entity":
            out["document"] = {"type": hit.doc_type, "id": hit.doc_id}
        if hit.dimension_id is not None:
            out["dimension_id"] = hit.dimension_id
        if (snippet := _snippet(hit.snippet)) is not None:
            out["snippet"] = snippet
        items.append(out)
    return {"items": items, "next_cursor": page.next_cursor}


# --- get_entity ----------------------------------------------------------------------------------


class GetEntity(Arguments):
    entity: EntityRef = Field(description="An entity id, or its exact name or alias.")
    at: DateIn | None = Field(
        default=None, description="Also its state then: existence, fields and links valid then."
    )
    timeline: Id | None = Field(
        default=None,
        description="The timeline of `at` (default: the prime timeline of the entity's "
        "dimension; needed for multiversal entities).",
    )


def get_entity(reads: Reads, args: GetEntity) -> dict[str, Any]:
    entity = reads.find(args.entity)
    out = reads.entities.to_out(entity)
    result: dict[str, Any] = {
        "id": out.id,
        "kind": out.kind,
        "name": out.name,
        "uri": reads.uri(out.id),
        "revision": out.revision,
    }
    for key in ("dimension_id", "parent_id", "summary"):
        if value := getattr(out, key):
            result[key] = value
    if out.aliases:
        result["aliases"] = [alias.alias for alias in out.aliases]
    if out.tags:
        result["tags"] = [tag.name for tag in out.tags]
    result["markdown"] = entity_note(
        reads.context, reads.policy, entity.id, lambda id_, label: f"[{label}]({reads.uri(id_)})"
    )
    if args.at is not None:
        result["state"] = _state(reads, entity, args)
    return result


def _state(reads: Reads, entity: Entity, args: GetEntity) -> dict[str, Any]:
    assert args.at is not None
    timeline = reads.timeline_of(args.timeline, entity.dimension_id)
    dimension = None if timeline is None else reads.dimension_of_timeline(timeline)
    at = reads.dates.resolve(args.at, dimension_id=dimension, path="at")
    if timeline is None:
        if at.dimension_id is None:
            raise InvalidInputError(
                "A multiversal entity's state needs a timeline (or a calendar date).",
                errors=[{"path": "timeline", "code": "required", "message": "Required."}],
            )
        timeline = reads.timeline_of(None, at.dimension_id)
        assert timeline is not None
        dimension = at.dimension_id
    state = EntityStates(reads.context, reads.policy).state(
        entity, timeline_id=timeline, at=str(at.t)
    )
    as_of = resolve_as_of(reads.context, reads.policy, timeline, str(at.t))
    links = LinkService(
        reads.context.session, reads.context.registry, reads.policy, reads.context.vault
    ).entity_links(entity.id, as_of=as_of)
    return {
        "timeline_id": timeline,
        "at": reads.dates.moment(dimension, at.t),
        "existence": state.existence,
        "name": state.name,
        "fields": {
            key: value.value
            if value.certainty == "certain"
            else {"value": value.value, "certainty": value.certainty}
            for key, value in state.fields.items()
        },
        "links": [
            {
                "label": item.label,
                "entity": {"id": item.other.id, "kind": item.other.kind, "name": item.other.name},
                **({"role": item.link.role} if item.link.role else {}),
                **({"certainty": item.certainty} if item.certainty == "possible" else {}),
            }
            for item in links.items
        ],
    }


# --- list_entities -------------------------------------------------------------------------------


class ListEntities(Arguments):
    kinds: list[str] | None = Field(default=None, description="Entity kinds (any of them).")
    tags: list[str] | None = Field(default=None, description="Tag names or ids (all of them).")
    dimension: Id | None = Field(
        default=None, description="Entities of this dimension (and multiversal ones)."
    )
    parent: Id | None = Field(default=None, description="Children of this entity.")
    at: DateIn | None = Field(default=None, description="Only entities existing then.")
    timeline: Id | None = Field(
        default=None, description="The timeline of `at` (default: the dimension's prime)."
    )
    limit: Limit = DEFAULT_LIMIT
    cursor: Cursor = None


def _tag_ids(reads: Reads, tags: Sequence[str]) -> list[str]:
    known = {tag.name.casefold(): tag.id for tag in reads.queries().tags(limit=1000).items}
    ids = set(known.values())
    out = []
    for tag in tags:
        tag_id = tag if tag in ids else known.get(tag.casefold())
        if tag_id is None:
            raise NotFoundError(f"No tag {tag!r}.")
        out.append(tag_id)
    return out


def list_entities(reads: Reads, args: ListEntities) -> dict[str, Any]:
    timeline = reads.timeline_of(args.timeline, args.dimension)
    at: str | None = None
    if args.at is not None:
        dimension = None if timeline is None else reads.dimension_of_timeline(timeline)
        resolved = reads.dates.resolve(args.at, dimension_id=dimension, path="at")
        if timeline is None and resolved.dimension_id is not None:
            timeline = reads.timeline_of(None, resolved.dimension_id)
        if timeline is None:
            raise InvalidInputError(
                "`at` needs a dimension, a timeline or a calendar date.",
                errors=[{"path": "at", "code": "required", "message": "Pass a dimension."}],
            )
        at = str(resolved.t)
    queries = reads.queries(timeline=timeline, at=at, dimension_id=args.dimension)
    page = queries.list_entities(
        kinds=args.kinds,
        dimension=args.dimension,
        parent=args.parent,
        tags=None if args.tags is None else _tag_ids(reads, args.tags),
        cursor=args.cursor,
        limit=_page(args.limit),
    )
    return {"items": [_summary(item) for item in page.items], "next_cursor": page.next_cursor}


# --- events_between ------------------------------------------------------------------------------


class EventsBetween(Arguments):
    start: DateIn = Field(alias="from", description="The range's first moment or date.")
    end: DateIn = Field(alias="to", description="The moment or date after the range (excluded).")
    timeline: Id | None = Field(default=None, description="The timeline (default: the prime).")
    dimension: Id | None = Field(
        default=None, description="Its prime timeline, when no timeline is given."
    )
    parent: Id | None = Field(default=None, description="Only the sub-events of this event.")
    include_series: bool = Field(
        default=True, description="Recurring events as their occurrences in the range."
    )
    limit: Limit = DEFAULT_LIMIT
    cursor: Cursor = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def events_between(reads: Reads, args: EventsBetween) -> dict[str, Any]:
    timeline = reads.timeline_of(args.timeline, args.dimension)
    dimension = None if timeline is None else reads.dimension_of_timeline(timeline)
    start = reads.dates.resolve(args.start, dimension_id=dimension, path="from")
    end = reads.dates.resolve(args.end, dimension_id=dimension or start.dimension_id, path="to")
    if timeline is None:
        dimension = start.dimension_id or end.dimension_id
        timeline = reads.timeline_of(None, dimension)
    if timeline is None or dimension is None:
        raise InvalidInputError(
            "Pass a timeline, a dimension, or calendar dates.",
            errors=[{"path": "timeline", "code": "required", "message": "Required."}],
        )
    if args.parent is not None:
        reads.visible(args.parent, EVENT)
    window = timeline_window(
        reads.context,
        reads.policy,
        timeline,
        WindowQuery(
            start=start.t,
            end=end.t,
            px=WINDOW_PX,
            parent=args.parent,
            include_series=args.include_series,
        ),
    )
    shown = {item.entity_id for item in window.items if item.occurrence_key is None}
    sub_events: dict[str, int] = {}
    listed = []
    for item in window.items:
        if item.parent_id is not None and item.parent_id in shown and item.parent_id != args.parent:
            sub_events[item.parent_id] = sub_events.get(item.parent_id, 0) + 1
        else:
            listed.append(item)
    listed.sort(key=lambda i: (i.start_t is None, i.start_t or 0, i.name, i.occurrence_key or ""))
    offset = _offset(args.cursor)
    page = listed[offset : offset + _page(args.limit)]
    dates = reads.dates
    items = [_event(dates, dimension, item, args.parent, sub_events) for item in page]
    more = offset + len(page) < len(listed)
    result: dict[str, Any] = {
        "timeline_id": timeline,
        "from": dates.moment(dimension, start.t),
        "to": dates.moment(dimension, end.t),
        "items": items,
        "next_cursor": str(offset + len(page)) if more else None,
    }
    if window.series_bands:
        result["busy_series"] = [
            {
                "id": band.entity_id,
                "name": band.name,
                "estimated_occurrences": band.estimated_count,
            }
            for band in window.series_bands
        ]
    if window.culled:
        result["left_out"] = window.culled
    return result


def _event(
    dates: Dates, dimension: str, item: WindowItem, parent: str | None, sub_events: dict[str, int]
) -> dict[str, Any]:
    end: Any = item.end_kind
    if item.end_kind not in {"instant", "unknown"}:
        end = dates.moment(
            dimension, item.end_t, item.end_precision, approximate=item.end_approximate
        )
    out: dict[str, Any] = {
        "id": item.entity_id,
        "name": item.name,
        "start": dates.moment(
            dimension, item.start_t, item.start_precision, approximate=item.start_approximate
        ),
        "end": end,
        "importance": item.importance,
    }
    if item.category:
        out["category"] = item.category
    if item.occurrence_key is not None:
        out["occurrence"] = item.occurrence_key
    if item.parent_id is not None and item.parent_id != parent:
        out["parent_id"] = item.parent_id
    if count := sub_events.get(item.entity_id):
        out["sub_events"] = count
    return out


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdigit():
        raise InvalidInputError(
            "Not a cursor of this tool.",
            errors=[{"path": "cursor", "code": "invalid_value", "message": "Bad cursor."}],
        )
    return int(cursor)


# --- convert_date --------------------------------------------------------------------------------


class ConvertDate(Arguments):
    date: DateIn = Field(description="A moment, or a calendar date to convert.")
    dimension: Id | None = Field(
        default=None, description="The dimension of a moment (a calendar date has its own)."
    )
    calendars: list[str] | None = Field(
        default=None,
        max_length=20,
        description="Calendars to show it in, by id or name (default: all of the dimension's).",
    )


def convert_date(reads: Reads, args: ConvertDate) -> dict[str, Any]:
    from lore.core.time.batch import convert_batch  # noqa: PLC0415
    from lore.core.time.schemas import ConvertIn  # noqa: PLC0415
    from lore.core.time.specs import ABSOLUTE_CALENDAR_ID  # noqa: PLC0415

    if args.dimension is not None:
        reads.visible(args.dimension, DIMENSION)
    resolved = reads.dates.resolve(args.date, dimension_id=args.dimension, path="date")
    dimension = resolved.dimension_id or args.dimension
    if dimension is None:
        raise InvalidInputError(
            "A moment needs its dimension.",
            errors=[{"path": "dimension", "code": "required", "message": "Required."}],
        )
    if args.calendars is None:
        listed = reads.queries().list_entities(
            kinds=[CALENDAR], dimension=dimension, include_multiversal=False, limit=19
        )
        calendars = [item.id for item in listed.items]
    else:
        calendars = [reads.dates.calendar(name, dimension).entity_id for name in args.calendars]
    calendars = [*calendars, ABSOLUTE_CALENDAR_ID]
    names = {
        row.id: row.name
        for row in reads.context.session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(calendars))
        )
    }
    converted = convert_batch(
        reads.context,
        reads.policy,
        ConvertIn(dimension_id=dimension, moments=[resolved.t], calendars=calendars),
    )
    return {
        "t": str(resolved.t),
        "dimension_id": dimension,
        "dates": [
            {
                "calendar_id": result.calendar_id,
                "calendar": names.get(result.calendar_id, "Absolute"),
                **({"fields": result.fields} if result.fields is not None else {}),
                **({"date": result.display} if result.display is not None else {}),
                **({"error": result.error.message} if result.error is not None else {}),
            }
            for result in converted.items[0].results
        ],
    }


# --- the catalog ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    arguments: type[Arguments]
    run: Callable[[Reads, Any], dict[str, Any]]
    writes: bool = False  # runs in a write transaction (mcp.md §5, Writing)


READ_TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_dimensions",
        "List dimensions",
        "The world's dimensions with their time spec, present, calendars and timelines (the "
        "prime timeline first). Start here: dates and timelines belong to a dimension.",
        ListDimensions,
        list_dimensions,
    ),
    Tool(
        "search",
        "Search",
        "Full-text search over names, aliases, summaries, bodies and fields, best matches "
        "first, with snippets (matches in **bold**).",
        Search,
        search,
    ),
    Tool(
        "get_entity",
        "Get an entity",
        "An entity by id or exact name or alias: its note as Markdown (properties, body, facts, "
        "links) and, with `at`, its state then (existence, fields, links valid then).",
        GetEntity,
        get_entity,
    ),
    Tool(
        "list_entities",
        "List entities",
        "Entities by kind, tag, dimension or parent, by name; with `at`, only those existing then.",
        ListEntities,
        list_entities,
    ),
    Tool(
        "events_between",
        "Events between dates",
        "The events of a timeline overlapping [from, to), by start, with their dates in the "
        "dimension's default calendar. Sub-events of a listed event are counted in its "
        "`sub_events` (list them with `parent`); recurring events appear as occurrences.",
        EventsBetween,
        events_between,
    ),
    Tool(
        "convert_date",
        "Convert a date",
        "A calendar date as a moment, and a moment as a date in each of its dimension's calendars.",
        ConvertDate,
        convert_date,
    ),
)

__all__ = ["READ_TOOLS", "CalendarDate", "Reads", "Tool", "entity_uri"]
