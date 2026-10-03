"""[core] entity sort names: entities.sort_name (case/accent-insensitive, natural numbers)

Revision ID: 99dba709e3e1
Revises: 4170d09b94db
Create Date: 2026-10-03 21:07:31.167141+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "99dba709e3e1"
down_revision: str | None = "4170d09b94db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sort_name(name: str) -> str:
    """A frozen copy of ``lore.core.entities.models.entity_sort_name`` as of this revision."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    folded = unicodedata.normalize("NFC", stripped).casefold()

    def pad(match: re.Match[str]) -> str:
        digits = match.group().lstrip("0")[:999] or "0"
        return f"{len(digits):03d}{digits}"

    return re.sub(r"[0-9]+", pad, folded)


def upgrade() -> None:
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sort_name", sa.String(), nullable=True))

    connection = op.get_bind()
    entities = sa.table("entities", sa.column("id", sa.String), sa.column("name", sa.String),
                        sa.column("sort_name", sa.String))  # fmt: skip
    rows = connection.execute(sa.select(entities.c.id, entities.c.name)).all()
    for entity_id, name in rows:
        connection.execute(
            entities.update().where(entities.c.id == entity_id).values(sort_name=_sort_name(name))
        )

    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.alter_column("sort_name", existing_type=sa.String(), nullable=False)
        batch_op.create_index("ix_entities_kind_sort_name", ["kind", "sort_name"], unique=False)
        batch_op.create_index(
            "ix_entities_parent_id_sort_name", ["parent_id", "sort_name"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.drop_index("ix_entities_parent_id_sort_name")
        batch_op.drop_index("ix_entities_kind_sort_name")
        batch_op.drop_column("sort_name")
