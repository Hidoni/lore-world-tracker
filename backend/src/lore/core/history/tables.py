"""Which tables history records, and which entities each row belongs to (``data-model.md`` §7).

Every authored table is recorded; derived ones (mentions, search, dependencies, findings,
proposals) are not. Core registers its tables here; a module lists each of its tables in
``ModuleSpec.history_tables`` (``derived=True`` for derived ones), which the registry checks.
Vault settings (``vault_meta``) aren't world data and aren't recorded (decided 2026-10-04).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Table

type Row = Mapping[str, Any]


def no_owner(_row: Row) -> list[str]:
    return []


def columns_owner(*columns: str) -> Callable[[Row], list[str]]:
    """Owners read from columns of the row (e.g. a link's ``source_id`` and ``target_id``)."""

    def owners(row: Row) -> list[str]:
        return [str(row[column]) for column in columns if row.get(column) is not None]

    return owners


@dataclass(frozen=True)
class HistoryTable:
    table: Table
    owners: Callable[[Row], list[str]] = no_owner
    derived: bool = False  # listed only to say "not recorded"

    @property
    def name(self) -> str:
        return self.table.name

    @classmethod
    def of(
        cls, model: type, owners: Callable[[Row], list[str]] = no_owner, *, derived: bool = False
    ) -> HistoryTable:
        """The entry of a mapped model's table: ``HistoryTable.of(MyRow, columns_owner("x"))``."""
        return cls(cast(Table, model.__table__), owners, derived)  # type: ignore[attr-defined]


def core_history_tables() -> tuple[HistoryTable, ...]:
    from lore.core.entities.models import Entity, EntityAlias, EntityTag, Tag  # noqa: PLC0415
    from lore.core.links.models import CustomLinkType, Link  # noqa: PLC0415

    return (
        HistoryTable.of(Entity, columns_owner("id")),
        HistoryTable.of(EntityAlias, columns_owner("entity_id")),
        HistoryTable.of(Tag),
        HistoryTable.of(EntityTag, columns_owner("entity_id")),
        HistoryTable.of(Link, columns_owner("source_id", "target_id")),
        HistoryTable.of(CustomLinkType),
    )
