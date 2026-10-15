"""The worldlines module's consistency rules (``docs/modules/worldlines.md``, ``time-model.md``
§11.4). They look at entities with explicit segments only (an implicit worldline is the
existence, which ``core.event.participant_not_existing`` checks):

- ``worldlines.absent_participant`` (warning): no segment covers the event's start in a timeline
  that sees it (or the segment the link chose doesn't).
- ``worldlines.ambiguous_participation`` (warning): several segments cover it and the link
  doesn't choose one (``data.segment_id``).
- ``worldlines.jump_event_mismatch`` (warning): a segment's departure event doesn't span its
  end, or its arrival event its start (or the event is in another dimension).
- ``worldlines.self_encounter`` (off, informational): two segments of an entity in the same
  timeline overlap (sharing only an end doesn't count): it is there twice and may meet itself.
- ``worldlines.causal_loop`` (off, informational): events that cause each other through
  ``core.causes`` (a cycle: the bootstrap paradox), one finding per loop.

The last three read the home rows of segments and events (stored moments), not overrides.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence

from sqlalchemy import or_, select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.models import Event, WorldlineSegment
from lore.core.visibility import AUTHOR
from lore.modules.worldlines.service import Worldlines

ABSENT = "worldlines.absent_participant"
AMBIGUOUS = "worldlines.ambiguous_participation"
MISMATCH = "worldlines.jump_event_mismatch"
ENCOUNTER = "worldlines.self_encounter"
LOOP = "worldlines.causal_loop"
PARTICIPANT = "core.participant"
CAUSES = "core.causes"
_BATCH = 5000
NAMED = 5  # events a loop's message names


def _chunks(ids: Iterable[str]) -> Iterator[list[str]]:
    wanted = sorted(set(ids))
    for start in range(0, len(wanted), _BATCH):
        yield wanted[start : start + _BATCH]


def _travelers(ctx: RuleContext, subjects: Iterable[str] | None) -> list[str]:
    """Entities with explicit segments among the subjects (or the participants of subject
    events); all of them without subjects."""
    with_segments = select(WorldlineSegment.entity_id).distinct()
    if subjects is None:
        return sorted(ctx.session.scalars(with_segments))
    wanted = set(subjects)
    wanted |= set(
        ctx.session.scalars(
            select(Link.target_id).where(
                Link.source_id.in_(sorted(wanted)),
                Link.link_type == PARTICIPANT,
                unindexed(Link.deleted_at).is_(None),
            )
        )
    )
    return sorted(
        ctx.session.scalars(with_segments.where(WorldlineSegment.entity_id.in_(sorted(wanted))))
    )


def _findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    service = Worldlines(ctx.context, AUTHOR)
    for entity_id in _travelers(ctx, subjects):
        entity = ctx.session.get(Entity, entity_id)
        if entity is None or entity.deleted_at is not None:
            continue
        lived = service.lived(entity)
        if lived.implicit:
            continue
        for participation in service.participations(lived):
            event = participation.event
            if participation.assignment == "absent":
                chosen = isinstance((participation.link.data or {}).get("segment_id"), str)
                yield FindingDraft(
                    ABSENT,
                    (entity.id, event.id),
                    f"“{entity.name}” takes part in “{event.name}”, but "
                    + ("the visit chosen for it doesn't cover the event."
                       if chosen else "isn't there then in any part of their worldline."),
                    discriminator=participation.link.id,
                    timeline_id=participation.timeline_id,
                    data={"link_id": participation.link.id},
                )  # fmt: skip
            elif participation.assignment == "ambiguous":
                ids = [lived.spans[i].id for i in participation.covering]
                yield FindingDraft(
                    AMBIGUOUS,
                    (entity.id, event.id),
                    f"“{entity.name}” is there {len(ids)} times when “{event.name}” happens: "
                    "choose which visit takes part in it.",
                    discriminator=participation.link.id,
                    timeline_id=participation.timeline_id,
                    data={"link_id": participation.link.id, "segment_ids": ids},
                )


# --- segments: jump events and self-encounters ---------------------------------------------------


def _segments(
    ctx: RuleContext, subjects: Iterable[str] | None
) -> list[tuple[Entity, list[WorldlineSegment]]]:
    """The live entities with explicit segments (home rows, in worldline order): those of the
    subjects, or whose jumps the subject events document; all of them without subjects."""
    if subjects is None:
        entity_ids = sorted(ctx.session.scalars(select(WorldlineSegment.entity_id).distinct()))
    else:
        found: set[str] = set()
        for chunk in _chunks(subjects):
            found |= set(
                ctx.session.scalars(
                    select(WorldlineSegment.entity_id).where(
                        or_(
                            WorldlineSegment.entity_id.in_(chunk),
                            WorldlineSegment.departure_event_id.in_(chunk),
                            WorldlineSegment.arrival_event_id.in_(chunk),
                        )
                    )
                )
            )
        entity_ids = sorted(found)
    result: list[tuple[Entity, list[WorldlineSegment]]] = []
    for chunk in _chunks(entity_ids):
        rows: dict[str, list[WorldlineSegment]] = {}
        statement = (
            select(WorldlineSegment)
            .where(
                WorldlineSegment.entity_id.in_(chunk),
                unindexed(WorldlineSegment.overrides_id).is_(None),
            )
            .order_by(WorldlineSegment.entity_id, WorldlineSegment.seq)
        )
        for row in ctx.session.scalars(statement):
            rows.setdefault(row.entity_id, []).append(row)
        entities = ctx.session.scalars(
            select(Entity).where(Entity.id.in_(sorted(rows)), Entity.deleted_at.is_(None))
        )
        result.extend((entity, rows[entity.id]) for entity in entities)
    return sorted(result, key=lambda item: item[0].id)


def _mismatches(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    travelers = _segments(ctx, subjects)
    event_ids = {
        e
        for _, rows in travelers
        for row in rows
        for e in (row.departure_event_id, row.arrival_event_id)
        if e is not None
    }
    events: dict[str, tuple[str, str | None, int | None, int | None]] = {}
    for chunk in _chunks(event_ids):
        statement = (
            select(Event.entity_id, Entity.name, Entity.dimension_id, Event.start_t, Event.end_t)
            .join(Entity, Entity.id == Event.entity_id)
            .where(
                Event.entity_id.in_(chunk),
                unindexed(Event.overrides_id).is_(None),
                unindexed(Entity.deleted_at).is_(None),
            )
        )
        for event_id, name, dimension_id, start_t, end_t in ctx.session.execute(statement):
            events[event_id] = (name, dimension_id, start_t, end_t)
    for entity, rows in travelers:
        for row in rows:
            sides = (
                ("departure", row.departure_event_id, row.end_t, "leaves"),
                ("arrival", row.arrival_event_id, row.start_t, "arrives"),
            )
            for side, documented, t, verb in sides:
                if documented is None or documented not in events or t is None:
                    continue
                name, dimension_id, start_t, end_t = events[documented]
                if start_t is None:
                    continue
                end = start_t if end_t is None else end_t
                if dimension_id == row.dimension_id and start_t <= t <= end:
                    continue
                yield FindingDraft(
                    MISMATCH,
                    (entity.id, documented),
                    f"“{entity.name}” {verb} at the "
                    + ("end" if side == "departure" else "start")
                    + f" of segment {row.seq}, but its {side} event “{name}” isn't then.",
                    discriminator=f"{row.id}:{side}",
                    timeline_id=row.timeline_id,
                    data={"segment_id": row.id, "side": side},
                )


def _span(row: WorldlineSegment) -> tuple[int, int] | None:
    return None if row.start_t is None or row.end_t is None else (row.start_t, row.end_t)


def _overlapping(rows: Sequence[WorldlineSegment]) -> Iterator[tuple[WorldlineSegment, ...]]:
    for i, first in enumerate(rows):
        for second in rows[i + 1 :]:
            a, b = _span(first), _span(second)
            if first.timeline_id != second.timeline_id or a is None or b is None:
                continue
            if max(a[0], b[0]) < min(a[1], b[1]):
                yield first, second


def _encounters(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    for entity, rows in _segments(ctx, subjects):
        for first, second in _overlapping(rows):
            yield FindingDraft(
                ENCOUNTER,
                (entity.id,),
                f"“{entity.name}” is in this timeline twice at once (segments {first.seq} and "
                f"{second.seq}) and may meet their other self.",
                discriminator=f"{first.id}:{second.id}",
                timeline_id=first.timeline_id,
                data={"segment_ids": [first.id, second.id]},
            )


# --- causal loops --------------------------------------------------------------------------------


def _causes(ctx: RuleContext, ids: Iterable[str], *, forward: bool) -> list[tuple[str, str]]:
    """The live ``core.causes`` links from (or to) these events, as ``(cause, effect)``."""
    found: list[tuple[str, str]] = []
    end = Link.source_id if forward else Link.target_id
    for chunk in _chunks(ids):
        statement = select(Link.source_id, Link.target_id).where(
            end.in_(chunk), Link.link_type == CAUSES, unindexed(Link.deleted_at).is_(None)
        )
        found.extend((a, b) for a, b in ctx.session.execute(statement))
    return found


def _reach(ctx: RuleContext, start: set[str], *, forward: bool) -> set[str]:
    seen, frontier = set(start), set(start)
    while frontier:
        steps = _causes(ctx, frontier, forward=forward)
        frontier = {b if forward else a for a, b in steps} - seen
        seen |= frontier
    return seen


def _loops(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    """The strongly connected components with a cycle (Tarjan, iterative), each sorted."""
    graph: dict[str, list[str]] = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, [])
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, position = work.pop()
            if position == 0:
                index[node] = low[node] = len(index)
                stack.append(node)
                on_stack.add(node)
            targets = graph[node]
            if position < len(targets):
                work.append((node, position + 1))
                target = targets[position]
                if target not in index:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index[target])
                continue
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = _pop_component(stack, on_stack, node)
                if len(component) > 1 or node in graph[node]:
                    found.append(sorted(component))
    return found


def _pop_component(stack: list[str], on_stack: set[str], root: str) -> list[str]:
    component: list[str] = []
    while True:
        member = stack.pop()
        on_stack.discard(member)
        component.append(member)
        if member == root:
            return component


def _causal_loops(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    if subjects is None:
        statement = select(Link.source_id, Link.target_id).where(
            Link.link_type == CAUSES, unindexed(Link.deleted_at).is_(None)
        )
        edges = [(a, b) for a, b in ctx.session.execute(statement)]
        wanted = None
    else:
        wanted = set(subjects)
        both = _reach(ctx, wanted, forward=True) & _reach(ctx, wanted, forward=False)
        edges = [(a, b) for a, b in _causes(ctx, both, forward=True) if b in both]
    nodes = sorted({n for edge in edges for n in edge})
    names: dict[str, str] = {}
    for chunk in _chunks(nodes):
        statement = select(Entity.id, Entity.name).where(
            Entity.id.in_(chunk), unindexed(Entity.deleted_at).is_(None)
        )
        names.update((entity_id, name) for entity_id, name in ctx.session.execute(statement))
    live = [(a, b) for a, b in edges if a in names and b in names]
    for loop in _loops(live):
        if wanted is not None and not wanted & set(loop):
            continue
        shown = ", ".join(f"“{names[e]}”" for e in loop[:NAMED]) + (
            " …" if len(loop) > NAMED else ""
        )
        yield FindingDraft(
            LOOP,
            tuple(loop),
            f"These events cause each other: {shown}. A causal loop (bootstrap paradox).",
        )


type Check = Callable[[RuleContext, Iterable[str] | None], Iterator[FindingDraft]]


def _check(rule_id: str) -> Check:
    def check(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
        return (f for f in _findings(ctx, subjects) if f.rule_id == rule_id)

    return check


TRIGGERS = (Trigger("record", "*"), Trigger("link_type", PARTICIPANT))
SEGMENTS = (Trigger("record", "*"),)

CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    RuleDef(
        id=ABSENT,
        owner="worldlines",
        title="Participant isn't there",
        description="An entity with a worldline takes part in an event that none of its "
        "segments covers (or the chosen visit doesn't). Change its worldline, the event or the "
        "participation.",
        category="advanced_time",
        default_severity="warning",
        configurable=True,
        triggers=TRIGGERS,
        check=_check(ABSENT),
        scan=lambda ctx: _check(ABSENT)(ctx, None),
    ),
    RuleDef(
        id=AMBIGUOUS,
        owner="worldlines",
        title="Which visit takes part?",
        description="A time traveler is present more than once when an event happens, and the "
        "participation doesn't say which visit takes part in it.",
        category="advanced_time",
        default_severity="warning",
        configurable=True,
        triggers=TRIGGERS,
        check=_check(AMBIGUOUS),
        scan=lambda ctx: _check(AMBIGUOUS)(ctx, None),
    ),
    RuleDef(
        id=MISMATCH,
        owner="worldlines",
        title="Jump event at another time",
        description="A segment's departure event doesn't happen when the segment ends (or its "
        "arrival event when it starts). Move the event or the segment.",
        category="advanced_time",
        default_severity="warning",
        configurable=True,
        triggers=SEGMENTS,
        check=_mismatches,
        scan=lambda ctx: _mismatches(ctx, None),
    ),
    RuleDef(
        id=ENCOUNTER,
        owner="worldlines",
        title="Meets itself",
        description="Two segments of an entity's worldline overlap in the same timeline: it is "
        "there twice at once.",
        category="advanced_time",
        default_severity="off",
        configurable=True,
        triggers=SEGMENTS,
        check=_encounters,
        scan=lambda ctx: _encounters(ctx, None),
    ),
    RuleDef(
        id=LOOP,
        owner="worldlines",
        title="Causal loop",
        description="Events cause each other in a cycle: a chain of causes leads back to its own "
        "beginning (the bootstrap paradox).",
        category="advanced_time",
        default_severity="off",
        configurable=True,
        triggers=(Trigger("link_type", CAUSES),),
        check=_causal_loops,
        scan=lambda ctx: _causal_loops(ctx, None),
    ),
)
