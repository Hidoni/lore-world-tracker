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

Accepted files (by their bytes): images (png, jpeg, webp, gif, avif, svg), documents (pdf, text,
Markdown) and fonts (woff2, woff, ttf, otf; writing systems' fonts, `docs/modules/scripts.md`).

Files: `media/<sha256[0:2]>/<sha256>` inside the vault folder. Thumbnails:
`media/thumbs/<sha256>_<width>.webp` (160, 480, 1280), generated lazily with libvips and
regenerable. Tiles of large images (#162): `media/tiles/<sha256>/<level>/<x>_<y>.webp`, regenerable.

## API

- `POST /m/media/items` (multipart: file, alt, caption): validates type/size per `security.md` §3
  and dedupes by hash (uploading the same bytes returns the existing item).
- `GET /m/media/items?unused=&entity=&q=&cursor=`: library listing.
- `GET /m/media/items/{id}`, `PATCH /m/media/items/{id}` (alt, caption), `DELETE` (trash).
- `PUT /m/media/items/{id}/file` (multipart: file, revision): replaces the file, keeping the id
  (the library's "replace file").
- `GET /m/media/items/{id}/file?size=160|480|1280|original`: streams the file. `ETag` = sha256,
  `Cache-Control: private, max-age=31536000, immutable`, plus the safe headers from `security.md`.
- `GET /m/media/items/{id}/tiles/{level}/{x}/{y}` (#162): a deep-zoom tile of a raster image
  (WebP), cached and visible like the file.
- Gallery: `GET|POST /m/media/entities/{id}/gallery`, `PATCH|DELETE /m/media/gallery/{item_id}`.
- Cover: set via the generic entity PATCH (`cover_media_id`). The module validates the id.

## Integration points

- **Rich text:** TipTap `image` node (`{mediaId, alt, caption, width}`). Paste/drop uploads. The
  backend `richtext_nodes` handler extracts refs and filters for readers.
- **Field type `media`:** registered by this module (usable by custom fields).
- **Entity header:** cover/portrait image (frontend extension `entityHeaderMedia`).
- **Maps** module uses `media.api.reference(media_id, entity_id, "map")`.
- `media_refs` is rebuilt whenever an owning context is saved.
- **Markdown export** (`markdown_contributors`, `lore.modules.media.markdown`): the files of the
  items the export's audience may see are copied to `_media/<uploaded name>`; images, `media`
  fields and covers embed them (`![[_media/<file>]]`), an image of an item not exported shows its
  alt text (`markdown-export.md` §5).
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
  copies the reader-visible items and their thumbnails (made in advance, as a read-only server
  can't write them) into the published vault folder and deletes the other items from the
  snapshot.
- The `media` field type holds an item id (a list for `multiple` fields); custom fields (M11) can
  use it.

## Implementation notes (#127, UI)

- **Replace file** (`Media.replace`): new bytes under the same item id, so every page, gallery,
  cover and map that uses it shows the new file. An image can only be replaced by an image; bytes
  another item already holds are refused (`409`, that item in `context.media_id`). The old file
  stays on disk (undo puts the old hash back). The SPA adds the item's hash to file URLs (`&v=`),
  since files are cached as immutable.
- **`image` node** (`modules/media/editor/image-node.tsx`): pasting or dropping image files
  uploads them (XHR, with progress) behind a placeholder decoration, so the document only ever
  holds stored images; the slash menu's "Image" opens the image picker. The node view edits the
  caption, the alt text and the width (Small 240, Medium 480, Large 960 px, Full). Editor
  extensions reach the vault and the writes through the core editor context
  (`editorContextOf(editor)`). Readers get a `<figure>` with a lazily loaded, `srcset`-sized image;
  with the module disabled the node shows its alt text.
- **Cover image**: the module's `entityHeaderMedia` for every kind (`'*'`), next to other modules'
  header media; authors add, change and remove it (`cover_media_id`).
- **Gallery panel** on every kind (shown to readers only when it has images): drag, or the
  arrow buttons, to reorder (a `sort_key` between the new neighbours), captions saved on blur,
  visibility per item, remove.
- **Media library** (`/m/media/library`, command "Open the media library"): grid, filters (text,
  type, unused, used by an entity, trash), multi-file upload, bulk trash/restore, and a sheet per
  file (alt text, caption, "Used by", download, replace, trash/restore).
- **`media` fields**: thumbnails when read; edited with the image picker (`fieldTypeEditors`).
- **Image picker** (`ImagePickerDialog`): the library's images with search, plus upload; shared by
  the editor, covers, galleries and fields.

## Implementation notes (#161, SVG)

- **Sanitizer** (`lore.modules.media.svg`, rules in `security.md` §3): an upload whose SVG it
  can't read is refused; the stored bytes stay as uploaded, and `GET …/file` sends the sanitized
  copy inline (cached next to the thumbnails, `media/thumbs/<sha256>_safe<VERSION>.svg`; made in
  advance on publish, like thumbnails). SVGs have no thumbnail sizes (`422`) and no dimensions.
- **Images** are raster images and SVGs (`storage.IMAGES`): an SVG is replaced only by an image, a
  raster image still only by a raster image. The SPA shows SVGs wherever it shows images (image
  picker, editor, covers, galleries, `media` fields) from the one sanitized file, without
  `srcset`; the maps picker offers raster images only (`rasterOnly`), as a map needs a size.

## Implementation notes (#162, deep zoom)

- **Decoding** moved from Pillow to libvips (`pyvips` with its bundled library,
  `pyvips[binary]`: no system package). It decodes streaming, so the pixel limit rose from 50 to
  400 megapixels (a 16k by 16k map is 268); uploads are still capped by `LORE_MAX_UPLOAD_MB`.
  Each type is decoded by its own loader, failing on truncated files. Thumbnails keep the stored
  orientation (no EXIF rotation, matching the recorded size), as before.
- **Tiles** (`storage.tile`): level `k` is the image shrunk `2^k` times (`ceil(width / 2^k)` by
  `ceil(height / 2^k)`), cut into 256 px tiles from the top left (the last column and row
  narrower); the coarsest level (`tile_levels`) fits in one tile. The first tile requested makes
  the whole pyramid in one pass (libvips `dzsave`, into a temporary folder renamed into place,
  one build per image at a time); a vault folder that can't be written makes the requested tile
  alone, in memory (slow: the publish step makes pyramids in advance). Replacing or purging the
  file leaves or removes its pyramid with its thumbnails.
- **Which images are tiled:** any raster image has tiles, but clients use them only for images
  whose longer side is above 8,192 px (`MediaItemOut.tile_levels`, null otherwise: about the
  largest image browsers and mobile GPUs take whole). Maps carry the same `tile_levels`.
- **Publish** makes and copies the pyramids of the reader-visible tiled images. A **static
  export** has no tiles (its files are copied by route and query): maps show the image whole
  there.

## Future ideas

Audio (pronunciations for lexicon entries), PDF previews, image annotations.
