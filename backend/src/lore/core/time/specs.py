"""Storage of time slots (``time-model.md`` §5-§6, ``data-model.md`` §1, §10).

Each slot is persisted as ``<slot>_spec`` (a JSON time point or end spec), ``<slot>_t`` (the last
good resolved moment, ``SortableBigInt``) and a status column (``time_status``, shared per record
or per slot). The column types here validate specs with the ``lore.chronology.schema`` models when
they are written and hand them back as those (frozen) models when they are read::

    class Pin(Base):
        valid_from_spec: Mapped[TimePoint | None] = spec_column(TimePointSpec)
        valid_from_t: Mapped[int | None] = moment_column()
        time_status: Mapped[str | None] = status_column()

Time point and duration documents have no version field (v1). Additions must stay backward
compatible; a breaking change needs a data migration rewriting every ``_spec`` column and an
upgrader here (``data-model.md`` §10).
"""

from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import JSON, Dialect, String
from sqlalchemy.orm import MappedColumn, mapped_column
from sqlalchemy.types import TypeDecorator

from lore.chronology.schema import EndSpec, TimePoint
from lore.core.db.types import SortableBigInt

ABSOLUTE_CALENDAR_ID = "absolute"
"""The virtual calendar every dimension has (``time-model.md`` §3). It isn't stored, so nothing
depends on it."""

_TIME_POINT: TypeAdapter[TimePoint] = TypeAdapter(TimePoint)
_END_SPEC: TypeAdapter[EndSpec] = TypeAdapter(EndSpec)


class SpecError(ValueError):
    """A spec doesn't match its schema. ``errors`` are Pydantic's error dicts."""

    def __init__(self, what: str, errors: list[Any]) -> None:
        super().__init__(f"invalid {what}: {errors}")
        self.errors = errors


def parse_time_point(document: Any) -> TimePoint:
    """Validate a time point (a JSON document or a ``TimePoint``)."""
    if isinstance(document, TimePoint):
        return document
    try:
        return _TIME_POINT.validate_python(document)
    except ValidationError as exc:
        raise SpecError("time point", exc.errors(include_url=False)) from exc


def parse_end_spec(document: Any) -> EndSpec:
    """Validate an end spec (``time-model.md`` §5.5; a JSON document or an ``EndSpec`` model)."""
    try:
        return _END_SPEC.validate_python(document)
    except ValidationError as exc:
        raise SpecError("end spec", exc.errors(include_url=False)) from exc


def dump_spec(spec: TimePoint | EndSpec) -> dict[str, Any]:
    """The JSON document stored for a spec (defaults included, so stored documents are explicit)."""
    return spec.model_dump(mode="json", by_alias=True)


_PLAIN_ENDS: dict[str, EndSpec] = {}


class TimePointSpec(TypeDecorator[TimePoint]):
    """A ``<slot>_spec`` column holding a time point: JSON in SQLite, ``TimePoint`` in Python.

    Binding validates (a dict or a ``TimePoint``); invalid documents raise ``SpecError``."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else dump_spec(parse_time_point(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> TimePoint | None:
        return None if value is None else parse_time_point(value)


class EndSpecColumn(TypeDecorator[Any]):
    """An ``end_spec`` column: JSON in SQLite, an ``EndSpec`` model in Python."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else dump_spec(parse_end_spec(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if len(value) == 1 and isinstance(value, dict):
            # Ends without members (instant, unknown, end of time: half the events of a world)
            # are parsed once: the models are immutable.
            kind = value.get("kind")
            if isinstance(kind, str):
                known = _PLAIN_ENDS.get(kind)
                if known is None:
                    known = _PLAIN_ENDS[kind] = parse_end_spec(value)
                return known
        return parse_end_spec(value)


def spec_column(
    kind: type[TimePointSpec] | type[EndSpecColumn] = TimePointSpec, *, nullable: bool = True
) -> MappedColumn[Any]:
    """A ``<slot>_spec`` column."""
    return mapped_column(kind, nullable=nullable)


def moment_column(*, nullable: bool = True) -> MappedColumn[Any]:
    """A ``<slot>_t`` column: the last good resolved moment."""
    return mapped_column(SortableBigInt, nullable=nullable)


def status_column() -> MappedColumn[Any]:
    """A status column (``time_status``): a ``TimeStatus`` value, NULL until first resolved."""
    return mapped_column(String, nullable=True)
