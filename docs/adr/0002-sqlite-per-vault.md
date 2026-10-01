# ADR-0002: One SQLite database per vault

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The app is single-user and locally hosted (brief), supports multiple independent universes (D9),
must be easy to back up, move and share read-only, and needs full-text search and JSON handling.

## Decision

- Each **vault** is a folder containing `lore.db` (SQLite, WAL), `media/`, `backups/` and
  `vault.json`.
- SQLAlchemy 2.0 ORM (sync), one engine per opened vault, one uvicorn worker.
- SQLite features relied upon: FTS5 (incl. trigram), JSON1, window functions, `VACUUM INTO`,
  `contentless_delete` (≥ 3.43, the startup check enforces it).
- Alembic migrations, single linear history, applied per vault on open with a pre-migration
  backup (`persistence-and-migrations.md`).

## Consequences

- Backup = copy a folder (or `VACUUM INTO`). Sharing = a sanitized copy. Restore = add a folder.
- No server process to operate, and docker compose stays a single service.
- Write concurrency is limited (fine for a single user). Long write transactions (calendar
  proposals over many records) block other writes briefly.
- ALTER TABLE limitations require Alembic batch mode.
- Moving to Postgres later would need a different sortable encoding (or NUMERIC) and FTS
  replacement. This is not planned.

## Alternatives considered

- PostgreSQL: native NUMERIC ordering for big integers and better concurrency, but an extra
  service, harder per-universe isolation, and harder portability. Rejected for a local
  single-user app.
- Document store / files (Obsidian-like Markdown files): great portability but weak for strict
  relational time data, propagation and queries. Markdown export is a post-MVP module instead.
