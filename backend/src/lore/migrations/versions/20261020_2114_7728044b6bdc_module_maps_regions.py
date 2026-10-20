"""[module: maps] regions (#154)

Revision ID: 7728044b6bdc
Revises: 774333780b5d
Create Date: 2026-10-20 21:14:42.252598+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7728044b6bdc"
down_revision: str | None = "774333780b5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maps_regions",
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("target_entity_id", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("timeline_id", sa.String(), nullable=True),
        sa.Column("overrides_id", sa.String(), nullable=True),
        sa.Column("valid_from_spec", sa.JSON(), nullable=True),
        sa.Column("valid_from_t", sa.String(), nullable=True),
        sa.Column("valid_to_spec", sa.JSON(), nullable=True),
        sa.Column("valid_to_t", sa.String(), nullable=True),
        sa.Column("time_status", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), server_default=sa.text("'public'"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["map_id"],
            ["maps_maps.id"],
            name=op.f("fk_maps_regions_map_id_maps_maps"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["overrides_id"],
            ["maps_regions.id"],
            name=op.f("fk_maps_regions_overrides_id_maps_regions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            name=op.f("fk_maps_regions_target_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"],
            ["entities.id"],
            name=op.f("fk_maps_regions_timeline_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maps_regions")),
    )
    with op.batch_alter_table("maps_regions", schema=None) as batch_op:
        batch_op.create_index("ix_maps_regions_map_id", ["map_id"], unique=False)
        batch_op.create_index("ix_maps_regions_overrides_id", ["overrides_id"], unique=False)
        batch_op.create_index(
            "ix_maps_regions_target_entity_id", ["target_entity_id"], unique=False
        )
        batch_op.create_index(
            "ix_maps_regions_timeline_start", ["timeline_id", "valid_from_t"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("maps_regions", schema=None) as batch_op:
        batch_op.drop_index("ix_maps_regions_timeline_start")
        batch_op.drop_index("ix_maps_regions_target_entity_id")
        batch_op.drop_index("ix_maps_regions_overrides_id")
        batch_op.drop_index("ix_maps_regions_map_id")

    op.drop_table("maps_regions")
