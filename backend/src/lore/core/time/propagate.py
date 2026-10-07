"""Live-linked time: dependency propagation (``time-model.md`` §7, ADR-0007, D3).

Services change time through a ``TimeWriter`` inside their request transaction::

    writer = TimeWriter(context)
    row.start_spec = spec                                   # the service stores the spec …
    writer.set_spec("event", event_id, "start", spec)       # … and the writer rewrites its edges
    writer.propagate()                                      # steps 2-6 of §7.2

``propagate`` checks that no changed node reaches itself (``409 time_cycle`` with the path),
collects the affected set (the changed nodes and everything that transitively depends on them),
orders it topologically (Kahn) and re-resolves each node with the values already updated in this
run: slots through ``lore.core.time.resolve``, calendars by compiling them again with their
re-resolved anchors. Then the hard structural checks run on every affected slot (status ``ok`` or
``trashed_ref``, an end not before its start); a violation rejects the transaction with
``422 time_constraint`` listing the records (``strict=False`` returns them instead, for calendar
proposals). A slot that doesn't resolve keeps its last good moment.

Nodes are slots (``SlotNode``), calendars (``CalendarNode``: a calendar depends on its own anchor
slots, record type ``calendar``) and dimension durations (``DimensionNode``).
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from lore.chronology.schema import AbsoluteAnchor, EndSpec, TimePoint, TimePointEnd
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError
from lore.core.time.dependencies import (
    CalendarNode,
    DependencyIndex,
    DimensionNode,
    SlotNode,
    Target,
    end_targets,
    time_point_targets,
)
from lore.core.time.models import Calendar
from lore.core.time.resolve import BASE, Resolution, Resolver
from lore.core.time.slots import SlotKey, SlotRegistry, SlotUpdate, SlotValue, SpecUpdate
from lore.core.time.specs import dump_spec
from lore.core.time.status import TimeStatus

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

CALENDAR = "calendar"
EVENT = "event"
BATCH = 5000  # keys per load (SQLite's variable limit)
GOOD = frozenset({TimeStatus.OK, TimeStatus.TRASHED_REF})
MAX_ROUNDS = 8  # follow-up runs for occurrence refs of refreshed series
_SEVERITY = {TimeStatus.OK: 0, TimeStatus.TRASHED_REF: 1}

type Node = Target


class TimeCycleError(ConflictError):
    """A write would make time slots depend on themselves (``time-model.md`` §7.2 step 2)."""

    code = "time_cycle"
    title = "Time cycle"


class TimeConstraintError(InvalidInputError):
    """A hard structural time rule would break (``time-model.md`` §7.2 step 6)."""

    code = "time_constraint"
    title = "Time constraint violated"


@dataclass(frozen=True)
class Violation:
    """A slot (or calendar) that breaks a hard rule after propagation."""

    record_type: str
    id: str
    slot: str
    code: str
    message: str
    t: int | None = None

    def as_record(self) -> dict[str, str | None]:
        return {
            "record_type": self.record_type,
            "id": self.id,
            "slot": self.slot,
            "code": self.code,
            "t": None if self.t is None else str(self.t),
        }


@dataclass
class Propagation:
    """What a run did: the slots whose stored moment or status changed, and the violations
    (always empty after a strict run)."""

    updated: list[SlotNode] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    affected: int = 0


def describe(node: Node) -> str:
    match node:
        case SlotNode():
            return f"{node.type} {node.id} {node.slot}"
        case CalendarNode():
            return f"calendar {node.calendar_id}"
        case DimensionNode():
            return f"dimension {node.dimension_id} duration"


def constraint_error(violations: Sequence[Violation], path: str = "") -> TimeConstraintError:
    count = len(violations)
    noun = "time slot breaks" if count == 1 else "time slots break"
    return TimeConstraintError(
        f"{count} {noun} a time rule: {violations[0].message}"
        + (f" (and {count - 1} more)" if count > 1 else ""),
        errors=[
            ErrorItem(
                path=path or f"{v.record_type}.{v.slot}",
                code=v.code,
                message=f"{v.record_type} {v.id}: {v.message}",
            )
            for v in violations
        ],
        context={"records": [v.as_record() for v in violations]},
    )


class TimeWriter:
    """Collects the time nodes a service changed and propagates them (one per transaction, or
    one per batch of changes)."""

    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.slots: SlotRegistry = context.registry.slot_registry()
        self.index = DependencyIndex(self.session)
        self.changed: set[Node] = set()

    # --- recording changes --------------------------------------------------------------------

    def set_spec(
        self,
        record_type: str,
        record_id: str,
        slot: str,
        spec: TimePoint | EndSpec | None,
        *,
        dimension_id: str | None = None,
        store: bool = False,
    ) -> None:
        """A slot's spec changed: rewrite its outgoing edges (§7.2 step 1) and mark it changed.
        ``store=True`` also stores the spec through the slot provider (otherwise the service
        did). ``dimension_id`` is needed for ``end_of_time`` ends (else it is loaded)."""
        _provider, definition = self.slots.slot(record_type, slot)
        key = SlotKey(record_id, slot)
        if store and spec is not None:
            self.slots.write_specs(self.session, record_type, [SpecUpdate(key, spec)])
        node = SlotNode(record_type, record_id, slot)
        targets: set[Target] = set()
        if isinstance(spec, TimePoint):
            targets = time_point_targets(spec)
        elif spec is not None:
            if dimension_id is None and spec.kind == "end_of_time":
                value = self.slots.load(self.session, record_type, [key]).get(key)
                dimension_id = None if value is None else value.dimension_id
            start = SlotNode(record_type, record_id, definition.start)
            targets = end_targets(spec, start=start, dimension_id=dimension_id)
        self.index.replace_edges(node, targets)
        self.changed.add(node)

    def touch(self, *nodes: Node) -> None:
        """Nodes whose resolved value may have changed without a spec change (a calendar
        definition, a dimension's duration, a record taken out of the trash)."""
        self.changed.update(nodes)

    def touch_series(self, *series_ids: str) -> None:
        """Occurrences of these series may have moved (a materialized occurrence changed, or the
        rule did): whatever is anchored to the series resolves again (occurrence refs depend on
        the series' ``start``/``end`` slots, ``recurrence.md`` §7)."""
        from lore.core.time.series import series_slots  # noqa: PLC0415 (import cycle)

        own = set(series_ids)
        for node in series_slots(series_ids):
            self.changed.update(d for d in self.index.dependents_of(node) if d.id not in own)

    def touch_entity(self, entity_id: str) -> None:
        """An entity was trashed or restored: whatever depends on its records (or on it as a
        calendar) resolves again, to update ``trashed_ref`` statuses (§7.3)."""
        own = self._records_of_entity(entity_id)
        for record_type, record_id in own:
            for node in self.index.dependents_of_record(record_type, record_id):
                if (node.type, node.id) not in own:
                    self.changed.add(node)
        for node in self.index.dependents_of(CalendarNode(entity_id)):
            if (node.type, node.id) not in own:
                self.changed.add(node)
        from lore.core.time.models import Event  # noqa: PLC0415 (import cycle)

        series_id = self.session.scalar(
            select(Event.series_entity_id).where(Event.entity_id == entity_id)
        )
        if series_id is not None:  # a materialized occurrence: refs to it fall back or return
            self.touch_series(series_id)

    def _records_of_entity(self, entity_id: str) -> set[tuple[str, str]]:
        return {
            (provider.record_type, record_id)
            for provider in self.slots.providers
            for record_id in provider.records_of_entity(self.session, entity_id)
        }

    # --- anchor freezing (§7.3) ---------------------------------------------------------------

    def freeze_dependents(self, entity_id: str) -> int:
        """Before an entity is purged: every slot anchored to its records (or to it as a
        calendar) becomes an ``absolute`` anchor at its last resolved moment, keeping the old
        spec in ``frozen_from``. Returns how many slots were frozen."""
        own = self._records_of_entity(entity_id)
        dependents: set[SlotNode] = {
            node
            for record_type, record_id in own
            for node in self.index.dependents_of_record(record_type, record_id)
        }
        dependents.update(self.index.dependents_of(CalendarNode(entity_id)))
        frozen = 0
        for node in sorted(d for d in dependents if (d.type, d.id) not in own):
            if self.slots.get(node.type) is None:
                continue  # a record type nobody registers any more: nothing to freeze
            key = SlotKey(node.id, node.slot)
            value = self.slots.load(self.session, node.type, [key]).get(key)
            if value is None or value.spec is None:
                continue
            if value.t is None:
                continue  # nothing to freeze to: it never resolved (stays unresolved_ref)
            spec = self._frozen(value)
            self.set_spec(node.type, node.id, node.slot, spec, store=True)
            frozen += 1
        return frozen

    def _frozen(self, value: SlotValue) -> TimePoint | EndSpec:
        assert value.spec is not None
        assert value.t is not None
        precision = BASE
        original = dump_spec(value.spec)
        if isinstance(value.spec, TimePoint):
            approximate = value.spec.approximate
            if value.dimension_id is not None and value.spec.precision != BASE:
                resolver = self._resolver(value.dimension_id, {})
                if resolver is not None and resolver.has_default_level(value.spec.precision):
                    precision = value.spec.precision
        else:
            approximate = False
        point = TimePoint(
            anchor=AbsoluteAnchor(kind="absolute", t=str(value.t)),
            precision=precision,
            approximate=approximate,
            frozen_from=original,
        )
        if isinstance(value.spec, TimePoint):
            return point
        return TimePointEnd(kind="time_point", time_point=point)

    # --- propagation --------------------------------------------------------------------------

    def propagate(self, *, strict: bool = True, path: str = "", rounds: int = 0) -> Propagation:
        """Steps 2-6 of §7.2 for the nodes changed so far (then forgets them).

        A run that refreshed series through their rule's time points, calendar or dimension (not
        their start) runs again for what is anchored to their occurrences (at most
        ``MAX_ROUNDS`` times)."""
        changed, self.changed = self.changed, set()
        if not changed:
            return Propagation()
        self.session.flush()
        self._check_cycles(changed)
        affected, edges = self._closure(changed)
        run = _Run(self, affected, edges)
        result = run.execute()
        if strict and result.violations:
            raise constraint_error(result.violations, path)
        followers = run.followers - affected
        if followers and rounds < MAX_ROUNDS:
            self.changed.update(followers)
            more = self.propagate(strict=strict, path=path, rounds=rounds + 1)
            result.updated += more.updated
            result.violations += more.violations
            result.affected += more.affected
        return result

    def _check_cycles(self, changed: Iterable[Node]) -> None:
        """Search from each changed node along outgoing edges; reaching it again is a cycle."""
        for start in sorted(changed, key=_order_key):
            parents: dict[Node, Node | None] = {start: None}
            queue: deque[Node] = deque([start])
            while queue:
                node = queue.popleft()
                for target in self._targets(node):
                    if target == start:
                        raise self._cycle(start, node, parents)
                    if target not in parents:
                        parents[target] = node
                        queue.append(target)

    def _targets(self, node: Node) -> list[Node]:
        match node:
            case SlotNode():
                return list(self.index.edges_of(node))
            case CalendarNode():
                return list(self.index.slots_with_edges(CALENDAR, node.calendar_id))
            case DimensionNode():
                return []

    def _cycle(self, start: Node, last: Node, parents: dict[Node, Node | None]) -> TimeCycleError:
        path: list[Node] = [last]
        while (parent := parents[path[-1]]) is not None:
            path.append(parent)
        path.reverse()
        names = [describe(node) for node in [*path, start]]
        return TimeCycleError(
            "These time anchors would depend on themselves: " + " → ".join(names) + ".",
            context={"path": names},
        )

    def _closure(self, changed: set[Node]) -> tuple[set[Node], dict[Node, set[Node]]]:
        """The affected set (step 3) and, per node, the affected nodes it depends on."""
        affected: set[Node] = set(changed)
        depends_on: dict[Node, set[Node]] = {node: set() for node in changed}
        frontier = list(changed)
        while frontier:
            found = self.index.dependents_of_many(frontier)
            following: list[Node] = []
            for target in frontier:
                dependents: list[Node] = list(found.get(target, []))
                if isinstance(target, SlotNode) and target.type == CALENDAR:
                    dependents.append(CalendarNode(target.id))
                for dependent in dependents:
                    depends_on.setdefault(dependent, set()).add(target)
                    if dependent not in affected:
                        affected.add(dependent)
                        following.append(dependent)
            frontier = following
        return affected, depends_on

    def _resolver(self, dimension_id: str, known: dict[SlotNode, Resolution]) -> Resolver | None:
        try:
            resolver = Resolver(self.context, dimension_id)
        except ConflictError:
            return None
        resolver.known = known
        return resolver


class _Run:
    """One propagation: resolves the affected nodes in topological order (steps 4-6)."""

    def __init__(
        self, writer: TimeWriter, affected: set[Node], depends_on: dict[Node, set[Node]]
    ) -> None:
        self.writer = writer
        self.session = writer.session
        self.slots = writer.slots
        self.affected = affected
        self.depends_on = depends_on
        self.known: dict[SlotNode, Resolution] = {}
        self.resolvers: dict[str, Resolver | None] = {}
        self.values = self._load([n for n in affected if isinstance(n, SlotNode)])
        self.pending: dict[str, list[SlotUpdate]] = {}
        self.result = Propagation(affected=len(affected))
        self.followers: set[Node] = set()
        """Dependents of series refreshed without their own slots being affected."""

    def _load(self, nodes: Sequence[SlotNode]) -> dict[SlotNode, SlotValue]:
        by_type: dict[str, list[SlotKey]] = {}
        for node in nodes:
            by_type.setdefault(node.type, []).append(SlotKey(node.id, node.slot))
        values: dict[SlotNode, SlotValue] = {}
        for record_type, keys in by_type.items():
            if self.slots.get(record_type) is None:
                continue
            for start in range(0, len(keys), BATCH):
                loaded = self.slots.load(self.session, record_type, keys[start : start + BATCH])
                values.update({SlotNode(record_type, k.id, k.slot): v for k, v in loaded.items()})
        return values

    def execute(self) -> Propagation:
        order, stuck = self._order()
        for node in order:
            match node:
                case SlotNode():
                    self._slot(node)
                case CalendarNode():
                    self._calendar(node)
                case DimensionNode():
                    pass  # its value (D) was written by the service
        for node in sorted(stuck, key=_order_key):
            if isinstance(node, SlotNode) and node in self.values:
                self._fail(node, TimeStatus.CYCLE, "time_cycle", "The anchors form a cycle.")
        self._write()
        self._check_order()
        self._series()
        return self.result

    def _order(self) -> tuple[list[Node], set[Node]]:
        """Kahn's algorithm over the affected subgraph; nodes left over are on a cycle."""
        waiting = {node: len(self.depends_on.get(node, ())) for node in self.affected}
        followers: dict[Node, list[Node]] = {}
        for node, targets in self.depends_on.items():
            for target in targets:
                followers.setdefault(target, []).append(node)
        ready = deque(sorted((n for n, count in waiting.items() if count == 0), key=_order_key))
        order: list[Node] = []
        while ready:
            node = ready.popleft()
            order.append(node)
            for follower in followers.get(node, ()):
                waiting[follower] -= 1
                if waiting[follower] == 0:
                    ready.append(follower)
        return order, {node for node, count in waiting.items() if count > 0}

    def _resolver(self, dimension_id: str | None) -> Resolver | None:
        if dimension_id is None:
            return None
        if dimension_id not in self.resolvers:
            self.resolvers[dimension_id] = self.writer._resolver(dimension_id, self.known)
        return self.resolvers[dimension_id]

    def _slot(self, node: SlotNode) -> None:
        value = self.values.get(node)
        if value is None or value.spec is None:
            return  # purged meanwhile, or a slot without a spec (e.g. a local calendar anchor)
        resolver = self._resolver(value.dimension_id)
        if resolver is None:
            self._fail(node, TimeStatus.UNRESOLVED_REF, "unresolved_ref",
                       "The record has no dimension to resolve in.")  # fmt: skip
            return
        _provider, definition = self.slots.slot(node.type, node.slot)
        if isinstance(value.spec, TimePoint):
            spec = value.spec
            if node.type == CALENDAR:
                from lore.core.time.calendars import resolvable  # noqa: PLC0415 (import cycle)

                spec = resolvable(spec)
            resolution = resolver.resolve(spec)
        else:
            start = (
                resolver.slot(node.type, node.id, definition.start)
                if value.spec.kind in ("duration", "instant", "unknown")
                else Resolution(None, TimeStatus.OK)  # the end doesn't use its start
            )
            resolution = resolver.resolve_end(value.spec, start)
        if resolution.status in GOOD and resolution.t is not None:
            self._store(node, resolution.t, resolution.status, resolution)
            return
        problem = resolution.problem
        status = resolution.status or TimeStatus.INVALID_DATE
        code = problem.code if problem is not None else status.value
        message = problem.message if problem is not None else "The time point doesn't resolve."
        self._fail(node, status, code, message, resolution.t)

    def _fail(
        self, node: SlotNode, status: TimeStatus, code: str, message: str, t: int | None = None
    ) -> None:
        """Keep the last good moment; the slot breaks a hard rule."""
        value = self.values[node]
        self.result.violations.append(Violation(node.type, node.id, node.slot, code, message, t))
        self._store(node, value.t, status, None)

    def _store(
        self, node: SlotNode, t: int | None, status: TimeStatus, resolution: Resolution | None
    ) -> None:
        value = self.values[node]
        self.known[node] = self._known(value, t, status, resolution)
        if t == value.t and status == value.status:
            return
        update = SlotUpdate(SlotKey(node.id, node.slot), t, status)
        self.result.updated.append(node)
        if node.type == CALENDAR:
            self.slots.write(self.session, CALENDAR, [update])  # the calendar compiles next
        else:
            self.pending.setdefault(node.type, []).append(update)

    @staticmethod
    def _known(
        value: SlotValue, t: int | None, status: TimeStatus, resolution: Resolution | None
    ) -> Resolution:
        """How dependents see a slot after this run: its stored moment, with the extent and
        precision of its new resolution (exact without one)."""
        if t is None:
            return Resolution(None, TimeStatus.UNRESOLVED_REF)
        extent, precision, calendar_id = (t, t + 1), BASE, None
        if resolution is not None and resolution.extent is not None and resolution.t is not None:
            lo, hi = resolution.extent
            extent = (t + lo - resolution.t, t + hi - resolution.t)
            precision, calendar_id = resolution.precision, resolution.calendar_id
        trashed = value.trashed or status == TimeStatus.TRASHED_REF
        good = TimeStatus.TRASHED_REF if trashed else TimeStatus.OK
        return Resolution(t, good, extent, precision, calendar_id=calendar_id)

    def _calendar(self, node: CalendarNode) -> None:
        from lore.core.time.calendars import compiled_calendar  # noqa: PLC0415 (import cycle)

        row = self.session.get(Calendar, node.calendar_id)
        if row is None:
            return
        self.session.flush()
        try:
            compiled_calendar(self.writer.context, node.calendar_id)
            status = "ok"
        except ConflictError:
            status = "error"
            self.result.violations.append(
                Violation(CALENDAR, node.calendar_id, "definition", "calendar_error",
                          "The calendar no longer compiles with its anchors' new moments.")
            )  # fmt: skip
        if row.compile_status != status:
            row.compile_status = status
        for resolver in self.resolvers.values():
            if resolver is not None:
                resolver.forget_calendar(node.calendar_id)

    def _write(self) -> None:
        """Store the new values (step 5), one batch per record type. Slots sharing a status
        column get the worst status of the record's updated slots."""
        for record_type, updates in sorted(self.pending.items()):
            provider = self.slots.get(record_type)
            assert provider is not None
            worst: dict[tuple[str, str | None], TimeStatus] = {}
            for update in updates:
                column = _status_column(provider, update.key.slot)
                key = (update.key.id, column)
                if key not in worst or _severity(update.status) > _severity(worst[key]):
                    worst[key] = update.status
            combined = [
                SlotUpdate(u.key, u.t, worst[(u.key.id, _status_column(provider, u.key.slot))])
                for u in updates
            ]
            for start in range(0, len(combined), BATCH):
                self.slots.write(self.session, record_type, combined[start : start + BATCH])
        self.pending.clear()

    def _check_order(self) -> None:
        """Hard check: an end may not precede the start it resolves from (checked for every
        affected end, and for the ends of every affected start)."""
        ends: set[SlotNode] = set()
        for node in self.known:
            provider = self.slots.get(node.type)
            if provider is None:
                continue
            for definition in provider.slots:
                if definition.spec != "end" or definition.is_family:
                    continue
                if node.slot in (definition.name, definition.start):
                    ends.add(SlotNode(node.type, node.id, definition.name))
        starts: dict[SlotNode, SlotNode] = {}
        for end in ends:
            provider, definition = self.slots.slot(end.type, end.slot)
            if provider.slot(definition.start) is not None:
                starts[end] = SlotNode(end.type, end.id, definition.start)
        needed = [n for n in {*starts, *starts.values()} if n not in self.known]
        stored = self._load(sorted(needed))
        for end in sorted(starts):
            end_t = self._t(end, stored)
            start_t = self._t(starts[end], stored)
            if end_t is not None and start_t is not None and end_t < start_t:
                self.result.violations.append(
                    Violation(end.type, end.id, end.slot, "end_before_start",
                              "The end lies before the start.", end_t)
                )  # fmt: skip

    def _series(self) -> None:
        """Refresh the bounds of the recurring series the run touched (``recurrence.md`` §5.5):
        through an event slot, the rule's calendar or the dimension's duration."""
        from lore.core.time.series import refresh_series  # noqa: PLC0415 (import cycle)

        events = {n.id for n in self.affected if isinstance(n, SlotNode) and n.type == EVENT}
        calendars = {n.calendar_id for n in self.affected if isinstance(n, CalendarNode)}
        dimensions = {n.dimension_id for n in self.affected if isinstance(n, DimensionNode)}
        if not (events or calendars or dimensions):
            return
        problems, refreshed = refresh_series(self.writer.context, events, calendars, dimensions)
        for problem in problems:
            self.result.violations.append(
                Violation(EVENT, problem.entity_id, "recurrence", problem.code, problem.message)
            )
        quiet = [i for i in refreshed if SlotNode(EVENT, i, "start") not in self.affected]
        if quiet:
            before = set(self.writer.changed)
            self.writer.touch_series(*quiet)
            self.followers = self.writer.changed - before
            self.writer.changed = before

    def _t(self, node: SlotNode, stored: dict[SlotNode, SlotValue]) -> int | None:
        known = self.known.get(node)
        if known is not None:
            return known.t
        value = stored.get(node)
        return None if value is None or value.spec is None else value.t


# --- entity lifecycle --------------------------------------------------------------------------


def after_trash(context: VaultContext, entity_id: str) -> None:
    """An entity was trashed or restored: its dependents resolve again (``trashed_ref``)."""
    writer = TimeWriter(context)
    writer.touch_entity(entity_id)
    writer.propagate()


def freeze_on_purge(context: VaultContext, entity: Any) -> None:
    """The core purge hook (``time-model.md`` §7.3): freeze what depends on the entity's
    records, then drop their own edges."""
    writer = TimeWriter(context)
    writer.freeze_dependents(entity.id)
    for record_type, record_id in sorted(writer._records_of_entity(entity.id)):
        writer.index.drop_record(record_type, record_id)
    writer.propagate()


def after_revert(context: VaultContext, changes: Sequence[Any]) -> Propagation:
    """After an undo (``history.service``): rebuild the edges of every reverted time-bearing
    row from its specs (dropping them for rows that are gone), refresh the trash state of
    reverted entities, and propagate (strict: the caller turns a violation into a revert
    conflict)."""
    writer = TimeWriter(context)
    providers = {
        getattr(provider.model, "__tablename__", None): provider
        for provider in writer.slots.providers
    }
    for change in changes:
        if change.table_name == "entities":
            writer.touch_entity(change.row_id)
            continue
        provider = providers.get(change.table_name)
        if provider is None:
            continue
        record_type, record_id = provider.record_type, str(change.row_id)
        writer.index.drop_record(record_type, record_id)
        keys = provider.record_keys(writer.session, record_id)
        values = writer.slots.load(writer.session, record_type, keys) if keys else {}
        for key, value in values.items():
            writer.set_spec(record_type, record_id, key.slot, value.spec,
                            dimension_id=value.dimension_id)  # fmt: skip
        if record_type == CALENDAR:
            writer.touch(CalendarNode(record_id))
        elif record_type == "dimension":
            writer.touch(DimensionNode(record_id))
    return writer.propagate()


def _status_column(provider: Any, slot: str) -> str | None:
    definition = provider.slot(slot)
    return None if definition is None else definition.status_column


def _severity(status: TimeStatus) -> int:
    return _SEVERITY.get(status, 2)


def _order_key(node: Node) -> tuple[int, tuple[str, ...]]:
    match node:
        case SlotNode():
            return (0, (node.type, node.id, node.slot))
        case CalendarNode():
            return (1, (node.calendar_id,))
        case DimensionNode():
            return (2, (node.dimension_id,))


__all__ = [
    "Propagation",
    "TimeConstraintError",
    "TimeCycleError",
    "TimeWriter",
    "Violation",
    "after_revert",
    "after_trash",
    "constraint_error",
    "describe",
    "freeze_on_purge",
]
