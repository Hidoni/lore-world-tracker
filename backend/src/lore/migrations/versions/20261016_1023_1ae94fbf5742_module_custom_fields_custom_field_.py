"""[module: custom_fields] custom field definitions

Revision ID: 1ae94fbf5742
Revises: d79456dede44
Create Date: 2026-10-16 10:23:11.876189+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1ae94fbf5742"
down_revision: str | None = "d79456dede44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_fields_defs",
        sa.Column("kind_key", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("multiple", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("required", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("temporal", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("default_visibility", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("sort_key", sa.String(), nullable=False),
        sa.Column("help", sa.String(), server_default="", nullable=False),
        sa.Column("searchable", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_fields_defs")),
        sa.UniqueConstraint("kind_key", "key", name="uq_custom_fields_defs_kind_key"),
    )
    with op.batch_alter_table("custom_fields_defs", schema=None) as batch_op:
        batch_op.create_index("ix_custom_fields_defs_key", ["key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("custom_fields_defs", schema=None) as batch_op:
        batch_op.drop_index("ix_custom_fields_defs_key")

    op.drop_table("custom_fields_defs")
