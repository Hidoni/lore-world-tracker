"""Core's narrative rules about existence and temporal facts (``consistency.md`` §6), and the
finders modules build theirs with. Every one is precision-aware (``existence.py``,
``compare.py``) and compares records of one timeline.

- ``core.event.participant_not_existing``: a participant's existence doesn't cover the event's
  span (recurring series aside). Entities with explicit worldline segments are left to
  ``worldlines.absent_participant`` while that module is on (time-model.md §11.4).
- ``core.fact.outside_existence``: a fact's validity (a temporal field's value, a name) lies
  outside its entity's existence.
- ``core.fact.overlap``: two facts of a single-valued field (or two names) overlap.
- ``core.link.outside_existence``: a temporal link's validity lies outside either end's
  existence.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from lore.core.consistency.compare import Certainty
from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.consistency.existence import (
    EXISTS,
    FACT,
    Existences,
    Requirement,
    Requirements,
    Span,
    chunks,
    dimensions_of,
    disjoint,
    live,
    span,
    with_existence,
    within,
)
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.facts.models import EntityFact
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.models import Event, WorldlineSegment

NAME = "core.name"
LINK = "link"
EVENT = "event"
type Finder = Callable[[RuleContext, frozenset[str] | None], Iterator[FindingDraft]]
type Side = Literal["source", "target"]


def narrative_rule(
    rule_id: str,
    owner: str,
    title: str,
    description: str,
    finder: Finder,
    *,
    triggers: tuple[Trigger, ...],
    severity: Literal["warning", "off"] = "warning",
) -> RuleDef:
    """A configurable narrative rule: ``check`` is the finder with the subjects, ``scan``
    without."""
    return RuleDef(
        id=rule_id,
        owner=owner,
        title=title,
        description=description,
        category="narrative",
        default_severity=severity,
        configurable=True,
        triggers=triggers,
        check=finder,
        scan=lambda ctx: finder(ctx, None),
    )


def _sides(statement: Any, subjects: Iterable[str] | None, *columns: Any) -> Iterator[Any]:
    """The statement as is (a scan), or once per batch of subjects and column (each through its
    index: SQLite won't use two for one ``OR``)."""
    if subjects is None:
        yield statement
        return
    for batch in chunks(subjects):
        for column in columns:
            yield statement.where(column.in_(batch))


def _rows(ctx: RuleContext, statements: Iterable[Any]) -> list[Any]:
    """The rows of several statements, each (by its first column) once."""
    found: dict[Any, Any] = {}
    for statement in statements:
        for row in ctx.session.execute(statement):
            found.setdefault(row[0], row)
    return list(found.values())


class Within:
    """Spans checked against the existence of entities in sets: ``add`` each, then ``findings``
    yields those violated with their certainty."""

    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self.dimensions = dimensions_of(ctx)
        self.existences = Existences(ctx)
        self._pending: list[tuple[str, str, Span, Any]] = []

    def add(self, container_id: str, timeline_id: str | None, inner: Span, item: Any) -> None:
        if timeline_id is not None:
            self._pending.append((container_id, timeline_id, inner, item))

    def findings(self) -> Iterator[tuple[Any, Certainty]]:
        self.existences.load(c for c, *_ in self._pending)
        requirements = Requirements(self.ctx)
        candidates: list[tuple[str, Requirement, Any]] = []
        for container_id, timeline_id, inner, item in self._pending:
            periods = self.existences.periods(container_id, timeline_id)
            dimension_id = self.dimensions.get(timeline_id)
            if periods is None or dimension_id is None:
                continue
            requirement = within(inner, periods)
            if requirements.want(dimension_id, requirement):
                candidates.append((dimension_id, requirement, item))
        self._pending.clear()
        requirements.load()
        for dimension_id, requirement, item in candidates:
            certainty = requirements.violated(dimension_id, requirement)
            if certainty is not None:
                yield item, certainty


# --- finders modules use -------------------------------------------------------------------------


def links_within(
    rule_id: str,
    link_types: Sequence[str] | None,
    sides: Sequence[Side],
    message: Callable[[str, str, Side], str],
) -> Finder:
    """Temporal links (of the types; every type with ``None``) whose validity lies outside the
    existence of their end(s) on the sides. ``message(source name, target name, side)``;
    subjects: that end, then the other."""

    def finder(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
        source, target = aliased(Entity), aliased(Entity)
        statement = (
            select(
                Link.id,
                Link.source_id,
                Link.target_id,
                Link.timeline_id,
                Link.valid_from_t,
                Link.valid_to_t,
                source.name,
                target.name,
            )
            .join(source, source.id == Link.source_id)
            .join(target, target.id == Link.target_id)
            .where(
                unindexed(Link.deleted_at).is_(None),
                unindexed(Link.overrides_id).is_(None),
                Link.timeline_id.is_not(None),  # a timeless link has no validity to check
                unindexed(source.deleted_at).is_(None),
                unindexed(target.deleted_at).is_(None),
            )
        )
        if link_types is not None:
            statement = statement.where(Link.link_type.in_(link_types))
        checker = Within(ctx)
        ends = {"source": Link.source_id, "target": Link.target_id}
        sides_of = (
            _sides(statement, subjects, Link.source_id, Link.target_id)
            if subjects is not None
            else _sides(statement, with_existence(ctx), *(ends[side] for side in sides))
        )
        for row in _rows(ctx, sides_of):
            link_id, source_id, target_id, timeline_id, from_t, to_t, *_names = row
            inner = span(LINK, link_id, from_t, to_t)
            for side in sides:
                checker.add(source_id if side == "source" else target_id, timeline_id, inner,
                            (row, side))  # fmt: skip
        for (row, side), certainty in checker.findings():
            link_id, source_id, target_id, timeline_id, _from, _to, source_name, target_name = row
            end, other = (source_id, target_id) if side == "source" else (target_id, source_id)
            yield FindingDraft(
                rule_id,
                (end, other),
                message(source_name, target_name, side),
                certainty=certainty,
                discriminator=f"{link_id}:{side}",
                timeline_id=timeline_id,
            )

    return finder


def events_within(
    rule_id: str,
    link_type: str,
    message: Callable[[str, str], str],
    *,
    instant: bool = False,
    skip: Callable[[RuleContext], frozenset[str]] | None = None,
) -> Finder:
    """Links of the type from an event to an entity whose existence doesn't cover the event's
    span (its start with ``instant``). Recurring series aren't checked. ``message(event name,
    entity name)``; subjects: the entity, then the event. ``skip`` names entities left to other
    rules."""

    def finder(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
        event_entity, other = aliased(Entity), aliased(Entity)
        statement = (
            select(
                Link.id,
                Link.source_id,
                Link.target_id,
                Event.timeline_id,
                Event.start_t,
                Event.end_t,
                event_entity.name,
                other.name,
            )
            .join(event_entity, event_entity.id == Link.source_id)
            .join(other, other.id == Link.target_id)
            .join(
                Event,
                and_(Event.entity_id == Link.source_id, unindexed(Event.overrides_id).is_(None)),
            )
            .where(
                Link.link_type == link_type,
                unindexed(Link.deleted_at).is_(None),
                unindexed(Event.recurrence).is_(None),
                unindexed(event_entity.deleted_at).is_(None),
                unindexed(other.deleted_at).is_(None),
            )
        )
        checker = Within(ctx)
        skipped = frozenset() if skip is None else skip(ctx)
        sides_of = (
            _sides(statement, subjects, Link.source_id, Link.target_id)
            if subjects is not None
            else _sides(statement, with_existence(ctx), Link.target_id)
        )
        for row in _rows(ctx, sides_of):
            _link_id, event_id, entity_id, timeline_id, start_t, end_t, *_names = row
            if entity_id in skipped:
                continue
            inner = span(EVENT, event_id, start_t, start_t if instant else end_t,
                         ("start", "start" if instant else "end"))  # fmt: skip
            checker.add(entity_id, timeline_id, inner, row)
        for row, certainty in checker.findings():
            link_id, event_id, entity_id, timeline_id, _start, _end, event_name, name = row
            yield FindingDraft(
                rule_id,
                (entity_id, event_id),
                message(event_name, name),
                certainty=certainty,
                discriminator=link_id,
                timeline_id=timeline_id,
            )

    return finder


def periods_within(
    rule_id: str,
    pairs: Callable[[RuleContext, frozenset[str] | None], Iterable[tuple[str, str]]],
    message: Callable[[str, str], str],
) -> Finder:
    """Existence periods of entities lying outside the existence of another entity: ``pairs``
    gives ``(entity, container)`` pairs (all with ``None``, else every pair involving a
    subject). ``message(entity name, container name)``; subjects: the entity, then the
    container. Each pair gives one finding, the most certain of its periods'."""

    def finder(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
        # Both need existence periods for one to lie outside the other's.
        found = list(
            dict.fromkeys(pairs(ctx, with_existence(ctx) if subjects is None else subjects))
        )
        if not found:
            return
        names = live(ctx, {i for pair in found for i in pair})
        found = [(a, b) for a, b in found if a in names and b in names]
        checker = Within(ctx)
        checker.existences.load(a for a, _ in found)
        for entity_id, container_id in found:
            for timeline_id in checker.existences.timelines(entity_id):
                for period in checker.existences.periods(entity_id, timeline_id) or ():
                    checker.add(container_id, timeline_id, period,
                                (entity_id, container_id, timeline_id))  # fmt: skip
        best: dict[tuple[str, str, str], Certainty] = {}
        for item, certainty in checker.findings():
            if best.get(item) != "definite":
                best[item] = certainty
        for (entity_id, container_id, timeline_id), certainty in sorted(best.items()):
            yield FindingDraft(
                rule_id,
                (entity_id, container_id),
                message(names[entity_id], names[container_id]),
                certainty=certainty,
                discriminator=timeline_id,
                timeline_id=timeline_id,
            )

    return finder


def links_of(
    ctx: RuleContext, subjects: frozenset[str] | None, link_type: str
) -> Iterator[tuple[str, str]]:
    """``(source, target)`` of the live links of a type (involving a subject)."""
    statement = select(Link.id, Link.source_id, Link.target_id).where(
        Link.link_type == link_type, unindexed(Link.deleted_at).is_(None)
    )
    for _id, source_id, target_id in _rows(
        ctx, _sides(statement, subjects, Link.source_id, Link.target_id)
    ):
        yield source_id, target_id


# --- core's rules --------------------------------------------------------------------------------


def _fact_rows(ctx: RuleContext, subjects: frozenset[str] | None, *conditions: Any) -> list[Any]:
    statement = (
        select(
            EntityFact.id,
            EntityFact.entity_id,
            EntityFact.field_key,
            EntityFact.timeline_id,
            EntityFact.valid_from_t,
            EntityFact.valid_to_t,
            Entity.name,
            Entity.kind,
        )
        .join(Entity, Entity.id == EntityFact.entity_id)
        .where(
            unindexed(EntityFact.deleted_at).is_(None),
            unindexed(EntityFact.overrides_id).is_(None),
            unindexed(Entity.deleted_at).is_(None),
            *conditions,
        )
    )
    return _rows(ctx, _sides(statement, subjects, EntityFact.entity_id))


def _facts_scope(ctx: RuleContext, subjects: frozenset[str] | None) -> frozenset[str]:
    return with_existence(ctx) if subjects is None else subjects


def _fields(ctx: RuleContext) -> dict[tuple[str, str], tuple[str, bool]]:
    """``(kind, field key)`` → (label, multiple) of the enabled kinds' fields."""
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    kinds = ctx.registry.vault_kinds(ctx.session, enabled_modules(ctx.session, ctx.registry))
    return {(k.key, f.key): (f.label, f.multiple) for k in kinds for f in k.fields}


def _value_label(fields: dict[tuple[str, str], tuple[str, bool]], kind: str, key: str) -> str:
    if key == NAME:
        return "A name"
    label = fields.get((kind, key), (key, False))[0]
    return f"A value of “{label}”"


def _facts_outside(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    fields = _fields(ctx)
    checker = Within(ctx)
    for row in _fact_rows(ctx, _facts_scope(ctx, subjects), EntityFact.field_key != EXISTS):
        fact_id, entity_id, _key, timeline_id, from_t, to_t, _name, _kind = row
        checker.add(entity_id, timeline_id, span(FACT, fact_id, from_t, to_t), row)
    for row, certainty in checker.findings():
        fact_id, entity_id, key, timeline_id, _from, _to, name, kind = row
        yield FindingDraft(
            "core.fact.outside_existence",
            (entity_id,),
            f"{_value_label(fields, kind, key)} of “{name}” is valid while it doesn't exist.",
            certainty=certainty,
            discriminator=fact_id,
            timeline_id=timeline_id,
        )


def _overlaps(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    fields = _fields(ctx)
    groups: dict[tuple[str, str, str], list[Any]] = {}
    for row in _fact_rows(ctx, subjects, EntityFact.field_key != EXISTS):
        _id, entity_id, key, timeline_id, *_rest, kind = row
        if key == NAME or not fields.get((kind, key), ("", False))[1]:
            groups.setdefault((entity_id, key, timeline_id), []).append(row)
    dimensions = dimensions_of(ctx)
    requirements = Requirements(ctx)
    candidates: list[tuple[str, Requirement, Any, Any]] = []
    for (_entity, _key, timeline_id), rows in groups.items():
        dimension_id = dimensions.get(timeline_id)
        if dimension_id is None or len(rows) < 2:  # noqa: PLR2004
            continue
        rows.sort(key=lambda r: r[0])
        for index, a in enumerate(rows):
            for b in rows[index + 1 :]:
                requirement = disjoint(span(FACT, a[0], a[4], a[5]), span(FACT, b[0], b[4], b[5]))
                if requirements.want(dimension_id, requirement):
                    candidates.append((dimension_id, requirement, a, b))
    requirements.load()
    for dimension_id, requirement, a, b in candidates:
        certainty = requirements.violated(dimension_id, requirement)
        if certainty is None:
            continue
        fact_id, entity_id, key, timeline_id, _from, _to, name, kind = a
        label = "Two names" if key == NAME else _value_label(fields, kind, key).replace(
            "A value", "Two values")  # fmt: skip
        yield FindingDraft(
            "core.fact.overlap",
            (entity_id,),
            f"{label} of “{name}” overlap in time: the later one wins.",
            certainty=certainty,
            discriminator=f"{fact_id}:{b[0]}",
            timeline_id=timeline_id,
        )


ANY_RECORD = Trigger("record", "*")


def _travelers(ctx: RuleContext) -> frozenset[str]:
    """Entities with explicit worldline segments while the worldlines module is on: their
    participations are checked against their segments (``worldlines.absent_participant``)."""
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    if "worldlines" not in enabled_modules(ctx.session, ctx.registry):
        return frozenset()
    return frozenset(ctx.session.scalars(select(WorldlineSegment.entity_id).distinct()))


NARRATIVE_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "core.event.participant_not_existing",
        "core",
        "Participant doesn't exist",
        "A participant's existence doesn't cover the event it takes part in. Change the event's "
        "time, the participant's existence or the participation.",
        events_within(
            "core.event.participant_not_existing",
            "core.participant",
            lambda event, name: f"“{name}” takes part in “{event}” while not existing.",
            skip=_travelers,
        ),
        triggers=(ANY_RECORD, Trigger("link_type", "core.participant")),
    ),
    narrative_rule(
        "core.fact.overlap",
        "core",
        "Overlapping values",
        "Two values of a single-valued temporal field (or two names) of an entity overlap in "
        "time; where they do, the later start wins.",
        _overlaps,
        triggers=(ANY_RECORD,),
    ),
    narrative_rule(
        "core.fact.outside_existence",
        "core",
        "Value outside existence",
        "A temporal field's value (or a name) is valid while its entity doesn't exist.",
        _facts_outside,
        triggers=(ANY_RECORD,),
    ),
    narrative_rule(
        "core.link.outside_existence",
        "core",
        "Link outside existence",
        "A temporal link is valid while one of its ends doesn't exist.",
        links_within(
            "core.link.outside_existence",
            None,
            ("source", "target"),
            lambda source, target, side: (
                f"A link between “{source}” and “{target}” is valid while "
                f"“{source if side == 'source' else target}” doesn't exist."
            ),
        ),
        triggers=(ANY_RECORD, Trigger("link_type", "*")),
    ),
)

__all__ = [
    "NARRATIVE_RULES",
    "Finder",
    "Within",
    "events_within",
    "links_of",
    "links_within",
    "narrative_rule",
    "periods_within",
]
