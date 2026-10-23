"""How a table travels in an interchange document beyond its rows (``interchange.md`` §5):
core declares its own (``CORE_TABLES``), a module lists its tables in
``ModuleSpec.interchange_tables``."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

type Row = Mapping[str, Any]  # a row's raw stored values


@dataclass(frozen=True)
class InterchangeTable:
    """``reuse_by_key``: a row whose unique key the target vault already has *is* that row (a
    tag by its name, a media item by its content), whatever else differs; without it such a
    row must be the same (ignoring timestamps and revision) or it is a conflict.

    ``file``/``store``: the table's rows have files (media): ``file(vault folder, row)`` is the
    file of an exported row (``None``: it has none); ``store(vault folder, row, file)`` puts an
    imported row's file into the target vault, raising ``ValueError`` when the file isn't the
    row's (a checksum mismatch)."""

    table: str
    reuse_by_key: bool = False
    file: Callable[[Path, Row], Path | None] | None = None
    store: Callable[[Path, Row, Path], None] | None = None


CORE_TABLES: tuple[InterchangeTable, ...] = (InterchangeTable("tags", reuse_by_key=True),)
