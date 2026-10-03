"""[core] vault meta

Revision ID: b9f3e4412ccc
Revises:
Create Date: 2026-10-03 18:00:00+00:00
"""
# Self-contained: never import ORM models or services here (persistence-and-migrations.md §3.2).

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "b9f3e4412ccc"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_SETTINGS = {
    "modules": {},
    "consistency": {},
    "display": {},
    "defaults": {"visibility": "public"},
}


def upgrade() -> None:
    vault_meta = op.create_table(
        "vault_meta",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_vault_meta")),
    )
    # The vault manager passes the vault's identity (from vault.json); scratch databases used by
    # `lore db revision` / `lore db check` have none.
    vault = context.config.attributes.get("vault") or {}
    rows = [{"key": key, "value": vault[key]} for key in ("vault_id", "name", "created_at")
            if key in vault]  # fmt: skip
    rows.append({"key": "settings", "value": DEFAULT_SETTINGS})
    op.bulk_insert(vault_meta, rows)


def downgrade() -> None:
    op.drop_table("vault_meta")
