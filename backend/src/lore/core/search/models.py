"""``search_docs``: one row per searchable document (``data-model.md`` §9).

The row holds the document's filters **and** its text, split into public and restricted columns.
It is the external content table of the FTS5 tables ``search_fts`` and ``search_trigram``, which
SQL triggers keep in sync on every insert, update and delete (also when an entity's purge
cascades here). The FTS tables and the triggers are created by the migration with
``op.execute`` and are invisible to the ORM and to autogenerate.
"""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.core.db.base import Base, Visibility

CASCADE = "CASCADE"  # derived data follows the entities it was computed from
ENTITY_DOC = "entity"

# The text columns, in the order of the FTS5 table's columns (bm25 weights and snippet() column
# numbers follow this order).
TEXT_COLUMNS = (
    "name",
    "aliases_public",
    "aliases_restricted",
    "summary",
    "body_public",
    "body_restricted",
    "fields_public",
    "fields_restricted",
    "extra_public",
    "extra_restricted",
)
PUBLIC_COLUMNS = tuple(c for c in TEXT_COLUMNS if not c.endswith("_restricted"))


class SearchDoc(Base):
    __tablename__ = "search_docs"
    __table_args__ = (
        UniqueConstraint("doc_type", "doc_id"),
        Index("ix_search_docs_entity_id", "entity_id"),
    )

    # The FTS rowid; INTEGER PRIMARY KEY makes it the table's own rowid.
    rowid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String)  # "entity" or "<module>.<type>"
    doc_id: Mapped[str] = mapped_column(String)
    # The entity the document is (entity docs) or belongs to (module docs).
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=CASCADE))
    dimension_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # entity docs: the entity's kind; else doc_type
    visibility: Mapped[Visibility] = mapped_column(String)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    name: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    aliases_public: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    aliases_restricted: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    summary: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    body_public: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    body_restricted: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    fields_public: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    fields_restricted: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    extra_public: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    extra_restricted: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
