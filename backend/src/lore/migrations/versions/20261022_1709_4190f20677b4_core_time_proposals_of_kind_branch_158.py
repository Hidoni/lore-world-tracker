"""[core:time] proposals of kind branch: re-parenting and merging branches (#158)

Revision ID: 4190f20677b4
Revises: 7728044b6bdc
Create Date: 2026-10-22 17:09:39.044338+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

from alembic import op

revision: str = "4190f20677b4"
down_revision: str | None = "7728044b6bdc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("proposals", schema=None) as batch_op:
        batch_op.drop_constraint("kind", type_="check")
        batch_op.create_check_constraint("kind", "kind IN ('calendar', 'recurrence', 'branch')")


def downgrade() -> None:
    op.execute("DELETE FROM proposals WHERE kind = 'branch'")
    with op.batch_alter_table("proposals", schema=None) as batch_op:
        batch_op.drop_constraint("kind", type_="check")
        batch_op.create_check_constraint("kind", "kind IN ('calendar', 'recurrence')")
