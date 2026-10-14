"""The graph (``docs/modules/graph.md``): entities as nodes, and links, mentions and the parent
tree as edges, read with set-based SQL through the request's ``VisibilityPolicy``.

- **Nodes** are the live entities the policy shows, of the enabled modules' kinds, filtered by
  dimension (with multiversal entities), kinds and tags (any of them). With the time cursor
  (``timeline``, ``at``) those that don't exist then are left out (``existence``: ``exists``,
  ``possible`` or ``unknown``).
- **Edges** join two nodes: links the policy shows (of ``link_types``; with the cursor timeless
  ones and those valid then on the timeline), mentions (for readers only those outside private
  blocks, weighted by their count) and parents.
- **Global** (no ``center``): every node and the edges between them, in a few statements. **Local**
  (``center``, ``depth``): a breadth-first search from the center, a set of edges per level.
- Over ``limit`` nodes, the highest-degree ones are kept (``truncated``).
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, cast

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session, aliased

from lore.core.db import unindexed
from lore.core.entities.models import Entity, EntityTag
from lore.core.entities.service import EntityService
from lore.core.facts.schemas import EXISTS
from lore.core.links.models import Link
from lore.core.links.service import timeless
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.richtext.models import Mention
from lore.core.time.branches import scope_for
from lore.core.time.models import Timeline
from lore.core.time.state import (
    FACT,
    AsOf,
    Coverage,
    StateReader,
    as_of_for,
    maybe_covers,
    timeline_resolver,
)
from lore.core.time.timeline_view import TimelineView
from lore.core.visibility import AUTHOR, VisibilityPolicy

LINK = "link"
_BATCH = 5000
type Scope = Callable[[Any], ColumnElement[bool]]  # an id column -> "is a node"
type Shown = Literal["exists", "unknown", "possible"]


@dataclass(frozen=True)
class Query:
    dimension: str | None = None
    center: str | None = None
    depth: int = 1
    kinds: Sequence[str] = ()
    link_types: Sequence[str] = ()
    tags: Sequence[str] = ()
    include_mentions: bool = True
    include_hierarchy: bool = True
    timeline: str | None = None
    at: str | None = None
    limit: int = 5000


class _Edge(NamedTuple):
    """An edge while it is gathered (models are built once, for the response)."""

    source: str
    target: str
    kind: Literal["link", "mention", "parent"]
    link_id: str | None = None
    link_type: str | None = None
    label: str | None = None
    weight: int = 1


@dataclass
class _Found:
    nodes: dict[str, Any] = field(default_factory=dict)  # id -> (id, kind, name, dimension_id)
    existence: dict[str, Shown] = field(default_factory=dict)
    edges: dict[tuple[str, str, str, str], _Edge] = field(default_factory=dict)

    def add_edges(self, edges: Iterable[_Edge]) -> None:
        for edge in edges:
            if edge.source != edge.target:
                key = (edge.kind, edge.link_id or "", edge.source, edge.target)
                self.edges[key] = edge


def _ids(ids: Iterable[str]) -> Scope:
    wanted = sorted(set(ids))
    return lambda column: column.in_(wanted)


class GraphReader:
    def __init__(self, context: VaultContext, policy: VisibilityPolicy) -> None:
        self.context = context
        self.session: Session = context.session
        self.policy = policy
        self.registry = context.registry

    def graph(self, query: Query) -> dict[str, Any]:
        """The graph as a ``Graph`` body (plain data)."""
        center = None
        if query.center is not None:
            center = EntityService(self.context, self.policy).load_visible(query.center)
        dimension_id = query.dimension or (center.dimension_id if center is not None else None)
        as_of = as_of_for(self.context, self.policy, timeline_id=query.timeline, at=query.at,
                          dimension_id=dimension_id)  # fmt: skip
        nodes = self._node_statement(query)
        found = _Found()
        if center is None:
            self._add_nodes(found, self.session.execute(nodes).all(), as_of)
            # Edges between candidates (those that don't exist then are dropped afterwards).
            candidates = nodes.subquery("candidates")
            # Every edge row is read once, checked against the candidates (a scan beats one index
            # lookup per node when most of them are in the graph).
            scope: Scope = lambda column: unindexed(column).in_(select(candidates.c.id))  # noqa: E731
            found.add_edges(self._edges(query, as_of, scope, scope))
        else:
            self._neighborhood(found, query, as_of, nodes, center.id)
        return self._result(found, query.limit, as_of is not None)

    # --- nodes ----------------------------------------------------------------------------------

    def _node_statement(self, query: Query) -> Any:
        enabled = enabled_modules(self.session, self.registry)
        kinds = {kind.key for kind in self.registry.kinds_for(enabled)}
        if query.kinds:
            kinds &= set(query.kinds)
        conditions: list[Any] = [
            Entity.deleted_at.is_(None),
            unindexed(Entity.kind).in_(sorted(kinds)),
            *self.policy.entities(Entity),
        ]
        if query.dimension is not None:
            conditions.append(
                or_(Entity.dimension_id == query.dimension, Entity.dimension_id.is_(None))
            )
        if query.tags:
            conditions.append(
                exists().where(EntityTag.entity_id == Entity.id, EntityTag.tag_id.in_(query.tags))
            )
        # Branch-only entities in their branch's lineage (time-model.md §4.6).
        conditions += scope_for(self.session, self.policy, query.timeline)(Entity)
        return select(Entity.id, Entity.kind, Entity.name, Entity.dimension_id).where(*conditions)

    def _add_nodes(self, found: _Found, rows: Sequence[Any], as_of: AsOf | None) -> list[str]:
        """Add the rows that exist at the cursor; their ids."""
        fresh = [row for row in rows if row[0] not in found.nodes]
        existence = self._existence([row[0] for row in fresh], as_of)
        added = []
        for row in fresh:
            shown = existence.get(row[0], "unknown")
            if shown not in ("exists", "possible", "unknown"):
                continue
            found.nodes[row[0]] = row
            found.existence[row[0]] = cast(Shown, shown)
            added.append(row[0])
        return added

    def _existence(self, ids: Sequence[str], as_of: AsOf | None) -> dict[str, str]:
        if as_of is None or not ids:
            return {}
        reader = StateReader(self.context, self.policy, as_of.timeline_id, as_of.t)
        facts = reader.facts(ids, keys=[EXISTS])
        coverage = Coverage(reader.resolver, FACT, as_of.t)
        coverage.preload(fact for found in facts.values() for fact in found)
        result: dict[str, str] = {}
        for entity_id, found in facts.items():
            covers = {coverage.of(fact) for fact in found}
            result[entity_id] = (
                "exists" if "certain" in covers else "possible" if "possible" in covers
                else "not_exists"
            )  # fmt: skip
        return result

    # --- edges ----------------------------------------------------------------------------------

    def _edges(self, query: Query, as_of: AsOf | None, sources: Scope, targets: Scope
               ) -> list[_Edge]:  # fmt: skip
        """The edges from a node in ``sources`` to one in ``targets``."""
        edges = self._links(query, as_of, sources, targets)
        if query.include_mentions:
            edges += self._mentions(sources, targets)
        if query.include_hierarchy:
            edges += self._parents(sources, targets)
        return edges

    def _link_timelines(self, timeline_id: str | None) -> Any:
        if timeline_id is None:
            return Link.timeline_id.in_(select(Timeline.entity_id).where(Timeline.is_prime))
        view = TimelineView.for_timeline(self.session, timeline_id)
        return Link.timeline_id.in_(view.timeline_ids)

    def _links(self, query: Query, as_of: AsOf | None, sources: Scope, targets: Scope
               ) -> list[_Edge]:  # fmt: skip
        conditions: list[Any] = [
            Link.deleted_at.is_(None),
            unindexed(Link.overrides_id).is_(None),
            sources(Link.source_id),
            targets(Link.target_id),
            # Both ends are nodes, which the policy shows: the link's own visibility and its
            # timeline remain (``policy.links`` without the ends, checked once per node).
            *self.policy.rows(Link),
            *self.policy.entity_ref(Link.timeline_id),
        ]
        if query.link_types:
            conditions.append(Link.link_type.in_(query.link_types))
        # Temporal links of the request's timeline (its lineage), or of prime timelines.
        conditions.append(or_(timeless(Link), self._link_timelines(query.timeline)))
        if as_of is not None:
            view = TimelineView.for_timeline(self.session, as_of.timeline_id)
            shown = view.select(Link, where=lambda row: [row.deleted_at.is_(None)]).subquery()
            covering = select(shown.c.id).where(*maybe_covers(shown.c, as_of.t))
            conditions.append(or_(timeless(Link), Link.id.in_(covering)))
        columns = (Link.id, Link.source_id, Link.target_id, Link.link_type, Link.role,
                   Link.timeline_id)  # fmt: skip
        rows = self.session.execute(select(*columns).where(*conditions)).all()
        if as_of is not None:
            # Only bounded links may not cover the moment; extents only tell how precise a
            # bound is: the author's resolver reads them.
            bounded = [row[0] for row in rows if row[5] is not None]
            records = [
                link
                for batch in _chunks(bounded)
                for link in self.session.scalars(select(Link).where(Link.id.in_(batch)))
            ]
            coverage = Coverage(timeline_resolver(self.context, AUTHOR, as_of.timeline_id), LINK,
                                as_of.t)  # fmt: skip
            coverage.preload(records)
            valid = {link.id for link in records if coverage.of(link) is not None}
            rows = [row for row in rows if row[5] is None or row[0] in valid]
        return [_Edge(source, target, "link", link_id, link_type, role)
                for link_id, source, target, link_type, role, _timeline in rows]  # fmt: skip

    def _mentions(self, sources: Scope, targets: Scope) -> list[_Edge]:
        if self.policy.reader:  # mentions in private blocks don't show
            weight = Mention.count_public + Mention.count_spoiler
        else:
            weight = Mention.count_public + Mention.count_spoiler + Mention.count_private
        rows = self.session.execute(
            select(Mention.source_entity_id, Mention.target_entity_id, weight).where(
                sources(Mention.source_entity_id), targets(Mention.target_entity_id), weight > 0
            )
        )
        return [_Edge(source, target, "mention", weight=count) for source, target, count in rows]

    def _parents(self, sources: Scope, targets: Scope) -> list[_Edge]:
        child = aliased(Entity)
        rows = self.session.execute(
            select(child.parent_id, child.id).where(
                child.parent_id.is_not(None), sources(child.parent_id), targets(child.id)
            )
        )
        return [_Edge(str(parent), entity, "parent") for parent, entity in rows]

    # --- local ----------------------------------------------------------------------------------

    def _neighborhood(self, found: _Found, query: Query, as_of: AsOf | None, nodes: Any,
                      center: str) -> None:  # fmt: skip
        """Breadth-first from the center: each level, the edges between the frontier and any
        node, then the edges among everything reached."""
        candidates = nodes.subquery("candidates")
        anywhere: Scope = lambda column: column.in_(select(candidates.c.id))  # noqa: E731
        frontier = self._add_nodes(found, self.session.execute(
            nodes.where(Entity.id == center)).all(), None)  # fmt: skip
        for _level in range(query.depth):
            if not frontier or len(found.nodes) >= query.limit * 4:
                break
            reached: set[str] = set()
            for batch in _chunks(frontier):
                near = _ids(batch)
                for edge in (*self._edges(query, as_of, near, anywhere),
                             *self._edges(query, as_of, anywhere, near)):  # fmt: skip
                    reached.update((edge.source, edge.target))
            new = sorted(reached - set(found.nodes))
            rows: list[Any] = []
            for batch in _chunks(new):
                rows += self.session.execute(nodes.where(Entity.id.in_(batch))).all()
            frontier = self._add_nodes(found, rows, as_of)
        ids = sorted(found.nodes)
        for batch in _chunks(ids):
            found.add_edges(self._edges(query, as_of, _ids(batch), _ids(ids)))

    # --- result ---------------------------------------------------------------------------------

    def _result(self, found: _Found, limit: int, timed: bool) -> dict[str, Any]:
        """The response body as plain data (``Graph``'s shape): tens of thousands of edges are
        too many to build models of."""
        edges = [e for e in found.edges.values()
                 if e.source in found.nodes and e.target in found.nodes]  # fmt: skip
        degree = _degrees(edges)
        order = sorted(
            found.nodes.values(), key=lambda row: (-degree.get(row[0], 0), row[2], row[0])
        )
        truncated = len(order) > limit
        if truncated:
            order = order[:limit]
            kept = {row[0] for row in order}
            edges = [e for e in edges if e.source in kept and e.target in kept]
            degree = _degrees(edges)
        return {
            "nodes": [
                {"id": node_id, "kind": kind, "name": name, "dimension_id": dimension_id,
                 "degree": degree.get(node_id, 0),
                 "existence": found.existence[node_id] if timed else None}
                for node_id, kind, name, dimension_id in order
            ],
            "edges": [
                {"source": e.source, "target": e.target, "kind": e.kind,
                 "link_type": e.link_type, "label": e.label, "weight": e.weight}
                for e in edges
            ],
            "truncated": truncated,
        }  # fmt: skip


def _degrees(edges: Iterable[_Edge]) -> dict[str, int]:
    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1
    return degree


def _chunks(ids: Sequence[str]) -> Iterable[list[str]]:
    for start in range(0, len(ids), _BATCH):
        yield list(ids[start : start + _BATCH])


__all__ = ["GraphReader", "Query"]
