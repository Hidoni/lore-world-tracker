"""Column types shared by every table (``docs/architecture/data-model.md`` §1)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Dialect, String
from sqlalchemy.types import TypeDecorator

from lore.chronology.numbers import NumberError, from_sortable_key, sortable_key


class SortableBigInt(TypeDecorator[int]):
    """A non-negative arbitrary-precision integer (in-world moments, ``*_t`` columns) stored as a
    sortable TEXT key (``time-model.md`` §2.3): byte-wise order equals numeric order.

    Bound parameters are encoded too, so ``column < 10**500`` and ``ORDER BY column`` work in SQL.
    Negative values, non-integers and more than 1000 digits are rejected. The column keeps
    SQLite's default ``BINARY`` collation: never ``CAST`` it or give it another collation.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"SortableBigInt takes an int, not {type(value).__name__}")
        try:
            return sortable_key(value)
        except NumberError as exc:
            raise ValueError(f"cannot store {str(value)[:40]} as a sortable key: {exc}") from exc

    def process_literal_param(self, value: Any, dialect: Dialect) -> str:
        key = self.process_bind_param(value, dialect)
        return "NULL" if key is None else f"'{key}'"

    def process_result_value(self, value: Any, dialect: Dialect) -> int | None:
        return None if value is None else from_sortable_key(value)


class UTCDateTime(TypeDecorator[datetime]):
    """A real-world timestamp (``created_at`` …, never in-world time), timezone-aware UTC.

    Stored as fixed-width ISO-8601 text (``2026-10-03T18:00:00.000000+00:00``), so it sorts as text
    and round-trips with its timezone. Naive datetimes are rejected.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"UTCDateTime takes a datetime, not {type(value).__name__}")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime needs a timezone-aware datetime")
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)


def utc_now() -> datetime:
    return datetime.now(UTC)
