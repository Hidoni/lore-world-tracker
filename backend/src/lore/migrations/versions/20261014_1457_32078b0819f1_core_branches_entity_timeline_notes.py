"""[core:time] per-timeline notes of entities (entity_timeline_notes, branches #115)

Revision ID: 32078b0819f1
Revises: ea5bdc2cf3f0
Create Date: 2026-10-14 14:57:33.275388+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "32078b0819f1"
down_revision: str | None = "ea5bdc2cf3f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_timeline_notes",
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("timeline_id", sa.String(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("body_schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_timeline_notes_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"],
            ["entities.id"],
            name=op.f("fk_entity_timeline_notes_timeline_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_timeline_notes")),
    )
    with op.batch_alter_table("entity_timeline_notes", schema=None) as batch_op:
        batch_op.create_index("ix_entity_timeline_notes_timeline_id", ["timeline_id"], unique=False)
        batch_op.create_index(
            "uq_entity_timeline_notes_entity_timeline", ["entity_id", "timeline_id"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("entity_timeline_notes", schema=None) as batch_op:
        batch_op.drop_index("uq_entity_timeline_notes_entity_timeline")
        batch_op.drop_index("ix_entity_timeline_notes_timeline_id")

    op.drop_table("entity_timeline_notes")
