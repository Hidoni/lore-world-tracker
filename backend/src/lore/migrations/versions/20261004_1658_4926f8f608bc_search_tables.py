"""[core] search: search_docs, the FTS5 tables search_fts and search_trigram, sync triggers

Revision ID: 4926f8f608bc
Revises: 3f8442eb85ef
Create Date: 2026-10-04 16:58:50.776527+00:00

The tables start empty: the first author-mode open of the vault fills them (the search index
version in ``vault_meta`` is missing, so ``lore.core.search`` reindexes; ``data-model.md`` §9).
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4926f8f608bc"
down_revision: str | None = "3f8442eb85ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
TRIGRAM_COLUMNS = ("name", "aliases_public")


def _text_column(name: str) -> sa.Column[str]:
    return sa.Column(name, sa.String(), server_default=sa.text("''"), nullable=False)


def _sync(table: str, columns: Sequence[str]) -> tuple[str, str, str]:
    """The (insert, delete, update) trigger bodies keeping an external-content FTS table in sync
    (the 'delete' command must get exactly the indexed values: the old row)."""
    names = ", ".join(columns)
    new = ", ".join(f"new.{c}" for c in columns)
    old = ", ".join(f"old.{c}" for c in columns)
    insert = f"INSERT INTO {table}(rowid, {names}) VALUES (new.rowid, {new});"
    delete = f"INSERT INTO {table}({table}, rowid, {names}) VALUES ('delete', old.rowid, {old});"
    return insert, delete, delete + " " + insert


def upgrade() -> None:
    op.create_table(
        "search_docs",
        sa.Column("rowid", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("doc_type", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("dimension_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        *(_text_column(name) for name in TEXT_COLUMNS),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_search_docs_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rowid", name=op.f("pk_search_docs")),
        sa.UniqueConstraint("doc_type", "doc_id", name=op.f("uq_search_docs_doc_type_doc_id")),
    )
    with op.batch_alter_table("search_docs", schema=None) as batch_op:
        batch_op.create_index("ix_search_docs_entity_id", ["entity_id"], unique=False)

    op.execute(
        f"CREATE VIRTUAL TABLE search_fts USING fts5({', '.join(TEXT_COLUMNS)}, "
        "content='search_docs', content_rowid='rowid', "
        "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')"
    )
    op.execute(
        f"CREATE VIRTUAL TABLE search_trigram USING fts5({', '.join(TRIGRAM_COLUMNS)}, "
        "content='search_docs', content_rowid='rowid', "
        "tokenize='trigram remove_diacritics 1')"
    )
    fts = _sync("search_fts", TEXT_COLUMNS)
    trigram = _sync("search_trigram", TRIGRAM_COLUMNS)
    op.execute(
        f"CREATE TRIGGER search_docs_ai AFTER INSERT ON search_docs BEGIN {fts[0]} {trigram[0]} END"
    )
    op.execute(
        f"CREATE TRIGGER search_docs_ad AFTER DELETE ON search_docs BEGIN {fts[1]} {trigram[1]} END"
    )
    op.execute(
        f"CREATE TRIGGER search_docs_au AFTER UPDATE OF {', '.join(TEXT_COLUMNS)} ON search_docs "
        f"BEGIN {fts[2]} {trigram[2]} END"
    )


def downgrade() -> None:
    for trigger in ("search_docs_au", "search_docs_ad", "search_docs_ai"):
        op.execute(f"DROP TRIGGER {trigger}")
    op.execute("DROP TABLE search_trigram")
    op.execute("DROP TABLE search_fts")
    with op.batch_alter_table("search_docs", schema=None) as batch_op:
        batch_op.drop_index("ix_search_docs_entity_id")
    op.drop_table("search_docs")
