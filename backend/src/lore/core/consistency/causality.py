"""What ``core.event.effect_before_cause`` needs beyond one dimension's moments (``time-model.md``
§9.3):

- **Across dimensions** the cause's start is mapped into the effect's dimension through the
  correspondences (``CorrespondenceGraph``, shortest path, §12.3). Without a path, or where the
  mapping is undefined, the pair isn't checked.
- **Subjective order** (§11): an effect that starts before its cause in the world isn't reported
  when an entity with explicit worldline segments takes part in both and lives the cause first
  (it learnt of it, travelled back and brought the effect about). Each participation is placed
  like the worldlines module does (§11.4): the segment the link chooses, else the first in
  worldline order whose dimension is the event's, whose timeline sees the event and which covers
  its start. Only while the worldlines module is on, and with the home rows of the segments and
  events.
"""

from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import select

from lore.core.consistency.compare import DEFINITE, POSSIBLE, Certainty
from lore.core.consistency.engine import RuleContext
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.links.models import Link
from lore.core.time.correspondences import CorrespondenceGraph
from lore.core.time.models import Event, WorldlineSegment
from lore.core.time.timeline_view import lineage
from lore.core.time.worldlines import Span, rate_of, subjective_at, subjective_starts

PARTICIPANT = "core.participant"
_BATCH = 5000

type Pair = tuple[str, str]  # cause, effect


def _chunks(ids: Iterable[str]) -> Iterator[list[str]]:
    wanted = sorted(set(ids))
    for start in range(0, len(wanted), _BATCH):
        yield wanted[start : start + _BATCH]


def _vague(spec: Any) -> bool:
    """Whether a stored start is circa or coarser than the base unit."""
    if not isinstance(spec, dict):
        return False
    return bool(spec.get("approximate")) or spec.get("precision", "base") != "base"


class Mapper:
    """Maps causes' starts into their effects' dimensions (the graph is loaded once, when the
    first pair needs it)."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self._graph: CorrespondenceGraph | None = None

    def violated(
        self,
        cause: tuple[str, int | None, Any],
        effect: tuple[str, int | None, Any],
    ) -> Certainty | None:
        """How certainly the effect (``dimension, start_t, start_spec``) starts before the
        cause's start mapped into its dimension; ``None`` when it doesn't or can't be told."""
        (cause_dimension, cause_t, cause_spec), (effect_dimension, effect_t, effect_spec) = (
            cause,
            effect,
        )
        if cause_t is None or effect_t is None:
            return None
        if self._graph is None:
            self._graph = CorrespondenceGraph.load(self.ctx.session)
        mapped = self._graph.map(cause_dimension, effect_dimension, cause_t)
        if mapped.t is None or effect_t >= mapped.t:
            return None
        return POSSIBLE if _vague(cause_spec) or _vague(effect_spec) else DEFINITE


@dataclass(frozen=True)
class _Place:
    dimension_id: str
    timeline_id: str
    t: int | None


class _Seen:
    """Whether a timeline sees an event of another (lineage cut-offs), cached per timeline."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self._lineages: dict[str, dict[str, int | None]] = {}

    def __call__(self, timeline_id: str, place: _Place) -> bool:
        if timeline_id not in self._lineages:
            self._lineages[timeline_id] = {
                e.timeline_id: e.cutoff for e in lineage(self.ctx.session, timeline_id)
            }
        entries = self._lineages[timeline_id]
        if place.timeline_id not in entries or place.t is None:
            return False
        cutoff = entries[place.timeline_id]
        return cutoff is None or place.t < cutoff


def _worldlines(ctx: RuleContext, entity_ids: list[str]) -> dict[str, list[Span]]:
    """The explicit worldlines (home rows) of these entities that resolve completely."""
    rows: dict[str, list[WorldlineSegment]] = {}
    for chunk in _chunks(entity_ids):
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
    found: dict[str, list[Span]] = {}
    for entity_id, segments in rows.items():
        spans: list[Span] = []
        for row in segments:
            if row.start_t is None or row.end_t is None:
                break
            spans.append(
                Span(row.id, row.dimension_id, row.timeline_id, row.start_t, row.end_t,
                     rate_of(row.rate))
            )  # fmt: skip
        else:
            found[entity_id] = spans
    return found


def experienced_in_order(ctx: RuleContext, pairs: Collection[Pair]) -> set[Pair]:
    """The pairs some entity taking part in both events lives cause first (``≤``)."""
    if not pairs:
        return set()
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    if "worldlines" not in enabled_modules(ctx.session, ctx.registry):
        return set()
    events = sorted({event for pair in pairs for event in pair})
    taking: dict[str, dict[str, str | None]] = {}
    for chunk in _chunks(events):
        statement = select(Link.source_id, Link.target_id, Link.data).where(
            Link.source_id.in_(chunk),
            Link.link_type == PARTICIPANT,
            unindexed(Link.deleted_at).is_(None),
            unindexed(Link.overrides_id).is_(None),
        )
        for source, target, data in ctx.session.execute(statement):
            picked = (data or {}).get("segment_id")
            taking.setdefault(source, {})[target] = picked if isinstance(picked, str) else None
    shared = {
        pair: sorted(set(taking.get(pair[0], {})) & set(taking.get(pair[1], {}))) for pair in pairs
    }
    worldlines = _worldlines(ctx, sorted({e for found in shared.values() for e in found}))
    if not worldlines:
        return set()
    places: dict[str, _Place] = {}
    for chunk in _chunks(events):
        statement = (
            select(Event.entity_id, Entity.dimension_id, Event.timeline_id, Event.start_t)
            .join(Entity, Entity.id == Event.entity_id)
            .where(Event.entity_id.in_(chunk), unindexed(Event.overrides_id).is_(None))
        )
        for event_id, dimension_id, timeline_id, start_t in ctx.session.execute(statement):
            if dimension_id is not None and timeline_id is not None:
                places[event_id] = _Place(dimension_id, timeline_id, start_t)
    seen = _Seen(ctx)

    def lived_at(entity_id: str, event_id: str) -> Fraction | None:
        spans, place = worldlines[entity_id], places.get(event_id)
        if place is None or place.t is None:
            return None
        picked = taking[event_id][entity_id]
        for index, span in enumerate(spans):
            if picked is not None and span.id != picked:
                continue
            if (
                span.dimension_id == place.dimension_id
                and span.timeline_id is not None
                and seen(span.timeline_id, place)
                and span.covers(place.t)
            ):
                return subjective_at(span, subjective_starts(spans)[index], place.t)
        return None

    found: set[Pair] = set()
    for pair, entities in shared.items():
        for entity_id in entities:
            if entity_id not in worldlines:
                continue
            cause, effect = lived_at(entity_id, pair[0]), lived_at(entity_id, pair[1])
            if cause is not None and effect is not None and cause <= effect:
                found.add(pair)
                break
    return found


__all__ = ["Mapper", "experienced_in_order"]
