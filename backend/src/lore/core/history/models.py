"""``changesets``, ``changes``, ``change_entities`` (``data-model.md`` §7)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base, IdMixin
from lore.core.db.types import UTCDateTime, utc_now

CASCADE = "CASCADE"  # history rows belong to their changeset


class Changeset(IdMixin, Base):
    """One write operation. ``updated_at`` moves when later saves are merged into it."""

    __tablename__ = "changesets"

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    # ui | api | cli | import | migration | system | undo
    origin: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String)
    request_id: Mapped[str | None] = mapped_column(String)
    reverts_changeset_id: Mapped[str | None] = mapped_column(String)
    reverted_by_changeset_id: Mapped[str | None] = mapped_column(String)


class Change(Base):
    """A row-level change. ``before``/``after`` are full rows as stored (raw SQLite values)."""

    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changeset_id: Mapped[str] = mapped_column(ForeignKey("changesets.id", ondelete=CASCADE))
    table_name: Mapped[str] = mapped_column(String)
    row_id: Mapped[str] = mapped_column(String)  # the primary key (JSON array if composite)
    op: Mapped[str] = mapped_column(String)  # insert | update | delete
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))

    __table_args__ = (Index("ix_changes_changeset_id", "changeset_id"),)


class ChangeEntity(Base):
    """The entities a change belongs to (a link change belongs to both ends)."""

    __tablename__ = "change_entities"

    change_id: Mapped[int] = mapped_column(
        ForeignKey("changes.id", ondelete=CASCADE), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)

    __table_args__ = (Index("ix_change_entities_entity_id_change_id", "entity_id", "change_id"),)
