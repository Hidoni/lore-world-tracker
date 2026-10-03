"""API schemas of history (``docs/architecture/api.md`` §2, Search, graph, consistency, history)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from lore.core.types import Affected


class ChangedEntity(BaseModel):
    """An entity a changeset touched. Purged entities keep the name and kind they last had."""

    id: str
    name: str | None
    kind: str | None
    exists: bool


class ChangesetSummary(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime = Field(description="Later than created_at when saves were merged in.")
    origin: str
    summary: str
    reverts_changeset_id: str | None
    reverted_by_changeset_id: str | None
    change_count: int
    entities: list[ChangedEntity]


class ChangesetPage(BaseModel):
    items: list[ChangesetSummary]
    next_cursor: str | None


class ChangeOut(BaseModel):
    """A row-level change. ``before``/``after`` are the full rows (JSON columns decoded)."""

    id: int
    table_name: str
    row_id: str
    op: Literal["insert", "update", "delete"]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    entity_ids: list[str]


class ChangesetDetail(ChangesetSummary):
    changes: list[ChangeOut]


class RevertResult(BaseModel):
    """The ``undo`` changeset the revert created."""

    changeset: ChangesetDetail
    affected: Affected
