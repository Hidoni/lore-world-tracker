"""[module: languages] create lexicon entries

Revision ID: 961ebb60c7f2
Revises: cef63815176d
Create Date: 2026-10-13 12:13:56.511374+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "961ebb60c7f2"
down_revision: str | None = "cef63815176d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISIBILITY_CHECK = "visibility IN ('public', 'spoiler', 'private')"


def upgrade() -> None:
    op.create_table(
        "languages_lexicon_entries",
        sa.Column("language_id", sa.String(), nullable=False),
        sa.Column("headword", sa.String(), nullable=False),
        sa.Column("romanization", sa.String(), nullable=True),
        sa.Column("pronunciation", sa.String(), nullable=True),
        sa.Column("part_of_speech", sa.String(), nullable=True),
        sa.Column("definitions", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("etymology", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("collation_key", sa.String(), nullable=False),
        sa.Column("timeline_id", sa.String(), nullable=True),
        sa.Column("valid_from_spec", sa.JSON(), nullable=True),
        sa.Column("valid_from_t", sa.String(), nullable=True),
        sa.Column("valid_to_spec", sa.JSON(), nullable=True),
        sa.Column("valid_to_t", sa.String(), nullable=True),
        sa.Column("time_status", sa.String(), nullable=True),
        sa.Column("sort_key", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), server_default=sa.text("'public'"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["language_id"],
            ["entities.id"],
            name=op.f("fk_languages_lexicon_entries_language_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"],
            ["entities.id"],
            name=op.f("fk_languages_lexicon_entries_timeline_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(VISIBILITY_CHECK, name=op.f("ck_languages_lexicon_entries_visibility")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_languages_lexicon_entries")),
    )
    with op.batch_alter_table("languages_lexicon_entries", schema=None) as batch_op:
        batch_op.create_index(
            "ix_languages_lexicon_entries_language_collation",
            ["language_id", "collation_key"],
            unique=False,
        )
        batch_op.create_index(
            "ix_languages_lexicon_entries_language_headword",
            ["language_id", "headword"],
            unique=False,
        )
        batch_op.create_index(
            "ix_languages_lexicon_entries_language_pos",
            ["language_id", "part_of_speech"],
            unique=False,
        )
        batch_op.create_index(
            "ix_languages_lexicon_entries_timeline_id", ["timeline_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("languages_lexicon_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_languages_lexicon_entries_timeline_id")
        batch_op.drop_index("ix_languages_lexicon_entries_language_pos")
        batch_op.drop_index("ix_languages_lexicon_entries_language_headword")
        batch_op.drop_index("ix_languages_lexicon_entries_language_collation")

    op.drop_table("languages_lexicon_entries")
