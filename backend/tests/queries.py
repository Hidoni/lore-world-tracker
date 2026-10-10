"""Counting the SQL statements a block runs, for tests that work is done in sets: the count
must not grow with the number of records."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


@contextmanager
def statements() -> Iterator[list[str]]:
    """The statements every engine runs inside the block (an ``executemany`` counts once)."""
    seen: list[str] = []

    def capture(_connection: Any, _cursor: Any, sql: str, *_rest: Any) -> None:
        seen.append(sql)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
