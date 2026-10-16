"""[module: custom_fields] custom kinds

Revision ID: 774333780b5d
Revises: 1ae94fbf5742
Create Date: 2026-10-16 11:00:01.755152+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "774333780b5d"
down_revision: str | None = "1ae94fbf5742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_fields_kinds",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("plural", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        sa.Column("allowed_parents", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("default_visibility", sa.String(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_custom_fields_kinds")),
    )


def downgrade() -> None:
    op.drop_table("custom_fields_kinds")
