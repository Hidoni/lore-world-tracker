# Backups, restore and upgrades

Your world lives in a **vault**: a folder under the data directory (`./data` in the suggested
docker compose setup and in `make dev`) holding the database, your media files and the vault's
backups. This guide covers backing a vault up, restoring it, upgrading the app without risk, and
the maintenance commands.

The commands below use the docker compose setup (`docs/architecture/deployment.md` §3). In a
development checkout, run them from `backend/` with the same data directory as `make dev`:
`LORE_DATA_DIR=../data uv run lore vault …`. Every `lore vault` command takes a vault id or
folder name; `lore vault list` prints both.

## 1. What a backup is

A backup is one zip file containing:

- the vault's database (your entities, links, dates, history, settings: everything you wrote),
- the vault's `media/` folder (images and attachments), unless you leave it out,
- a manifest with the app version, the database version and a checksum of every file.

Backups contain **everything**, private entities and notes included. Share one only with
someone who may see all of it; to share with readers, publish a snapshot instead (`sharing.md`).

Backups are written inside the vault folder: `vaults/<folder>/backups/manual/` for the ones you
ask for, `vaults/<folder>/backups/auto/` for the others. That protects you from mistakes in the
app, not from losing the disk: copy backups (or the whole data directory) somewhere else from
time to time. **Download** in Settings does that for one backup.

## 2. Back up now

In the app: **Settings → Backups**. **Back up now** writes a backup; untick **Include media
files** for a smaller one with the database only. The list below shows every backup, newest
first, with its kind (**Manual**, **Scheduled**, or **Before a change**), size and a
**Download** button.

From the command line:

```sh
docker compose exec lore lore vault list
docker compose stop lore
docker compose run --rm lore lore vault backup <vault>              # with media
docker compose run --rm lore lore vault backup <vault> --no-media   # database only
docker compose start lore
```

The command needs the vault to itself: while the server has the vault open, it fails with
"The vault is open in another process". Stop the server first, as above, or use the app.

## 3. Scheduled backups

Each vault backs itself up on a schedule, set under **Settings → Backups → Schedule**:

- **Every (hours)**: how often (default 24; `0` turns scheduled backups off).
- **Keep the last**: how many scheduled backups to keep (default 7). Older scheduled backups are
  deleted; manual and before-a-change backups are never deleted automatically.
- **Include media**: whether scheduled backups include media files (default on).

Click **Save schedule**. Scheduled backups are made by the running server, about every ten
minutes it checks which vaults are due, and only for vaults it has opened since it started. If
the app isn't running, or you haven't opened a vault since restarting it, no scheduled backup is
made: back up by hand before anything risky.

## 4. Automatic backups before risky changes

Lore also backs a vault up, without media, before:

- **upgrading its database** to a new app version (§6),
- applying a calendar change that affects more than 100 records (`calendars.md` §6).

These appear in the list as **Before a change**, except the pre-upgrade copy, which is a plain
database file (`backups/auto/pre-migrate-….db`) rather than a zip.

## 5. Restore

Restoring never overwrites anything: it always creates a **new** vault, named like
"Aetheria (restored 2026-10-17)", next to the existing ones. Open it, check it, then move the
old vault to the trash from the vault list if you no longer want it.

In the app: **Settings → Backups → Restore**, choose the **Backup zip** (a downloaded one, or
one from another machine) and click **Restore into a new vault**. When it is done, the page links
to the new vault.

From the command line, the zip must be inside the data directory so the container can see it:

```sh
cp ~/Downloads/backup.zip data/
docker compose exec lore lore vault restore /data/backup.zip
```

Restore checks the zip first (manifest, checksums, file names and sizes). A damaged or foreign
file is refused and leaves nothing behind. A backup made by an older version is upgraded as it
is restored; one made by a **newer** version is refused: upgrade the app first.

To move a world to another machine, restore a backup there, or copy the vault folder into the
other installation's `data/vaults/` while both apps are stopped.

## 6. Upgrade the app

Pull the new version and rebuild:

```sh
docker compose exec lore lore vault list     # optional: note your vaults
git pull
docker compose build
docker compose up -d
```

(In development: `git pull`, `make setup`, then `make dev` again.)

Each vault is upgraded the first time you open it with the new version. Lore saves a copy of its
database first (§4) and upgrades in one transaction: if the upgrade fails, the vault is left as
it was and the error names the backup. Every release is tested by upgrading sample vaults made
by each earlier release (`backend/tests/fixtures/vaults/`), so skipping versions is fine.

For a safe upgrade:

1. **Back up each vault** you care about (§2) and download the zips. A zip made by the old
   version restores in the old version, which is your way back.
2. Upgrade as above.
3. Open each vault and look around. The vault list shows **Server version** and marks a vault
   that **Needs migration** or is **Newer than this app**.

There is no downgrade. An older app refuses a vault a newer one has upgraded; to go back,
reinstall the old version and restore the backup you made before upgrading.

If you'd rather upgrade by hand, set `LORE_AUTO_MIGRATE=false` on the `lore` service. Vaults
that need it then show **Needs migration** and won't open until you run:

```sh
docker compose exec lore lore vault status <vault>    # schema revision vs. this app's
docker compose exec lore lore vault migrate <vault>   # backs up, then upgrades
```

## 7. Check and maintain a vault

```sh
docker compose exec lore lore vault check <vault>
```

`check` tests the vault's health: the database version, SQLite's integrity and foreign keys, and
the data Lore derives from your content (the search index, mentions, resolved dates). It works
on a temporary copy, never changes the vault, and can run while the app is running (it needs as
much free temporary space as the database takes). It exits with status 1 and lists the problems
if it finds any; `--json` prints a report for scripts.

The other commands open the vault, so stop the server first:

```sh
docker compose stop lore
docker compose run --rm lore lore vault reindex <vault>
docker compose run --rm lore lore vault compact-history <vault> --older-than 365
docker compose run --rm lore lore vault optimize <vault> --vacuum
docker compose start lore
```

- `reindex` rebuilds the search index, mentions and resolved dates from your content. Run it
  when `check` reports problems with them, or when search misses things it should find.
- `compact-history --older-than N` replaces the history older than N days with one entry per
  entity (what changed over that period), to keep the database from growing with every edit.
  Compacted history can't be undone or looked at edit by edit any more, so make a backup first;
  `--dry-run` only says how much it would compact. Run `optimize --vacuum` afterwards to shrink
  the file.
- `optimize` refreshes SQLite's statistics (the app also does this daily). With `--vacuum` it
  also rewrites the database file to reclaim space after large deletions; that needs as much
  free disk space as the file takes.
