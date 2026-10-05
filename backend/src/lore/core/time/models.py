"""``time_dependencies`` (``data-model.md`` §5.5, ``time-model.md`` §7.1): the edges propagation
walks. Derived from the specs, but kept in the same transaction as them (not recorded in history).
Dependents and targets are polymorphic (any registered record type), so there are no foreign keys.
"""

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base


class TimeDependency(Base):
    """``dependent`` slot → ``target``: a slot (``target_kind = 'slot'``), a calendar
    (``'calendar'``, ``target_calendar_id``) or a dimension's duration (``'dimension'``,
    ``target_id``)."""

    __tablename__ = "time_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dependent_type: Mapped[str] = mapped_column(String)
    dependent_id: Mapped[str] = mapped_column(String)
    dependent_slot: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str] = mapped_column(String)  # slot | calendar | dimension
    target_type: Mapped[str | None] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    target_slot: Mapped[str | None] = mapped_column(String)
    target_calendar_id: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_time_dependencies_dependent", "dependent_type", "dependent_id", "dependent_slot"),
        Index("ix_time_dependencies_target", "target_type", "target_id", "target_slot"),
        Index("ix_time_dependencies_target_calendar_id", "target_calendar_id"),
    )
