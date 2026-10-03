"""[core] core schema v1: entities, aliases, tags, links, link types, mentions

Revision ID: 4170d09b94db
Revises: b9f3e4412ccc
Create Date: 2026-10-03 18:51:09.129082+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4170d09b94db"
down_revision: str | None = "b9f3e4412ccc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISIBILITY_CHECK = "visibility IN ('public', 'spoiler', 'private')"


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dimension_id", sa.String(), nullable=True),
        sa.Column("origin_timeline_id", sa.String(), nullable=True),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), server_default=sa.text("('')"), nullable=False),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("body_schema_version", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("field_visibility", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("cover_media_id", sa.String(), nullable=True),
        sa.Column("sort_key", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), server_default=sa.text("'public'"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dimension_id"],
            ["entities.id"],
            name=op.f("fk_entities_dimension_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_timeline_id"],
            ["entities.id"],
            name=op.f("fk_entities_origin_timeline_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["entities.id"],
            name=op.f("fk_entities_parent_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(VISIBILITY_CHECK, name=op.f("ck_entities_visibility")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
    )
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.create_index("ix_entities_deleted_at", ["deleted_at"], unique=False)
        batch_op.create_index(
            "ix_entities_dimension_id_kind", ["dimension_id", "kind"], unique=False
        )
        batch_op.create_index("ix_entities_kind", ["kind"], unique=False)
        batch_op.create_index(
            "ix_entities_origin_timeline_id", ["origin_timeline_id"], unique=False
        )
        batch_op.create_index("ix_entities_parent_id", ["parent_id"], unique=False)

    op.create_table(
        "link_type_defs",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("inverse_label", sa.String(), nullable=True),
        sa.Column("description", sa.String(), server_default=sa.text("('')"), nullable=False),
        sa.Column("source_kinds", sa.JSON(), server_default=sa.text("'\"*\"'"), nullable=False),
        sa.Column("target_kinds", sa.JSON(), server_default=sa.text("'\"*\"'"), nullable=False),
        sa.Column("symmetric", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("temporal", sa.String(), server_default=sa.text("'optional'"), nullable=False),
        sa.Column("unique_policy", sa.String(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("max_targets_per_source", sa.Integer(), nullable=True),
        sa.Column("max_sources_per_target", sa.Integer(), nullable=True),
        sa.Column("data_schema", sa.JSON(), nullable=True),
        sa.Column("graph", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_link_type_defs")),
    )
    op.create_table(
        "tags",
        sa.Column("name", sa.String(), nullable=False),
        # NFC-normalized, case-folded name (computed in Python): tag names are unique ignoring
        # case, for every alphabet (SQLite's lower() only folds ASCII).
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("name_key", name=op.f("uq_tags_name_key")),
    )
    op.create_table(
        "entity_aliases",
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("alias_kind", sa.String(), server_default=sa.text("'alias'"), nullable=False),
        sa.Column("sort_key", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), server_default=sa.text("'public'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_aliases_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(VISIBILITY_CHECK, name=op.f("ck_entity_aliases_visibility")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_aliases")),
    )
    with op.batch_alter_table("entity_aliases", schema=None) as batch_op:
        batch_op.create_index("ix_entity_aliases_alias", ["alias"], unique=False)
        batch_op.create_index("ix_entity_aliases_entity_id", ["entity_id"], unique=False)

    op.create_table(
        "entity_tags",
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("tag_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_tags_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_entity_tags_tag_id_tags"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("entity_id", "tag_id", name=op.f("pk_entity_tags")),
    )
    op.create_table(
        "links",
        sa.Column("link_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("timeline_id", sa.String(), nullable=True),
        sa.Column("overrides_id", sa.String(), nullable=True),
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
            ["overrides_id"],
            ["links.id"],
            name=op.f("fk_links_overrides_id_links"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["entities.id"],
            name=op.f("fk_links_source_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["entities.id"],
            name=op.f("fk_links_target_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id"],
            ["entities.id"],
            name=op.f("fk_links_timeline_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(VISIBILITY_CHECK, name=op.f("ck_links_visibility")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_links")),
    )
    with op.batch_alter_table("links", schema=None) as batch_op:
        batch_op.create_index("ix_links_link_type", ["link_type"], unique=False)
        batch_op.create_index(
            "ix_links_source_id_link_type", ["source_id", "link_type"], unique=False
        )
        batch_op.create_index(
            "ix_links_target_id_link_type", ["target_id", "link_type"], unique=False
        )
        batch_op.create_index(
            "ix_links_timeline_id_valid_from_t", ["timeline_id", "valid_from_t"], unique=False
        )

    op.create_table(
        "mentions",
        sa.Column("source_entity_id", sa.String(), nullable=False),
        sa.Column("target_entity_id", sa.String(), nullable=False),
        sa.Column("count_public", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("count_spoiler", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("count_private", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["entities.id"],
            name=op.f("fk_mentions_source_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            name=op.f("fk_mentions_target_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_entity_id", "target_entity_id", name=op.f("pk_mentions")),
    )


def downgrade() -> None:
    op.drop_table("mentions")
    with op.batch_alter_table("links", schema=None) as batch_op:
        batch_op.drop_index("ix_links_timeline_id_valid_from_t")
        batch_op.drop_index("ix_links_target_id_link_type")
        batch_op.drop_index("ix_links_source_id_link_type")
        batch_op.drop_index("ix_links_link_type")

    op.drop_table("links")
    op.drop_table("entity_tags")
    with op.batch_alter_table("entity_aliases", schema=None) as batch_op:
        batch_op.drop_index("ix_entity_aliases_entity_id")
        batch_op.drop_index("ix_entity_aliases_alias")

    op.drop_table("entity_aliases")
    op.drop_table("tags")
    op.drop_table("link_type_defs")
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.drop_index("ix_entities_parent_id")
        batch_op.drop_index("ix_entities_origin_timeline_id")
        batch_op.drop_index("ix_entities_kind")
        batch_op.drop_index("ix_entities_dimension_id_kind")
        batch_op.drop_index("ix_entities_deleted_at")

    op.drop_table("entities")
