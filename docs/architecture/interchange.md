# Portable JSON interchange

A documented, versioned JSON format for exporting a whole vault or one dimension and importing it
into another vault, of this app or a later one (#149, post-MVP). It complements backups
(`persistence-and-migrations.md` §5): a backup restores a whole vault as a new vault; an
interchange file is imported **into an existing vault**, whole or in part, with fresh ids or its
own. Code: `lore.core.interchange` (`format.py`: the document, codec and archive; `export.py`;
`importer.py`; `router.py`: the download and the upload; `spec.py`: what modules declare).

Decided by the product owner (2026-10-22, the defaults proposed on #149): a partial export is
**one dimension**, the multiversal entities it refers to travel as references; imports **remap
ids** by default (keeping them is an option); with kept ids, a clash **fails the whole import**
with a report by default (overwriting is an option).

## 1. Entry points

- **API**: `GET /vaults/{v}/export/interchange?audience=readers|author&dimension=<id or name>`
  → a zip (`<folder>[-<dimension>]-lore[-private].zip`), author-only (readers get `404`).
  `POST /vaults/{v}/import/interchange?ids=remap|keep&on_conflict=fail|overwrite` with the file
  (multipart `file`: the zip, or a bare JSON document without files) → the import report
  (`InterchangeImport`); `403 read_only` on a read-only server.
- **CLI**: `lore vault export-json <vault> --out <file.zip> [--audience readers|author]
  [--dimension D]` reads a copy of the database, so it runs next to a server.
  `lore vault import-json <vault> <file> [--keep-ids] [--overwrite]` opens the vault (its lock:
  stop the server first, or use the API).
- **UI**: Settings → Publishing → Export as JSON (whole vault or a dimension; readers’ view or
  everything) and Import JSON (the file, “Keep the file’s ids”, “Overwrite”, the report).

`audience`: `readers` (default) exports what readers see, as a published snapshot holds it (the
publish sanitizer runs on the copy: `visibility-and-sharing.md` §4); `author` exports everything,
private content included: treat it like a backup.

## 2. The file

A zip holding `lore-interchange.json` (the document) and the files of its rows
(`files/<table>/<row id>`: media items' files). A bare document (no files) imports too.

```json
{
  "format": "lore-interchange",
  "format_version": 1,
  "app_version": "1.0.0",
  "schema_revision": "4190f20677b4",
  "exported_at": "2026-10-22T23:00:00+00:00",
  "source": {"vault_id": "0190…", "name": "Aetheria"},
  "audience": "author",
  "scope": {"kind": "dimension", "dimension_id": "0190…", "name": "Aetheria"},
  "modules": ["characters", "groups", "…"],
  "references": [{"id": "0190…", "kind": "language", "name": "Common Trade"}],
  "tables": {"entities": [{"id": "0190…", "kind": "dimension", "…": "…"}], "links": ["…"]},
  "files": {"files/media_items/0190…": "<sha256>"}
}
```

- **`format_version`** covers this envelope. `lore.core.interchange.format.UPGRADERS[n]` turns a
  version `n` document into `n + 1` (frozen once released); a newer version is refused (`409
  interchange_newer_than_app`). Unknown top-level keys are ignored.
- **`tables`**: every **authored** table (what history records, `data-model.md` §7: core's and
  every module's `ModuleSpec.history_tables` not marked derived), each a list of rows with every
  column, in the schema of **`schema_revision`**. Derived tables (search, mentions, time
  dependencies, findings, media references, proposals) and history are never exported.
- **Values** (`lore.core.interchange.format.codec`): JSON columns as JSON (time specs, rich text,
  fields, calendar definitions… with their own `schema_version`s), moments (`SortableBigInt`
  columns, `*_t`, `duration`) as **decimal strings** (non-negotiable rule 1), booleans as
  booleans, everything else as SQLite stores it (ids, text, integers, ISO-8601 timestamps).
  Rows are exact copies: typed dates stay in their anchors, materialized occurrences are the only
  occurrences (rule 4).
- **`files`**: the sha256 of every file in the zip; any other entry is refused.

### 2.1 Older schemas

The importer brings rows to its own head with **its migrations**: a document whose
`schema_revision` is behind head is written into a scratch database migrated to that revision,
the database is upgraded to head (foreign keys unchecked: a partial document refers to records it
doesn't hold), and the rows are read back. So every data migration (JSON documents included) also
upgrades interchange files, with nothing to maintain beside it. A revision this app doesn't know
was written by a newer app: `409 interchange_newer_than_app`.

## 3. Export

Everything runs on a copy of the database (`snapshot`) opened in a staging folder, like a
published snapshot, so the vault is never written and a server can keep it open.

1. **One dimension** (`dimension`: its id or exact name; `404` if there is none, or readers
   can't see it in a readers' export): its records' time points anchored to records the export
   doesn't hold (another dimension's, through correspondences; calendars and dimensions it
   doesn't hold) are **frozen** at their resolved moments (`TimeWriter.freeze`, as before a purge,
   `time-model.md` §7.3; anchors to multiversal entities' records stay).
2. **Readers**: the publish sanitizer (`lore.core.vaults.publish.sanitize`) removes what `READER`
   hides and freezes anchors to it.
3. The tables are read; a dimension export keeps its part (§3.2).

### 3.2 What one dimension holds (`select_dimension`)

- Its entities: the dimension itself and every entity whose home dimension it is (calendars,
  timelines, events, branch-only entities…), in the trash too.
- Every other row that refers (by foreign key) to a kept row and to nothing else than kept rows
  and **multiversal entities**, until nothing changes. So links between its entities, and links,
  facts and worldline segments tying multiversal entities to it, come along; a multiversal
  entity's own aliases, tags and facts elsewhere don't. Optional references to rows left out are
  cleared (`OPTIONAL_REFERENCES`, as in published snapshots), other rows referring to them are
  left out (correspondences and sync points with other dimensions).
- Rows of tables without foreign keys come along when a kept row names them (tags, media items);
  definitions (custom link types, custom kinds and fields) always do; consistency suppressions
  never (their fingerprints can't tell which dimension they belong to).
- **References**: the multiversal entities named anywhere in the kept rows (foreign keys, rich
  text, anchors), with their kind and name; they aren't copied.

## 4. Import

One transaction (`BEGIN IMMEDIATE`) recorded as **one changeset** (origin `import`, summary
"Imported “Aetheria” from “…” (n entities)"), undoable like any other, and checked by the
consistency engine at commit with the target vault's severities (`422 consistency_error` refuses
it). Nothing is written when anything fails.

1. **Read** the zip (`security.md` §3: safe names, no symlinks, unlisted files, file-count and size
   caps, checksums; `422 invalid_interchange`), upgrade the envelope, bring the rows to head
   (§2.1) and decode them: every row must have exactly its table's columns.
2. **Modules**: records of modules the vault doesn't have enabled (their tables, kinds and link
   types; custom kinds need the custom fields module) refuse the import: `409
   interchange_modules_disabled`, `context.modules`.
3. **Ids**: `remap` (default) gives every row whose key is an id a fresh UUIDv7 (in the order of
   the old ids, so id order is kept), so importing twice gives two copies; `keep` keeps them.
   Every id-shaped string in the rows (foreign keys, anchors, rich-text links, field values,
   `fact:<id>` slot keys…) is rewritten with the same map. Suppressions are dropped with
   remapped ids (their fingerprints hash the old ids).
4. **References** are matched in the vault: the multiversal entity of the reference's kind with
   its id, else the only non-trashed multiversal entity of its kind and name. Rows naming an
   unmatched one by foreign key are left out (`dropped`); an optional reference is cleared.
   Mentions of it in rich text stay as they are (a missing link). More generally any foreign key
   pointing at neither an imported row nor one of the vault's is handled that way.
5. **Keys**: a row whose unique key (other than its primary key: a tag's name, a media item's
   content hash, a custom field's kind and key) the vault already has is taken as the vault's row
   when the table is `reuse_by_key` (tags, media items) or the two are the same (ignoring
   `created_at`, `updated_at`, `revision`); rows referring to it are pointed at the vault's.
   Otherwise it is a **conflict**.
6. **Primary keys** (kept ids, or keys that aren't ids: custom link types, custom kinds): a row the
   vault has the same is left alone (`reused`; re-importing a file into the vault it came from
   changes nothing); a different one is a **conflict**.
7. **Conflicts**: `on_conflict=fail` (default) refuses the whole import: `409
   interchange_conflict` with `context.count` and the first 50 `conflicts` (`{table, id, reason:
   "id" | "key", columns, name?}`). `overwrite` replaces the vault's rows with the file's (an
   automatic `pre-import` backup is taken first). Rows the file doesn't hold are never deleted.
   Other unique rules (one prime timeline per dimension…) that the rows break refuse the import
   with `409 interchange_conflict`.
8. **Write** the rows with Core statements (`history.record_bulk`), then the files of the
   tables that have them (`InterchangeTable.store`: a media file must have its item's checksum
   and type, `security.md` §3), then rebuild the **derived data** of what was written: time
   dependency edges and resolved moments (every slot of the written records resolves again, then
   everything anchored to them), search documents (entities and module documents) and mentions;
   module derived rows (media references) follow from the changeset (`derived_hooks`).

The report (`InterchangeImport`): `entities` written, rows `created`, `updated`, `reused` and
`dropped` by table, `references_matched`, `references_unmatched` (`{id, kind, name}`), `files`
stored and the `changeset_id` (`null` when nothing changed).

## 5. Modules

`ModuleSpec.interchange_tables` (`modules.md` §2.1): `InterchangeTable(table, reuse_by_key,
file, store)` declares how a module's table travels beyond its rows. Core declares `tags`
(`reuse_by_key`). Every module table recorded in history is exported without declaring anything.

- **media**: `media_items` are `reuse_by_key` (by content hash) and carry their files.
