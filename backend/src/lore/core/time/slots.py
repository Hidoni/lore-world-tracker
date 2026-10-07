"""The slot registry (``time-model.md`` §6, ADR-0007): which records own time slots, where each
slot is stored and whether other records may anchor to it.

A **slot provider** registers one record type: its ORM model, its slots and how to load and store
them. Core registers its record types in ``lore.core.time.kinds.CORE_SLOT_PROVIDERS``; modules
through ``ModuleSpec.slot_providers`` (record types named ``<module id>.<type>``). Resolution and
propagation only ever touch slots through the registry, so they work for any table.

A ``SlotDef`` names one slot (``start``) or a family of slots (``exclusion:*`` covers
``exclusion:0.from`` …; ``*`` covers every slot name). Fixed slots stored in columns
(``<slot>_spec``, ``<slot>_t``, ``time_status``) get a default loader and writer; slots that live
elsewhere (families, and ``custom`` slots: inside JSON documents, in keyed rows) need the
provider's own, which only ever see those slots. One record type may mix both (an event's
``start`` column and its rule's ``recurrence_until``).
"""

import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import bindparam, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from lore.chronology.schema import EndSpec, SlotRef, TimePoint
from lore.core.entities.models import Entity
from lore.core.history.recorder import record_bulk, recorded_tables
from lore.core.history.tables import Row
from lore.core.time.models import Timeline
from lore.core.time.status import TimeStatus

type SpecKind = Literal["time_point", "end"]

_RECORD_TYPE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")
_SLOT_NAME = re.compile(r"[a-z][a-z0-9_]*")
_BATCH = 5000  # ids per IN (...)
CORE = "core"


@dataclass(frozen=True)
class SlotDef:
    """One slot of a record type, or a family of slots.

    ``name`` is a slot name (``start``), a family (``exclusion:*`` matches ``exclusion:<any>``) or
    ``*`` (any slot not matched otherwise). The column names default to ``<name>_spec`` /
    ``<name>_t`` for fixed slots; families have no columns, so their provider needs its own loader
    and writer. ``custom`` slots have a fixed name but no columns either (time points inside a
    JSON document). ``status_column`` may be shared by several slots of the record.
    """

    name: str
    spec: SpecKind = "time_point"
    referenceable: bool = False
    spec_column: str | None = None
    resolved_column: str | None = None
    status_column: str | None = "time_status"
    start: str = "start"
    """For end specs: the slot of the same record the end resolves from (and may not precede)."""
    custom: bool = False
    """Stored by the provider's own loader and writer (no columns)."""

    @property
    def is_family(self) -> bool:
        return self.name == "*" or self.name.endswith(":*")

    @property
    def columns(self) -> tuple[str, str] | None:
        """``(spec column, resolved column)`` of a fixed slot; ``None`` for families and custom
        slots."""
        if self.is_family or self.custom:
            return None
        return (
            self.spec_column or f"{self.name}_spec",
            self.resolved_column or f"{self.name}_t",
        )

    def matches(self, slot: str) -> bool:
        if self.name == "*":
            return True
        if self.is_family:
            prefix = self.name[:-1]  # keeps the colon
            return slot.startswith(prefix) and len(slot) > len(prefix)
        return slot == self.name


@dataclass(frozen=True)
class SlotKey:
    """A slot of a stored record, as providers see it (the record type is the provider's)."""

    id: str
    slot: str


@dataclass(frozen=True)
class SlotValue:
    """A slot's stored state: its spec, last good moment and status. ``trashed`` tells
    resolution that the record is in the trash (``time-model.md`` §7.3)."""

    spec: TimePoint | EndSpec | None
    t: int | None
    status: TimeStatus | None
    trashed: bool = False
    dimension_id: str | None = None
    """The record's dimension (what its time points resolve in)."""


@dataclass(frozen=True)
class SlotUpdate:
    """What a resolution writes: the moment to store (the caller passes the last good one back
    when resolution failed) and the status."""

    key: SlotKey
    t: int | None
    status: TimeStatus


@dataclass(frozen=True)
class SpecUpdate:
    """A new spec for a slot (anchor freezing, ``time-model.md`` §7.3)."""

    key: SlotKey
    spec: TimePoint | EndSpec


type SlotLoader = Callable[[Session, Sequence[SlotKey]], dict[SlotKey, SlotValue]]
"""Load the given slots. Records that don't exist (purged) are absent from the result."""

type SlotWriter = Callable[[Session, Sequence[SlotUpdate]], None]
"""Store resolved values. Must write through the session (history records the changes) or call
``history.record_bulk``."""


@dataclass(frozen=True)
class SlotMoment:
    """A resolved slot value, e.g. one that a new dimension duration would exclude."""

    record_type: str
    id: str
    slot: str
    t: int


type SpecWriter = Callable[[Session, Sequence[SpecUpdate]], None]
"""Store new specs (through the session, so history records them)."""

type SlotLister = Callable[[Session], list[SlotKey]]
"""Every slot of the record type that has a spec (``lore vault check``)."""

type BeyondQuery = Callable[[Session, str, int], list[SlotMoment]]
"""``(session, dimension id, bound)``: slots of the dimension's records resolved after ``bound``
(R-DIM-3)."""


@dataclass(frozen=True)
class SlotProvider:
    """A record type with time slots (``ModuleSpec.slot_providers`` for module records).

    Slots with columns are loaded and written by column access on ``model``; ``load``/``write``
    (and ``write_spec``, ``keys``, ``beyond``) handle the families and custom slots. Trashed rows
    are reported for a model with ``deleted_at``, or through ``entity_column`` when the row's trash
    state is its entity's (extension tables). ``id_column`` is the record id the slot refs use.

    How to find the records of a dimension (R-DIM-3): ``dimension_column`` (holds the dimension
    id), ``timeline_column`` (holds a timeline id) or a custom ``beyond`` query (required for
    slot families).
    """

    record_type: str
    model: type
    slots: tuple[SlotDef, ...]
    id_column: str = "id"
    load: SlotLoader | None = None
    write: SlotWriter | None = None
    entity_column: str | None = None
    dimension_column: str | None = None
    timeline_column: str | None = None
    beyond: BeyondQuery | None = None
    write_spec: SpecWriter | None = None
    keys: SlotLister | None = None

    def slot(self, name: str) -> SlotDef | None:
        """The definition covering a slot name: an exact name wins over families, ``*`` last."""
        ordered = sorted(self.slots, key=lambda s: (s.name == "*", s.is_family))
        return next((definition for definition in ordered if definition.matches(name)), None)

    def in_columns(self, slot: str) -> bool:
        """Whether a slot is stored in columns (else by the provider's own functions)."""
        definition = self.slot(slot)
        return definition is not None and self._stored_in_columns(definition)

    def _stored_in_columns(self, definition: SlotDef) -> bool:
        """A fixed slot whose columns exist (with a loader, missing columns make it custom)."""
        columns = definition.columns
        table = getattr(self.model, "__table__", None)
        return (
            columns is not None
            and table is not None
            and all(column in table.columns for column in columns)
        )

    def load_slots(self, session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
        columns = [key for key in keys if self.in_columns(key.slot)]
        custom = [key for key in keys if not self.in_columns(key.slot)]
        result = _load_columns(self, session, columns) if columns else {}
        if custom:
            if self.load is None:
                raise SlotError("unknown_slot", f"{self.record_type} has no loader")
            result.update(self.load(session, custom))
        return result

    def write_slots(self, session: Session, updates: Sequence[SlotUpdate]) -> None:
        columns = [u for u in updates if self.in_columns(u.key.slot)]
        custom = [u for u in updates if not self.in_columns(u.key.slot)]
        if columns:
            _write_columns(self, session, columns)
        if custom:
            if self.write is None:
                raise SlotError("unknown_slot", f"{self.record_type} has no writer")
            self.write(session, custom)

    def moments_beyond(self, session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
        found = _beyond_columns(self, session, dimension_id, bound)
        if self.beyond is not None:
            found += self.beyond(session, dimension_id, bound)
        return found

    def write_specs(self, session: Session, updates: Sequence[SpecUpdate]) -> None:
        """Store new specs: the spec columns of column slots, the provider's ``write_spec`` for
        the others (``SlotError`` ``not_supported`` without one)."""
        columns = [u for u in updates if self.in_columns(u.key.slot)]
        custom = [u for u in updates if not self.in_columns(u.key.slot)]
        if columns:
            _write_spec_columns(self, session, columns)
        if custom:
            if self.write_spec is None:
                raise SlotError(
                    "not_supported", f"{self.record_type} slots can't be given a new spec"
                )
            self.write_spec(session, custom)

    def all_keys(self, session: Session) -> list[SlotKey]:
        """Every slot with a spec: the spec columns of column slots and the provider's ``keys``
        (custom slots without ``keys`` are never listed)."""
        found = _keys_columns(self, session)
        if self.keys is not None:
            found += self.keys(session)
        return sorted(found, key=lambda key: (key.id, key.slot))

    def record_keys(self, session: Session, record_id: str) -> list[SlotKey]:
        """The slots of one record that have a spec."""
        found: list[SlotKey] = []
        row = _rows(self, session, [record_id]).get(record_id) if self._column_slots() else None
        if row is not None:
            found = [
                SlotKey(record_id, slot.name)
                for slot in self._column_slots()
                if slot.columns is not None and getattr(row, slot.columns[0]) is not None
            ]
        if self.keys is not None:
            found += [key for key in self.keys(session) if key.id == record_id]
        return found

    def _column_slots(self) -> list[SlotDef]:
        return [slot for slot in self.slots if self._stored_in_columns(slot)]

    def records_of_entity(self, session: Session, entity_id: str) -> list[str]:
        """Ids of the records that belong to an entity (through ``entity_column``)."""
        if self.entity_column is None:
            return []
        if self.entity_column == self.id_column:
            return [entity_id]
        model: Any = self.model
        ids: Iterable[Any] = session.scalars(
            select(getattr(model, self.id_column)).where(
                getattr(model, self.entity_column) == entity_id
            )
        )
        return [str(record_id) for record_id in ids]


class SlotError(ValueError):
    """A slot reference the registry can't accept. ``code`` is stable (API ``code``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SlotRegistry:
    """Every record type with time slots: core's plus every module's (enabled or not: anchors into
    a disabled module's records keep resolving)."""

    providers: tuple[SlotProvider, ...] = ()
    _by_type: dict[str, SlotProvider] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_type", {p.record_type: p for p in self.providers})

    def get(self, record_type: str) -> SlotProvider | None:
        return self._by_type.get(record_type)

    def record_types(self) -> list[str]:
        return [provider.record_type for provider in self.providers]

    def slot(self, record_type: str, slot: str) -> tuple[SlotProvider, SlotDef]:
        """The provider and definition of a slot; ``SlotError`` (``unknown_slot``) otherwise."""
        provider = self._by_type.get(record_type)
        if provider is None:
            raise SlotError("unknown_slot", f"unknown record type {record_type!r}")
        definition = provider.slot(slot)
        if definition is None:
            raise SlotError("unknown_slot", f"{record_type} has no time slot {slot!r}")
        return provider, definition

    def check_ref(self, ref: SlotRef) -> SlotDef:
        """Check that a relative anchor may point at ``ref`` (``time-model.md`` §5.2, §6):
        the slot exists (``unknown_slot``) and is referenceable (``slot_not_referenceable``)."""
        _provider, definition = self.slot(ref.type, ref.slot)
        if not definition.referenceable:
            raise SlotError(
                "slot_not_referenceable", f"{ref.type} slot {ref.slot!r} cannot be referenced"
            )
        return definition

    def load(
        self, session: Session, record_type: str, keys: Sequence[SlotKey]
    ) -> dict[SlotKey, SlotValue]:
        for key in keys:
            self.slot(record_type, key.slot)
        return self._provider(record_type).load_slots(session, keys)

    def write(self, session: Session, record_type: str, updates: Sequence[SlotUpdate]) -> None:
        for update in updates:
            self.slot(record_type, update.key.slot)
        self._provider(record_type).write_slots(session, updates)

    def write_specs(
        self, session: Session, record_type: str, updates: Sequence[SpecUpdate]
    ) -> None:
        for update in updates:
            self.slot(record_type, update.key.slot)
        self._provider(record_type).write_specs(session, updates)

    def moments_beyond(self, session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
        """Every slot of the dimension's records resolved after ``bound``, sorted (R-DIM-3: these
        block a duration change to ``bound``)."""
        found = [
            moment
            for provider in self.providers
            for moment in provider.moments_beyond(session, dimension_id, bound)
        ]
        return sorted(found, key=lambda m: (m.record_type, m.id, m.slot))

    def _provider(self, record_type: str) -> SlotProvider:
        provider = self._by_type.get(record_type)
        if provider is None:
            raise SlotError("unknown_slot", f"unknown record type {record_type!r}")
        return provider


def validate_providers(
    owner: str, providers: Iterable[object], models: Collection[type]
) -> list[str]:
    """Problems with one owner's slot providers (``core`` or a module id). Module record types
    must be ``<module id>.<type>`` and use the module's own models; core ones are unprefixed."""
    problems: list[str] = []
    for provider in providers:
        if not isinstance(provider, SlotProvider):
            problems.append(f"{owner}: slot providers must be SlotProvider")
            continue
        where = f"{owner}: slot provider {provider.record_type!r}"
        if not _RECORD_TYPE.fullmatch(provider.record_type):
            problems.append(f"{where}: record types must match {_RECORD_TYPE.pattern}")
        elif owner == CORE and "." in provider.record_type:
            problems.append(f"{where}: core record types are unprefixed")
        elif owner != CORE and not provider.record_type.startswith(owner + "."):
            problems.append(f"{where}: record types must be named '{owner}.<type>'")
        if owner != CORE and provider.model not in models:
            problems.append(f"{where}: the model isn't one of the module's models")
        problems += _validate_slots(where, provider)
    return problems


def validate_registry(providers: Iterable[tuple[str, SlotProvider]]) -> list[str]:
    """Problems across owners: duplicate record types."""
    problems: list[str] = []
    owners: dict[str, str] = {}
    for owner, provider in providers:
        if provider.record_type in owners:
            problems.append(
                f"{owner}: slot provider {provider.record_type!r} is already registered by "
                f"{owners[provider.record_type]}"
            )
        owners[provider.record_type] = owner
    return problems


def _validate_slots(where: str, provider: SlotProvider) -> list[str]:
    problems: list[str] = []
    table = getattr(provider.model, "__table__", None)
    if table is None:
        return [f"{where}: {provider.model.__name__} is not a mapped table model"]
    columns = set(table.columns.keys())
    if provider.id_column not in columns:
        problems.append(f"{where}: no id column {provider.id_column!r}")
    if not provider.slots:
        problems.append(f"{where}: declares no slots")
    problems += _validate_lookup(where, provider, columns)
    seen: set[str] = set()
    custom = provider.load is not None and provider.write is not None
    if (provider.load is None) != (provider.write is None):
        problems.append(f"{where}: give both a loader and a writer, or neither")
    for slot in provider.slots:
        name = slot.name
        base = name[:-2] if name.endswith(":*") else name
        if name != "*" and not _SLOT_NAME.fullmatch(base):
            problems.append(f"{where}: slot {name!r} must be a name, 'name:*' or '*'")
        if name in seen:
            problems.append(f"{where}: duplicate slot {name!r}")
        seen.add(name)
        if slot.is_family or slot.custom:
            if not custom:
                what = "slot family" if slot.is_family else "custom slot"
                problems.append(f"{where}: {what} {name!r} needs a loader and a writer")
            continue
        wanted = [*(slot.columns or ()), slot.status_column]
        missing = [c for c in wanted if c is not None and c not in columns]
        if missing and not custom:
            problems += [f"{where}: slot {name!r} has no column {c!r}" for c in missing]
    return problems


def _validate_lookup(where: str, provider: SlotProvider, columns: set[str]) -> list[str]:
    """The columns that find a row's trash state and dimension."""
    problems: list[str] = []
    for label, column in (
        ("entity", provider.entity_column),
        ("dimension", provider.dimension_column),
        ("timeline", provider.timeline_column),
    ):
        if column is not None and column not in columns:
            problems.append(f"{where}: no {label} column {column!r}")
    if (provider.dimension_column is None) == (provider.timeline_column is None) and (
        provider.beyond is None
    ):
        problems.append(
            f"{where}: give one of dimension_column and timeline_column, or a beyond query"
        )
    if provider.beyond is None and any(slot.is_family or slot.custom for slot in provider.slots):
        problems.append(f"{where}: slot families and custom slots need a beyond query")
    return problems


# --- the default loader and writer: fixed slots in columns -------------------------------------


def _fixed(provider: SlotProvider, slot: str) -> SlotDef:
    definition = provider.slot(slot)
    if definition is None or definition.columns is None:
        raise SlotError("unknown_slot", f"{provider.record_type} has no column slot {slot!r}")
    return definition


def _rows(provider: SlotProvider, session: Session, ids: Iterable[str]) -> dict[str, Any]:
    model: Any = provider.model
    id_attr = getattr(model, provider.id_column)
    wanted = sorted(set(ids))
    rows: Sequence[Any] = (
        session.scalars(select(model).where(id_attr.in_(wanted))).all() if wanted else []
    )
    return {str(getattr(row, provider.id_column)): row for row in rows}


def _dimensions(provider: SlotProvider, session: Session, rows: Iterable[Any]) -> dict[str, str]:
    """Record id → dimension id of loaded rows (``dimension_column`` or ``timeline_column``)."""
    rows = list(rows)
    if provider.dimension_column is not None:
        return {
            str(getattr(r, provider.id_column)): getattr(r, provider.dimension_column)
            for r in rows
            if getattr(r, provider.dimension_column) is not None
        }
    if provider.timeline_column is None:
        return {}
    timelines = {
        str(getattr(r, provider.id_column)): getattr(r, provider.timeline_column) for r in rows
    }
    wanted = sorted({t for t in timelines.values() if t is not None})
    found: dict[str, str] = dict(
        session.execute(
            select(Timeline.entity_id, Timeline.dimension_id).where(Timeline.entity_id.in_(wanted))
        ).all()
    )
    return {i: found[t] for i, t in timelines.items() if t in found}


def _load_columns(
    provider: SlotProvider, session: Session, keys: Sequence[SlotKey]
) -> dict[SlotKey, SlotValue]:
    rows = _rows(provider, session, (key.id for key in keys))
    trashed_ids = _trashed(provider, session, rows.values())
    dimensions = _dimensions(provider, session, rows.values())
    result: dict[SlotKey, SlotValue] = {}
    for key in keys:
        row = rows.get(key.id)
        if row is None:
            continue
        definition = _fixed(provider, key.slot)
        spec_column, resolved_column = definition.columns or ("", "")
        status = getattr(row, definition.status_column) if definition.status_column else None
        trashed = key.id in trashed_ids
        result[key] = SlotValue(
            spec=getattr(row, spec_column),
            t=getattr(row, resolved_column),
            status=None if status is None else TimeStatus(status),
            trashed=trashed,
            dimension_id=dimensions.get(key.id),
        )
    return result


def _trashed(provider: SlotProvider, session: Session, rows: Iterable[Any]) -> set[str]:
    """Ids of the loaded rows that are in the trash (their own ``deleted_at`` or their entity's)."""
    rows = list(rows)
    if hasattr(provider.model, "deleted_at"):
        return {str(getattr(r, provider.id_column)) for r in rows if r.deleted_at is not None}
    if provider.entity_column is None:
        return set()
    owners = {
        str(getattr(r, provider.entity_column)): str(getattr(r, provider.id_column)) for r in rows
    }
    trashed = session.scalars(
        select(Entity.id).where(Entity.id.in_(sorted(owners)), Entity.deleted_at.is_not(None))
    )
    return {owners[entity_id] for entity_id in trashed}


def _beyond_columns(
    provider: SlotProvider, session: Session, dimension_id: str, bound: int
) -> list[SlotMoment]:
    model: Any = provider.model
    if not provider._column_slots() or (
        provider.dimension_column is None and provider.timeline_column is None
    ):
        return []
    if provider.dimension_column is not None:
        in_dimension = getattr(model, provider.dimension_column) == dimension_id
    else:
        timeline_ids = select(Timeline.entity_id).where(Timeline.dimension_id == dimension_id)
        in_dimension = getattr(model, str(provider.timeline_column)).in_(timeline_ids)
    found: list[SlotMoment] = []
    for slot in provider._column_slots():
        assert slot.columns is not None
        resolved = getattr(model, slot.columns[1])
        rows = session.execute(
            select(getattr(model, provider.id_column), resolved).where(
                in_dimension, resolved > bound
            )
        )
        found += [SlotMoment(provider.record_type, str(i), slot.name, t) for i, t in rows]
    return found


def _raw_rows(session: Session, table: Any, id_column: str, ids: Sequence[str]) -> dict[str, Row]:
    """Rows as SQLite stores them (raw values, what history records), by id."""
    found: dict[str, Row] = {}
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start : start + _BATCH]
        marks = ", ".join("?" for _ in chunk)
        result = session.connection().exec_driver_sql(
            f'SELECT * FROM "{table.name}" WHERE "{id_column}" IN ({marks})', tuple(chunk)
        )
        found.update({str(row[id_column]): dict(row) for row in result.mappings()})
    return found


def _write_columns(provider: SlotProvider, session: Session, updates: Sequence[SlotUpdate]) -> None:
    """One ``UPDATE`` per column set (``executemany``), recorded with ``record_bulk``; loaded
    ORM objects of the rows are expired."""
    model: Any = provider.model
    table = model.__table__
    session.flush()
    ids = sorted({update.key.id for update in updates})
    before = _raw_rows(session, table, provider.id_column, ids)
    missing = [record_id for record_id in ids if record_id not in before]
    if missing:
        raise SlotError("unresolved_ref", f"{provider.record_type} {missing[0]} not found")
    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for update in updates:
        definition = _fixed(provider, update.key.slot)
        _spec_column, resolved_column = definition.columns or ("", "")
        params = {"_id": update.key.id, "_t": update.t, "_status": update.status.value}
        groups.setdefault((resolved_column, definition.status_column), []).append(params)
    id_column = table.c[provider.id_column]
    for (resolved_column, status_column), batch in groups.items():
        moment = bindparam("_t", type_=table.c[resolved_column].type)
        values: dict[str, Any] = {resolved_column: moment}
        if status_column is not None:
            values[status_column] = bindparam("_status")
        statement = sa_update(table).where(id_column == bindparam("_id")).values(values)
        session.execute(statement, batch)
    after = _raw_rows(session, table, provider.id_column, ids)
    if table.name in recorded_tables(session):
        record_bulk(session, table, list(before.values()), list(after.values()))
    wanted = set(ids)
    for obj in list(session.identity_map.values()):
        if isinstance(obj, model) and str(getattr(obj, provider.id_column)) in wanted:
            session.expire(obj)


def _write_spec_columns(
    provider: SlotProvider, session: Session, updates: Sequence[SpecUpdate]
) -> None:
    rows = _rows(provider, session, (update.key.id for update in updates))
    for update in updates:
        row = rows.get(update.key.id)
        if row is None:
            raise SlotError("unresolved_ref", f"{provider.record_type} {update.key.id} not found")
        spec_column, _resolved_column = _fixed(provider, update.key.slot).columns or ("", "")
        setattr(row, spec_column, update.spec)


def _keys_columns(provider: SlotProvider, session: Session) -> list[SlotKey]:
    model: Any = provider.model
    found: list[SlotKey] = []
    for slot in provider._column_slots():
        assert slot.columns is not None
        spec = getattr(model, slot.columns[0])
        ids: Iterable[Any] = session.scalars(
            select(getattr(model, provider.id_column)).where(spec.is_not(None))
        )
        found += [SlotKey(str(record_id), slot.name) for record_id in ids]
    return sorted(found, key=lambda key: (key.id, key.slot))


__all__ = [
    "BeyondQuery",
    "SlotDef",
    "SlotError",
    "SlotKey",
    "SlotLister",
    "SlotLoader",
    "SlotMoment",
    "SlotProvider",
    "SlotRegistry",
    "SlotUpdate",
    "SlotValue",
    "SlotWriter",
    "SpecKind",
    "SpecUpdate",
    "SpecWriter",
    "validate_providers",
    "validate_registry",
]
