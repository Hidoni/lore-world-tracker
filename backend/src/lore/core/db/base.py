"""The declarative base and the column conventions every ORM model uses
(``docs/architecture/data-model.md`` §1).

Constraint names follow a fixed convention so that migrations can refer to them (SQLite batch
mode recreates tables and needs named constraints).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import CheckConstraint, ColumnElement, Integer, MetaData, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from lore.core.db.types import UTCDateTime, utc_now

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

type Visibility = Literal["public", "spoiler", "private"]
VISIBILITIES: tuple[Visibility, ...] = ("public", "spoiler", "private")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    """A primary key: a lowercase UUIDv7 string, generated server-side."""
    return str(uuid.uuid7())


class IdMixin:
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)


class TimestampsMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)


class SoftDeleteMixin:
    """``deleted_at`` set = in the trash (``data-model.md`` §1, soft delete)."""

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RevisionMixin:
    """Optimistic concurrency: ``revision`` starts at 1 and the ORM increments it on every UPDATE
    (``version_id_col``; a concurrent change makes the flush raise ``StaleDataError``). Services
    compare it with the revision a PATCH sends."""

    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.revision}


class VisibilityMixin:
    """``visibility TEXT NOT NULL DEFAULT 'public'`` with a CHECK (``data-model.md`` §1)."""

    @declared_attr
    def visibility(cls) -> Mapped[Visibility]:  # noqa: N805
        allowed = ", ".join(f"'{value}'" for value in VISIBILITIES)
        return mapped_column(
            String,
            CheckConstraint(f"visibility IN ({allowed})", name="visibility"),
            default="public",
            server_default=text("'public'"),
        )


def not_trashed[M: SoftDeleteMixin](model: type[M]) -> ColumnElement[bool]:
    """Filter for rows not in the trash: ``select(Entity).where(not_trashed(Entity))``."""
    return model.deleted_at.is_(None)
