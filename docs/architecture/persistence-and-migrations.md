# Persistence, migrations and backups

> Data safety is principle #1 (`docs/product/vision.md`). This document is the migration plan the
> brief asks for "from day one".

## 1. Data directory and vault format

```
$LORE_DATA_DIR/                      # default ./data (dev), /data (Docker)
  vaults/
    <folder>/                        # "<slug>-<first 8 chars of vault id>", fixed at creation
      vault.json                     # vault manifest (below)
      lore.db  lore.db-wal  lore.db-shm
      media/<aa>/<sha256>            # media module: content-addressed blobs
      media/thumbs/<sha256>_<w>.webp
      backups/auto/                  # pre-migration and scheduled backups
      backups/manual/                # user-requested backups
  trash/                             # deleted vaults are moved here (never rm -rf)
```

`vault.json`:

```json
{ "format_version": 1, "vault_id": "01a0…", "name": "Aetheria", "created_at": "…",
  "created_by_app_version": "0.1.0", "published": false }
```

- `format_version` covers the **folder layout** (not the DB schema). Upgraders live in
  `lore.core.vaults.format` and run before DB migrations when a vault is opened.
- The vault registry scans `vaults/*/vault.json` at startup and on `GET /vaults`.
- One running author instance per data directory. A lock file (`vaults/<folder>/.lock`
  containing PID + hostname) prevents two author processes from opening the same vault. A stale
  lock (dead PID on the same host) is taken over with a warning.

## 2. SQLite configuration

Applied on every new connection (SQLAlchemy `connect` event):

```
PRAGMA journal_mode = WAL;        -- author mode only
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

- One SQLAlchemy `Engine` per opened vault (lazy, cached). Sessions are per request with
  `expire_on_commit=False`. Path operations are sync (FastAPI threadpool).
- Run uvicorn with **one worker**. SQLite serializes writes anyway, and per-vault caches (compiled
  calendars, registries) live in-process.
- `PRAGMA optimize` on vault close and daily. `lore vault check` runs `integrity_check`,
  `foreign_key_check` and derived-data consistency checks (search, mentions, dependencies,
  resolved times).
- **Read-only mode** opens `file:lore.db?mode=ro&uri=true`. Published snapshots
  (`journal_mode=DELETE`) are additionally opened with `immutable=1`.
- Requirements: SQLite with FTS5 (incl. trigram tokenizer, ≥ 3.34), JSON1, window functions and
  `contentless_delete` (≥ 3.43). The Python 3.14 builds used locally (3.50.x) and in the Docker
  image satisfy this. Startup checks it and refuses to run otherwise.

## 3. Schema migrations (Alembic)

### 3.1 Setup

- Migrations live in `backend/src/lore/migrations/` (`env.py`, `versions/`). Alembic is configured
  **programmatically** (`lore.core.db.migrate`) per vault database. There is no global
  `alembic.ini` URL.
- `render_as_batch=True` (SQLite ALTER limitations).
- `include_object` hook: ignore FTS5 virtual tables and their shadow tables (`search_fts*`,
  `search_trigram*`) and SQLite internals. FTS tables are created/changed with explicit
  `op.execute(...)`.
- File template: `%%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s`.
- Migration docstrings start with the owner: `[core]`, `[core:time]` or `[module: <id>]`.

### 3.2 Rules

1. **Single linear history.** CI fails if `alembic heads` returns more than one head. When two
   PRs race, the later one rebases and re-points `down_revision`.
2. **Never edit a migration after it is merged.** Fix forward.
3. **Migrations are self-contained.** No imports of ORM models or services (they change over
   time). Use `sa.table()`/`sa.column()` or SQL. Data-migration logic is copied into the migration
   file. The exception is **versioned upgrader functions** explicitly designed to be frozen
   (`lore.chronology.schema.upgrade.v1_to_v2`, `lore.core.richtext.upgrade.v1_to_v2`, …). Those
   are never changed after release.
4. **Every schema change has a migration in the same PR as the model change.** CI runs an
   autogenerate comparison (`lore db check`) that must be empty.
5. **Data migrations** that rewrite JSON documents (calendar definitions, rich text, field values,
   specs) process rows in batches, are idempotent where possible, and have unit tests with
   before/after fixtures.
6. **Downgrades** are implemented for simple schema changes. Data migrations may raise
   `NotImplementedError` in `downgrade()`. The supported rollback is **restoring the automatic
   pre-migration backup**.
7. FTS/derived tables may be dropped and rebuilt by a migration (`reindex` step) instead of
   being migrated in place.

### 3.3 Upgrade on open

When a vault is opened (author mode, `LORE_AUTO_MIGRATE=true` by default):

1. Run vault-format upgraders (`vault.json`).
2. Read the DB revision:
   - **== head**: open.
   - **> head** (written by a newer app): refuse with `409 vault_newer_than_app`.
   - **< head**: write a pre-migration backup (`VACUUM INTO backups/auto/pre-migrate-<from>-to-<to>-<timestamp>.db`),
     then run `alembic upgrade head`. SQLite DDL is transactional, so a failed migration rolls
     back. If anything still fails, the vault is marked unusable for this process, the error and
     the backup path are reported, and the original file is left untouched.
3. If `LORE_AUTO_MIGRATE=false`, a vault needing migration opens in a "needs migration" state and
   the UI offers a button (`POST /vaults/{v}/migrate`).

Read-only mode **never** migrates. It refuses vaults that are not at head (publish snapshots
with the same app version that serves them).

### 3.4 CLI

```
lore vault list | create | status <vault> | migrate <vault> [--to REV] | check <vault>
lore vault reindex <vault> | backup <vault> | restore <zip> | publish <vault> --out DIR
lore db revision -m "msg" [--autogenerate]     # wraps alembic with the programmatic config (uses a scratch DB)
lore db check                                    # empty autogenerate diff + single head
```

### 3.5 Migration tests

1. **Upgrade from empty:** create an empty DB, upgrade to head, compare with ORM metadata.
2. **Golden fixture vaults:** `backend/tests/fixtures/vaults/<name>@<revision>/` are real vault
   folders (small but rich: calendars of every feature, recurring events with materialized
   occurrences, branches, worldlines, facts, private content, media). They are generated by
   `backend/scripts/make_fixture_vault.py` **at each milestone release** and committed. Tests
   upgrade copies to head, then run API smoke tests and invariants (`lore vault check`). Old
   fixtures are never deleted.
3. **Per data migration:** unit tests with before/after rows.

## 4. Versioned JSON documents

See `data-model.md` §10. Rules: every structured JSON document either carries a `schema_version`
or has its version tracked in a column. Python owns the upgraders. Stored documents are upgraded
by data migrations, so at runtime all documents are at the current version. API clients
(including the TS engine) only ever see current versions.

## 5. Backups and restore

- **Format:** a zip with `manifest.json` (`{format_version, app_version, schema_revision,
  vault: {...vault.json}, created_at, includes_media, sha256 per file}`), `lore.db` (made with
  `VACUUM INTO`, which gives a consistent compact copy without stopping writes), and `media/` when
  included.
- **Manual:** `POST /vaults/{v}/backups {include_media}` or `lore vault backup`. Listed and
  downloadable in settings. Backups contain private data, and the UI says so.
- **Automatic:** pre-migration (DB only), before destructive bulk operations (calendar proposal
  apply affecting > 100 records, module removal, restore), and **scheduled** (vault setting:
  every N hours while the app runs, keep the last K; default 24 h / 7).
- **Restore:** `POST /vaults/restore` (multipart) or `lore vault restore`. Validates the manifest
  and checksums, extracts into a **new** vault folder ("Aetheria (restored 2026-10-01)", new
  folder, same `vault_id` only if no vault with that id is present), runs format and DB upgrades,
  and registers the vault. It never overwrites an existing vault.
- **Published snapshot** (sanitized copy for read-only serving): see
  `visibility-and-sharing.md` §4.

## 6. Moving between machines

A vault folder (or a backup zip) is fully portable. Copy it into another installation's
`vaults/` directory, or restore the zip. An older app refuses newer vaults (§3.3). A newer app
upgrades older vaults automatically after taking a backup.
