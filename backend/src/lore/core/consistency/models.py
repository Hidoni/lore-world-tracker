"""Consistency tables (``consistency.md`` §1, §3): ``consistency_findings`` (derived: not
recorded in history, rewritten by checks and scans), their subjects
(``consistency_finding_entities``, for filters and badges) and ``consistency_suppressions``
(authored: a user decision, recorded in history)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base, IdMixin
from lore.core.db.types import UTCDateTime, utc_now


class Finding(IdMixin, Base):
    """One open violation of a rule, identified by its ``fingerprint`` (``consistency.md`` §1)."""

    __tablename__ = "consistency_findings"

    fingerprint: Mapped[str] = mapped_column(String, unique=True)
    rule_id: Mapped[str] = mapped_column(String)
    certainty: Mapped[str] = mapped_column(String)  # definite | possible
    message: Mapped[str] = mapped_column(String)
    timeline_id: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    __table_args__ = (
        CheckConstraint("certainty IN ('definite', 'possible')", name="certainty"),
        Index("ix_consistency_findings_rule_id", "rule_id"),
    )


class FindingEntity(Base):
    """A finding's subject entities (no foreign key to ``entities``: findings of a purged entity
    are deleted by the engine)."""

    __tablename__ = "consistency_finding_entities"

    finding_id: Mapped[str] = mapped_column(
        ForeignKey("consistency_findings.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(server_default=text("0"))

    __table_args__ = (Index("ix_consistency_finding_entities_entity_id", "entity_id"),)


class Suppression(Base):
    """A finding marked intentional (``consistency.md`` §3): kept when the finding goes away, so
    it stays suppressed if found again."""

    __tablename__ = "consistency_suppressions"

    fingerprint: Mapped[str] = mapped_column(String, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
