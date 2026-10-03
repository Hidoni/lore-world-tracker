"""[core] history: changesets, changes, change_entities

Revision ID: 3f8442eb85ef
Revises: 99dba709e3e1
Create Date: 2026-10-03 21:48:34.064508+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8442eb85ef"
down_revision: str | None = "99dba709e3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "changesets",
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("reverts_changeset_id", sa.String(), nullable=True),
        sa.Column("reverted_by_changeset_id", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changesets")),
    )
    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("changeset_id", sa.String(), nullable=False),
        sa.Column("table_name", sa.String(), nullable=False),
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("op", sa.String(), nullable=False),
        sa.Column("before", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after", sa.JSON(none_as_null=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["changeset_id"],
            ["changesets.id"],
            name=op.f("fk_changes_changeset_id_changesets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changes")),
    )
    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.create_index("ix_changes_changeset_id", ["changeset_id"], unique=False)

    op.create_table(
        "change_entities",
        sa.Column("change_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["changes.id"],
            name=op.f("fk_change_entities_change_id_changes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("change_id", "entity_id", name=op.f("pk_change_entities")),
    )
    with op.batch_alter_table("change_entities", schema=None) as batch_op:
        batch_op.create_index(
            "ix_change_entities_entity_id_change_id", ["entity_id", "change_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("change_entities", schema=None) as batch_op:
        batch_op.drop_index("ix_change_entities_entity_id_change_id")

    op.drop_table("change_entities")
    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.drop_index("ix_changes_changeset_id")

    op.drop_table("changes")
    op.drop_table("changesets")
