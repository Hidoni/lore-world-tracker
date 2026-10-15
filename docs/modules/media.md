# Module: `media` — Images and attachments

> Upload images and files into a vault and use them in pages (portraits, banners, glyph sheets,
> maps). Covers R-MED-1.

## Summary

| | |
|---|---|
| Module id | `media` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M10 |

## Kinds

None. Media items are assets, not entities.

## Tables

| Table | Columns |
|-------|---------|
| `media_items` | `id`, `sha256` (UNIQUE), `filename` (original, display only), `mime`, `size`, `width NULL`, `height NULL`, `alt`, `caption`, `created_at`, `deleted_at` |
| `media_refs` (derived) | `media_id`, `entity_id`, `context` (`body`, `field:<key>`, `cover`, `gallery`, `map`, `note`), PK all three, `ON DELETE CASCADE` |
| `media_gallery` | `id`, `entity_id`, `media_id`, `caption`, `sort_key`, `visibility`, `revision`, timestamps, `deleted_at` |

Files: `media/<sha256[0:2]>/<sha256>` inside the vault folder. Thumbnails:
`media/thumbs/<sha256>_<width>.webp` (160, 480, 1280), generated lazily with Pillow and
regenerable.

## API

- `POST /m/media/items` (multipart: file, alt, caption): validates type/size per `security.md` §3
  and dedupes by hash (uploading the same bytes returns the existing item).
- `GET /m/media/items?unused=&entity=&q=&cursor=`: library listing.
- `GET /m/media/items/{id}`, `PATCH /m/media/items/{id}` (alt, caption), `DELETE` (trash).
- `GET /m/media/items/{id}/file?size=160|480|1280|original`: streams the file. `ETag` = sha256,
  `Cache-Control: private, max-age=31536000, immutable`, plus the safe headers from `security.md`.
- Gallery: `GET|POST /m/media/entities/{id}/gallery`, `PATCH|DELETE /m/media/gallery/{item_id}`.
- Cover: set via the generic entity PATCH (`cover_media_id`). The module validates the id.

## Integration points

- **Rich text:** TipTap `image` node (`{mediaId, alt, caption, width}`). Paste/drop uploads. The
  backend `richtext_nodes` handler extracts refs and filters for readers.
- **Field type `media`:** registered by this module (usable by custom fields).
- **Entity header:** cover/portrait image (frontend extension `entityHeaderMedia`).
- **Maps** module uses `media.api.reference(media_id, entity_id, "map")`.
- `media_refs` is rebuilt whenever an owning context is saved.
- **GC:** media without refs and not in any gallery for 30 days are moved to trash by a daily
  job, and purged from trash after another 30 days (configurable). Never purge without trash.

## UI

- Media library page (grid, filters: unused / by entity / type, bulk delete, replace file).
- Gallery panel on entity pages (drag to reorder, captions, visibility per item).
- Cover image in the entity header (upload, pick from library, remove).
- Image picker dialog reused by the editor and fields.

## Visibility, backup, publish

- An item is reader-visible iff at least one visible context references it
  (`visibility-and-sharing.md` §2). The file endpoint enforces this in reader mode.
- Backups include `media/` when requested. Publish copies only reader-visible items (and
  regenerates thumbnails lazily on the reader side, which then needs a writable cache dir).
  Published snapshots include pre-generated thumbnails.

## Consistency rules

None (missing files are reported by `lore vault check`).

## Disabling / removal notes

Disabling hides uploads, galleries and covers, and image nodes render as alt text. Files are kept.
Removal requires an export of `media/`.

## Implementation notes (#126)

- **Storage** (`lore.modules.media.storage`): files are written to a temporary file and renamed
  into place. The type comes from the bytes; the uploaded name only decides between plain text and
  Markdown. Thumbnails are made on first request (the first frame of an animation); a vault folder
  that can't be written (read-only server) gets them made in memory each time.
- **Items** carry `revision` (PATCH) and `unused_since` (the collection's mark) besides the
  columns above, and are recorded in history (trash and edits can be undone). `POST
  /m/media/items/{id}/restore` takes one out of the trash; uploading the same bytes does too.
- **References** (`lore.modules.media.refs`): a derived hook (`ModuleSpec.derived_hooks`)
  rebuilds `body`, `field:<key>`, `cover` and `gallery` for every entity a changeset touches
  (writes and undo alike), from the stored body, `rich_text` and `media` field values (and their
  facts), `cover_media_id` and live gallery items. `media_refs.visibility` is the least
  restrictive level the item has in that context: an image in a private `visibilityBlock` of a
  public body is private there; a field's level is its default or the entity's override (a fact's,
  the stricter of the two). Other modules write their own contexts (`map`, `note`) with
  `lore.modules.media.api.reference` / `unreference`. Ids of items that don't exist make no
  reference; an unknown cover is refused (`422`, path `cover_media_id`).
- **Readers** see an item iff a ref that isn't private belongs to an entity they see
  (`REF_VISIBILITY`), and the item isn't in the trash; gallery items follow their own
  visibility and their entity's. The `image` node is kept for readers (it is what makes its item
  visible to them).
- **GC** (`lore.modules.media.gc`, a daily `maintenance_tasks` entry): marks unused items
  (`unused_since`, not history), trashes those unused for `trash_after_days` (one changeset that
  can be undone) and purges trashed, still unused items after `purge_after_days` (rows and files;
  not undoable). Both default to 30 and come from the module's stored settings.
- **`lore vault check`** (`derived_checks`): stale references (`media`, `stale_refs`) and items
  whose file is missing (`missing_file`); `lore vault reindex` rebuilds the references.
- **Backups** include the `media/` folder (core, `include_media`). **Publish**: `publish_media`
  copies the reader-visible items and their thumbnails into the published vault folder; #140
  calls it when snapshots arrive.
- The `media` field type holds an item id (a list for `multiple` fields); custom fields (M11) can
  use it.

## Future ideas

Audio (pronunciations for lexicon entries), PDF previews, image annotations, SVG sanitization for
inline rendering, deep-zoom tiling (shared with maps).
