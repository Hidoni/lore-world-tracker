# Migrations

Alembic environment (`env.py`), template (`script.py.mako`) and `versions/` of the vault database:
one linear history, batch mode, configured programmatically by `lore.core.db.migrate` (there is no
`alembic.ini`). New migration: `uv run lore db revision -m "…" [--autogenerate]`; verify with
`uv run lore db check`. Rules and how-to: `docs/architecture/persistence-and-migrations.md` §3.
