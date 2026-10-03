"""``mentions``: derived from rich-text bodies on every save (``data-model.md`` §6.4)."""

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base

CASCADE = "CASCADE"  # derived data follows the entities it was computed from


class Mention(Base):
    __tablename__ = "mentions"

    source_entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=CASCADE), primary_key=True
    )
    target_entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete=CASCADE), primary_key=True
    )
    # Counts by the visibility of the containing block.
    count_public: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    count_spoiler: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    count_private: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
