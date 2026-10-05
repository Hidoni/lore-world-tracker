"""The slot registry (``time-model.md`` §6, ADR-0007): which records own time slots, where each
slot is stored and whether other records may anchor to it.

A **slot provider** registers one record type: its ORM model, its slots and how to load and store
them. Core registers its record types in ``CORE_SLOT_PROVIDERS``; modules through
``ModuleSpec.slot_providers`` (record types named ``<module id>.<type>``). Resolution and
propagation only ever touch slots through the registry, so they work for any table.

A ``SlotDef`` names one slot (``start``) or a family of slots (``exclusion:*`` covers
``exclusion:0.from`` …; ``*`` covers every slot name). Fixed slots stored in columns
(``<slot>_spec``, ``<slot>_t``, ``time_status``) get a default loader and writer; record types
whose slots live elsewhere (inside JSON documents, in keyed rows) bring their own.
"""

import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.chronology.schema import EndSpec, SlotRef, TimePoint
from lore.core.time.status import TimeStatus

type SpecKind = Literal["time_point", "end"]

_RECORD_TYPE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")
_SLOT_NAME = re.compile(r"[a-z][a-z0-9_]*")
CORE = "core"


@dataclass(frozen=True)
class SlotDef:
    """One slot of a record type, or a family of slots.

    ``name`` is a slot name (``start``), a family (``exclusion:*`` matches ``exclusion:<any>``) or
    ``*`` (any slot not matched otherwise). The column names default to ``<name>_spec`` /
    ``<name>_t`` for fixed slots; families have no columns, so their provider needs its own loader
    and writer. ``status_column`` may be shared by several slots of the record.
    """

    name: str
    spec: SpecKind = "time_point"
    referenceable: bool = False
    spec_column: str | None = None
    resolved_column: str | None = None
    status_column: str | None = "time_status"

    @property
    def is_family(self) -> bool:
        return self.name == "*" or self.name.endswith(":*")

    @property
    def columns(self) -> tuple[str, str] | None:
        """``(spec column, resolved column)`` of a fixed slot; ``None`` for families."""
        if self.is_family:
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


@dataclass(frozen=True)
class SlotUpdate:
    """What a resolution writes: the moment to store (the caller passes the last good one back
    when resolution failed) and the status."""

    key: SlotKey
    t: int | None
    status: TimeStatus


type SlotLoader = Callable[[Session, Sequence[SlotKey]], dict[SlotKey, SlotValue]]
"""Load the given slots. Records that don't exist (purged) are absent from the result."""

type SlotWriter = Callable[[Session, Sequence[SlotUpdate]], None]
"""Store resolved values. Must write through the session (history records the changes) or call
``history.record_bulk``."""


@dataclass(frozen=True)
class SlotProvider:
    """A record type with time slots (``ModuleSpec.slot_providers`` for module records).

    ``load``/``write`` default to column access on ``model`` (fixed slots only); a model with
    ``deleted_at`` reports trashed rows. ``id_column`` is the record id the slot refs use.
    """

    record_type: str
    model: type
    slots: tuple[SlotDef, ...]
    id_column: str = "id"
    load: SlotLoader | None = None
    write: SlotWriter | None = None

    def slot(self, name: str) -> SlotDef | None:
        """The definition covering a slot name: an exact name wins over families, ``*`` last."""
        ordered = sorted(self.slots, key=lambda s: (s.name == "*", s.is_family))
        return next((definition for definition in ordered if definition.matches(name)), None)

    def load_slots(self, session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
        if self.load is not None:
            return self.load(session, keys)
        return _load_columns(self, session, keys)

    def write_slots(self, session: Session, updates: Sequence[SlotUpdate]) -> None:
        if self.write is not None:
            self.write(session, updates)
        else:
            _write_columns(self, session, updates)


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

    def _provider(self, record_type: str) -> SlotProvider:
        provider = self._by_type.get(record_type)
        if provider is None:
            raise SlotError("unknown_slot", f"unknown record type {record_type!r}")
        return provider


# Core record types register here as their tables arrive (events, timelines, facts, …).
CORE_SLOT_PROVIDERS: tuple[SlotProvider, ...] = ()


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
        if slot.is_family:
            if not custom:
                problems.append(f"{where}: slot family {name!r} needs a loader and a writer")
            continue
        wanted = [*(slot.columns or ()), slot.status_column]
        missing = [c for c in wanted if c is not None and c not in columns]
        if missing and not custom:
            problems += [f"{where}: slot {name!r} has no column {c!r}" for c in missing]
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


def _load_columns(
    provider: SlotProvider, session: Session, keys: Sequence[SlotKey]
) -> dict[SlotKey, SlotValue]:
    rows = _rows(provider, session, (key.id for key in keys))
    soft_deletes = hasattr(provider.model, "deleted_at")
    result: dict[SlotKey, SlotValue] = {}
    for key in keys:
        row = rows.get(key.id)
        if row is None:
            continue
        definition = _fixed(provider, key.slot)
        spec_column, resolved_column = definition.columns or ("", "")
        status = getattr(row, definition.status_column) if definition.status_column else None
        trashed = soft_deletes and row.deleted_at is not None
        result[key] = SlotValue(
            spec=getattr(row, spec_column),
            t=getattr(row, resolved_column),
            status=None if status is None else TimeStatus(status),
            trashed=trashed,
        )
    return result


def _write_columns(provider: SlotProvider, session: Session, updates: Sequence[SlotUpdate]) -> None:
    rows = _rows(provider, session, (update.key.id for update in updates))
    for update in updates:
        row = rows.get(update.key.id)
        if row is None:
            raise SlotError("unresolved_ref", f"{provider.record_type} {update.key.id} not found")
        definition = _fixed(provider, update.key.slot)
        _spec_column, resolved_column = definition.columns or ("", "")
        setattr(row, resolved_column, update.t)
        if definition.status_column:
            setattr(row, definition.status_column, update.status.value)


__all__ = [
    "CORE_SLOT_PROVIDERS",
    "SlotDef",
    "SlotError",
    "SlotKey",
    "SlotLoader",
    "SlotProvider",
    "SlotRegistry",
    "SlotUpdate",
    "SlotValue",
    "SlotWriter",
    "SpecKind",
    "validate_providers",
    "validate_registry",
]
