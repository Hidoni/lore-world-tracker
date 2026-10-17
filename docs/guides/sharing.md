# Sharing your world with readers

Lore keeps everything you write in one private vault. To let other people read it, you **publish
a snapshot**: a copy of the vault from which everything private has been removed, and serve it
from a second, **read-only** instance. Readers can browse, search and use the timeline, but can't
change anything, and private content isn't hidden from them: it isn't there at all.

This guide uses the suggested docker compose setup (`docs/architecture/deployment.md` §3).

## 1. Decide what readers see

Every entity, link, field value, alias and block in a body has a **visibility**
(`docs/architecture/visibility-and-sharing.md` §1):

| Visibility | You see | Readers see |
|------------|---------|-------------|
| Public | it | it |
| Spoiler | it, marked as a spoiler | it, folded: they click to reveal it |
| Private | it, marked with a lock | nothing, not even that it exists |

New content gets the vault's default visibility (**Settings → General**). Set an entity's
visibility in its header, a field's with the selector next to it, a link's in its dialog, and a
block's by wrapping it in a spoiler or private block in the editor (`/spoiler`, `/private`). What
hides an entity hides what only it can see: a private dimension hides everything in it, a private
timeline hides its events.

## 2. Preview as a reader

Click the **eye** button in the top bar (**Preview as reader**). The app now shows exactly what a
reader gets: no editing, spoilers folded, private content gone (the server answers every read as
it would to a reader). Click it again to stop. Check the pages you care about before publishing.

## 3. Publish a snapshot

Create the two folders next to `docker-compose.yml` and start Lore (once):

```sh
mkdir -p data published
docker compose up -d
```

Then publish, either from **Settings → Publishing → Publish snapshot** (it shows when the vault
was last published) or from the command line:

```sh
docker compose exec lore lore vault list           # the vaults: id, folder, name
docker compose exec lore lore vault publish <vault id or folder>
```

The snapshot is written into `./published` (the author instance's `LORE_PUBLISH_DIR`). Before
anything is written, a leak check scans the copy; if it finds private data, nothing is published
and you get the reason. A snapshot never contains your history, consistency findings or pending
proposals.

## 4. Run the reader

```sh
docker compose --profile reader up -d reader
```

The reader serves `./published` read-only on port **8081**: open `http://<this host>:8081`. It
refuses every change (`403 read_only`), mounts the folder read-only, and never touches your
private vault in `./data`.

To put it on the internet, run it behind a reverse proxy with TLS. `deploy/Caddyfile` is a
ready-made Caddy example: it gets a certificate for your domain automatically and can ask readers
for a password (basic auth). Set `LORE_ALLOWED_HOSTS` on the `reader` service to your domain.

## 5. Update what readers see

Write as usual in your author instance, then publish again: the new snapshot replaces the old one
in `./published`. Restart the reader so it opens the new copy:

```sh
docker compose restart reader
```

## Static export (preview)

A published snapshot can also become a static site that any web host serves, with no Lore
server at all:

```sh
lore vault export-static <snapshot> --out site/ --data-dir ./published --spa frontend/dist
python -m http.server --directory site
```

It is still being built: the export has the landing page, lists and entity pages (with the time
cursor) and the timeline (any zoom, recurring events, branches, correspondences, worldlines);
module pages, maps, media and search say "Not in this export" until their data is exported too
(#376–#378).

## Backups and snapshots are different things

| | Backup | Published snapshot |
|---|---|---|
| Made by | **Settings → Backups**, `lore vault backup`, the schedule | **Settings → Publishing**, `lore vault publish` |
| Contains | **everything**: private entities, blocks, notes, history | only what readers may see |
| For | restoring your vault | sharing with readers |
| Opens in | the author instance (restored as a new vault) | a read-only instance only |

Never share a backup with someone who shouldn't see your private notes. Share a snapshot instead.
