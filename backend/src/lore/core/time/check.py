"""The time checker of ``lore vault check`` (``persistence-and-migrations.md`` §2): stored
dependency edges and resolved moments are derived from the time specs; this verifies them and
rebuilds them (``lore vault reindex``)."""

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from lore.chronology.schema import TimePoint
from lore.core.time.calendars import resolvable
from lore.core.time.dependencies import (
    CalendarNode,
    SlotNode,
    Target,
    end_targets,
    time_point_targets,
)
from lore.core.time.models import Calendar, TimeDependency
from lore.core.time.propagate import CALENDAR, TimeWriter
from lore.core.time.resolve import Resolution, Resolver
from lore.core.time.slots import SlotRegistry, SlotValue
from lore.core.time.status import TimeStatus

if TYPE_CHECKING:
    from lore.core.maintenance.checks import Problem
    from lore.core.modules.spec import VaultContext

CHECK = "time"
BATCH = 5000
GOOD = (TimeStatus.OK, TimeStatus.TRASHED_REF)


def _slots(context: VaultContext) -> Iterator[tuple[SlotNode, SlotValue]]:
    """Every slot with a spec and its stored value."""
    registry: SlotRegistry = context.registry.slot_registry()
    for provider in registry.providers:
        keys = provider.all_keys(context.session)
        for start in range(0, len(keys), BATCH):
            batch = keys[start : start + BATCH]
            loaded = registry.load(context.session, provider.record_type, batch)
            for key, value in sorted(loaded.items(), key=lambda item: (item[0].id, item[0].slot)):
                if value.spec is not None:
                    yield SlotNode(provider.record_type, key.id, key.slot), value


def expected_targets(registry: SlotRegistry, node: SlotNode, value: SlotValue) -> set[Target]:
    """The edges a slot's spec calls for (``time-model.md`` §7.1)."""
    if isinstance(value.spec, TimePoint):
        return time_point_targets(value.spec)
    assert value.spec is not None
    _provider, definition = registry.slot(node.type, node.slot)
    start = SlotNode(node.type, node.id, definition.start)
    return end_targets(value.spec, start=start, dimension_id=value.dimension_id or "")


def _fresh(
    resolvers: dict[str, Resolver], context: VaultContext, node: SlotNode, value: SlotValue
) -> Resolution | None:
    """A fresh resolution of a slot from its spec (``None`` without a dimension)."""
    if value.dimension_id is None:
        return None
    resolver = resolvers.get(value.dimension_id)
    if resolver is None:
        resolver = resolvers[value.dimension_id] = Resolver(context, value.dimension_id)
    if isinstance(value.spec, TimePoint):
        return resolver.resolve(resolvable(value.spec) if node.type == CALENDAR else value.spec)
    assert value.spec is not None
    registry: SlotRegistry = context.registry.slot_registry()
    _provider, definition = registry.slot(node.type, node.slot)
    needs_start = value.spec.kind in ("duration", "instant", "unknown")
    start = (
        resolver.slot(node.type, node.id, definition.start)
        if needs_start
        else Resolution(None, TimeStatus.OK)
    )
    return resolver.resolve_end(value.spec, start)


def verify_time(context: VaultContext) -> Iterator[Problem]:
    """Edges against specs (missing, stale, orphaned) and every stored moment against a fresh
    resolution (relative anchors resolve against their targets' stored moments)."""
    from lore.core.maintenance.checks import Problem  # noqa: PLC0415 (import cycle)

    session = context.session
    registry: SlotRegistry = context.registry.slot_registry()
    writer = TimeWriter(context)
    resolvers: dict[str, Resolver] = {}
    seen: set[SlotNode] = set()
    for node, value in _slots(context):
        seen.add(node)
        where = f"{node.type} {node.id} slot {node.slot!r}"
        if set(writer.index.edges_of(node)) != expected_targets(registry, node, value):
            message = f"the dependencies of {where} don't match its spec"
            yield Problem(CHECK, "time_edges_stale", message)
        fresh = _fresh(resolvers, context, node, value)
        if fresh is None:
            continue
        if fresh.status in GOOD and fresh.t is not None:
            if fresh.t != value.t:
                message = f"{where} is stored at {value.t}, but resolves to {fresh.t}"
                yield Problem(CHECK, "time_moment_stale", message)
        elif value.status in GOOD:
            code = fresh.problem.code if fresh.problem is not None else "unresolved"
            message = f"{where} is stored as {value.status}, but doesn't resolve ({code})"
            yield Problem(CHECK, "time_status_stale", message)
    T = TimeDependency  # noqa: N806
    dependents = session.execute(
        select(T.dependent_type, T.dependent_id, T.dependent_slot).distinct()
    )
    for row in dependents:
        node = SlotNode(*row)
        if node not in seen:
            message = f"{node.type} {node.id} slot {node.slot!r} has dependencies but no spec"
            yield Problem(CHECK, "time_edges_orphaned", message)


def rebuild_time(context: VaultContext) -> int:
    """Rewrite every slot's edges from its spec (and drop orphaned ones), then re-resolve
    everything (problems are stored as statuses, keeping the last good moments). Returns the
    number of slots."""
    session = context.session
    writer = TimeWriter(context)
    session.execute(delete(TimeDependency))
    count = 0
    for node, value in list(_slots(context)):
        writer.set_spec(node.type, node.id, node.slot, value.spec, dimension_id=value.dimension_id)
        count += 1
    writer.touch(*(CalendarNode(c) for c in session.scalars(select(Calendar.entity_id))))
    writer.propagate(strict=False)
    return count


__all__ = ["expected_targets", "rebuild_time", "verify_time"]
