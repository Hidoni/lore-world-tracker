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
  `lore.core.vaults.format` (`UPGRADERS[n]` turns version `n` into `n + 1`) and run before DB
  migrations when a vault is opened in author mode, which writes the upgraded `vault.json` back.
  Listing never writes. Unknown keys in `vault.json` are preserved on rewrite.
- **Creating** (`lore.core.vaults.VaultManager`): the folder is assembled as
  `vaults/.creating-<id>/` (`vault.json` + an empty WAL-mode `lore.db`) and renamed into place,
  so a crash never leaves a half-made vault. The slug is the name lowercased to ASCII `a-z0-9`
  with single hyphens, at most 40 characters (`vault` if nothing is left). UUIDv7 ids made within
  about a minute share their first 8 characters, so if `<slug>-<first 8>` exists, longer id
  prefixes are used (13, 18, 23 characters, then the whole id). `vaults/` and `trash/` are created
  on the first vault creation. **Renaming** changes only `name`, never the folder. **Deleting**
  moves the folder to `trash/<folder>-<UTC yyyymmddThhmmssZ>` (`-2`, `-3`, … on a clash).
- The vault registry scans `vaults/*/vault.json` at startup and on `GET /vaults`. Hidden entries
  (`.creating-*`) and plain files are ignored. **Folders that can't be used are listed, never
  hidden** (decided 2026-10-03), as `problems` with a code: `folder_name_invalid` (not
  `^[a-z0-9-]+$`), `manifest_invalid` (`vault.json` missing, unreadable or invalid),
  `format_newer_than_app`, or `duplicate_id` (a copied folder: several folders carry one id).
  Among duplicates, the folder whose name ends with an id prefix (the one `create` made) wins,
  then the first by folder name; only that one can be opened.
- **List order** (decided 2026-10-03): most recently modified first, ties by name
  (case-insensitive), then id. Until history exists, `modified_at` is the newest mtime of
  `vault.json`, `lore.db` and a non-empty `lore.db-wal` (an empty WAL only means a connection is
  open).
- In read-only mode, `LORE_EXPOSED_VAULTS` (ids or folder names) limits the registry, including
  `problems`. Author mode always sees every vault.
- One running author instance per data directory. A lock file (`vaults/<folder>/.lock`, JSON with
  `pid`, `hostname`, `acquired_at`) prevents two author processes from opening the same vault. It
  is taken when the author process first opens, renames or trashes the vault and released on
  shutdown (`409 vault_locked` otherwise, with the owner in `context`). A stale lock is taken over
  with a warning, which can only be decided **on the same host**: the PID is dead, or it is this
  process's own PID although this process doesn't hold the lock (a previous run with the same PID,
  e.g. PID 1 in a restarted container). Locks from other hosts and unreadable lock files are never
  taken over; `docker-compose.yml` pins `hostname: lore` so a recreated container counts as the
  same host.

## 2. SQLite configuration

Applied on every new connection (SQLAlchemy `connect` event):

```
PRAGMA journal_mode = WAL;        -- author mode only
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

- One SQLAlchemy `Engine` per opened vault (lazy, cached, disposed on shutdown), in
  `lore.core.db`. Connections use `file:` URIs: `mode=rw` in author mode (a missing database is
  never created by opening it), `mode=ro` in read-only mode. SQLAlchemy emits `BEGIN` itself
  (pysqlite's implicit transactions are off), so SAVEPOINTs and transactional DDL work.
- Vault-scoped routes take `VaultDep` (`get_vault(vault_id)`, opens the vault) and `SessionDep`
  (`lore.core.api.deps`): one session and one transaction per request, committed when the path
  operation returns and rolled back if it raises, with `expire_on_commit=False`. The dependency
  uses `scope="function"`, so the commit happens before the response is sent. Path operations are
  sync (FastAPI threadpool).
- Run uvicorn with **one worker**. SQLite serializes writes anyway, and per-vault caches (compiled
  calendars, registries) live in-process.
- `PRAGMA optimize` on vault close and daily. `lore vault check` runs `integrity_check`,
  `foreign_key_check` and derived-data consistency checks (search, mentions, dependencies,
  resolved times).
- **Read-only mode** opens `file:lore.db?mode=ro&uri=true`. Published snapshots
  (`journal_mode=DELETE`) are additionally opened with `immutable=1`.
- Requirements: SQLite with FTS5 (incl. trigram tokenizer, ≥ 3.34), JSON1, window functions and
  `contentless_delete` (≥ 3.43). The Python 3.14 builds used locally (3.50.x) and in the Docker
  image satisfy this. Startup (the app lifespan) checks it with probes on an in-memory database
  and refuses to run otherwise (`lore.core.db.ensure_sqlite_capabilities`).

## 3. Schema migrations (Alembic)

### 3.1 Setup

- Migrations live in `backend/src/lore/migrations/` (`env.py`, `script.py.mako`, `versions/`).
  Alembic is configured **programmatically** (`lore.core.db.migrate.Migrator`) per vault
  database. There is no `alembic.ini`. The migrator opens the connection, passes it to `env.py`
  (`config.attributes["connection"]`) and runs the whole upgrade in **one transaction it owns**,
  with `foreign_keys=OFF` (batch mode rebuilds tables) and a `PRAGMA foreign_key_check` before the
  commit: any violation rolls everything back. `env.py` refuses to run without a connection.
- The target metadata for autogenerate and `lore db check` is `lore.core.models.load_metadata()`.
  A new core model module must be imported there (module models: the module framework).
- `render_as_batch=True` (SQLite ALTER limitations).
- `include_object` hook: ignore FTS5 virtual tables and their shadow tables (`search_fts*`,
  `search_trigram*`) and SQLite internals. FTS tables are created/changed with explicit
  `op.execute(...)`.
- File template: `%%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s`
  (UTC).
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

Implementation (`VaultManager.open` / `.migrate`):

- **Revision comparison.** The history is linear, so a revision the app knows but that isn't head
  is behind it, and a revision it doesn't know was written by a newer app. An empty database
  (no `alembic_version`) is behind head.
- **New vaults** are migrated to head when they are created (before the folder is renamed into
  place), so they need no backup and open even with auto-migration off. The first migration
  seeds `vault_meta` with the vault's identity, which the manager passes to migrations as
  `context.config.attributes["vault"]` (`{vault_id, name, created_at}`; absent for scratch
  databases).
- **Schema state.** Every vault in `GET /vaults` / `GET /vaults/{v}` carries `schema_status
  {state, revision, head}`, read without opening the vault for writing. `state` is `current`,
  `needs_migration` (409 `vault_needs_migration` when opened with auto-migration off, or by a
  read-only server), `newer_than_app` (409 `vault_newer_than_app`), `migration_failed` or
  `database_unreadable`.
- **Failure.** A failed upgrade rolls back. The vault is then unusable for this process: opening
  or migrating it returns `500 vault_migration_failed` with the backup path in `context.backup`
  until the app restarts, with no second attempt and no second backup.
- **`POST /vaults/{v}/migrate`** (and `lore vault migrate <vault> [--to REV]`) upgrades to head (or
  to a later revision), returning `{vault, from_revision, to_revision, backup}`. A vault already
  at the target is left alone (`backup: null`). Targets behind the current revision are refused
  (`422`): downgrades are done by restoring a backup.
- `vault.json` is authoritative for the name. `vault_meta.name` is updated on rename (when the
  vault is open) and on every author-mode open.

### 3.4 CLI

```
lore vault list | create | status <vault> | migrate <vault> [--to REV] | check <vault>
lore vault reindex <vault> | backup <vault> | restore <zip> | publish <vault> --out DIR
lore db revision -m "msg" [--autogenerate]     # wraps alembic with the programmatic config (uses a scratch DB)
lore db check                                    # empty autogenerate diff + single head
```

`lore vault status|migrate` take a vault id or folder name. `make check` (and so CI) runs
`lore db check`.

### 3.5 Migration tests

1. **Upgrade from empty:** create an empty DB, upgrade to head, compare with ORM metadata.
2. **Golden fixture vaults:** `backend/tests/fixtures/vaults/v<app version>/` are real vault
   folders (small but rich: every feature available at that version, e.g. calendars of every
   feature, recurring events with materialized occurrences, branches, worldlines, facts, private
   content, media). They are generated with the sample world generator
   (`backend/scripts/make_sample_vault.py --size tiny`, see `testing.md` §2) **at each milestone
   release** and committed. Tests upgrade copies to head, then run API smoke tests and invariants
   (`lore vault check`). Old fixtures are never deleted.
3. **Per data migration:** unit tests with before/after rows, using the `migrations` fixture
   (`backend/tests/migration_harness.py`, below).

### 3.6 How to write a migration

1. Change or add the ORM models (new core model modules: import them in
   `lore.core.models.load_metadata`).
2. `cd backend && uv run lore db revision -m "add entity aliases" --autogenerate`. This upgrades a
   scratch database to head, diffs it against the models and writes
   `src/lore/migrations/versions/<yyyymmdd_hhmm>_<rev>_<slug>.py` from `script.py.mako`.
   Without `--autogenerate` you get an empty migration (data migrations).
3. Edit it:
   - Set the docstring owner: `"""[core] …`, `"""[core:time] …` or `"""[module: <id>] …`.
   - Review every operation (autogenerate misses renames, CHECK constraints and server
     defaults). Name constraints with `op.f(...)` so they match the naming convention in
     `lore.core.db.base`.
   - Never import `lore` code (models, services). Declare what you touch locally, copy the logic
     in, and use the frozen upgraders (§3.2 rule 3) only where they exist for this purpose.
   - FTS5 and other virtual tables: `op.execute("CREATE VIRTUAL TABLE …")`. Names starting with
     `search_fts`, `search_trigram` or `sqlite_` are ignored by autogenerate and the check.
   - Data migration pattern:

     ```python
     entities = sa.table("entities", sa.column("id", sa.String), sa.column("fields", sa.JSON))

     def upgrade() -> None:
         connection = op.get_bind()
         last_id = ""
         while True:  # batches, keyed on the primary key
             rows = connection.execute(
                 sa.select(entities.c.id, entities.c.fields)
                 .where(entities.c.id > last_id).order_by(entities.c.id).limit(500)
             ).all()
             if not rows:
                 break
             for row in rows:
                 connection.execute(
                     entities.update().where(entities.c.id == row.id)
                     .values(fields=_upgrade_fields(row.fields))  # a copy, defined in this file
                 )
             last_id = rows[-1].id
     ```

   - `downgrade()`: implement simple schema changes; data migrations may
     `raise NotImplementedError` (rollback = restore the pre-migration backup).
4. `uv run lore db check` must report no differences and exactly one head. If `main` gained a
   migration meanwhile, re-point your `down_revision` to the new head (`workflow.md` §9).
5. Test it with the `migrations` fixture:

   ```python
   def test_fields_are_upgraded(migrations: MigrationHarness) -> None:
       migrations.upgrade("<previous revision>")
       migrations.execute("INSERT INTO entities (id, fields, …) VALUES (?, ?, …)", (…))
       migrations.upgrade("<your revision>")
       assert migrations.rows("SELECT fields FROM entities") == […]
   ```

   `script_directory()` and `migration_source()` in the same file build throwaway histories, for
   framework tests that need extra, failing or forked migrations.

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
