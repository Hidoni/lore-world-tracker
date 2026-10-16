"""The custom_fields module's tables (``docs/modules/custom_fields.md``, Tables).

- ``custom_fields_defs``: an author's field on a kind (``kind_key``), or on every kind that isn't
  a system kind (``"*"``). Keys are ``custom.<slug>``, unique per kind (a ``"*"`` key is unique
  everywhere). Values live where every field's do: ``entities.fields`` and, for temporal fields,
  ``entity_facts``.
"""

from typing import Any

from sqlalchemy import JSON, Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base, IdMixin, RevisionMixin, TimestampsMixin


class CustomFieldDef(IdMixin, RevisionMixin, TimestampsMixin, Base):
    __tablename__ = "custom_fields_defs"

    kind_key: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    multiple: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    temporal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    default_visibility: Mapped[str] = mapped_column(String, default="public")
    section: Mapped[str | None] = mapped_column(String)
    sort_key: Mapped[str] = mapped_column(String)
    help: Mapped[str] = mapped_column(String, default="", server_default="")
    searchable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("kind_key", "key", name="uq_custom_fields_defs_kind_key"),
        Index("ix_custom_fields_defs_key", "key"),
    )
