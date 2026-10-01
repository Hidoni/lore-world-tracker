# Visibility and sharing

> D11: read-only server mode in the MVP, static export later. D12: visibility (public / spoiler /
> private) on entities, links/fields and rich-text blocks. **A shared view must never leak private
> content.** This document defines the model, the enforcement architecture and the tests that
> guarantee it.

## 1. Visibility levels

| Level | Author mode | Reader mode / exports |
|-------|-------------|------------------------|
| `public` | shown | shown |
| `spoiler` | shown with a spoiler marker | delivered with `spoiler: true`; UI folds it behind click-to-reveal |
| `private` | shown with a lock marker | **never delivered**, not even indirectly |

The default visibility for new content is a vault setting (default `public`).

## 2. Where visibility applies

Entities · aliases · tags (derived: a tag is visible if any visible entity uses it) · field values
(`entities.field_visibility`, with defaults from the field definition) · facts · links ·
rich-text blocks (`visibilityBlock`) · per-timeline notes · worldline segments ·
correspondences · timelines (as entities) · module rows (map pins, gallery items, lexicon entries)
· media (derived from references).

**Effective visibility** (the most restrictive wins):

- A link, fact, alias, note, segment or pin is visible only if its own level allows it **and**
  every entity it references is visible.
- Anything time-bound in a **private timeline** is invisible.
- A **media item** is visible only if at least one visible context references it (body image in a
  visible block, cover of a visible entity, gallery item, map of a visible location).
- An **entity link inside rich text** pointing to a hidden entity is rendered as plain text
  (the name stays if the block is visible: the author wrote it). The `entityId` attribute is
  stripped.
- A **time anchor** referencing a hidden record still resolves. Readers see the resolved date
  but not the reference (the "relative to …" explanation is omitted).
- **Derived data:** mention counts, backlink lists, graph edges, search snippets, consistency
  findings (never shown to readers), history (never shown to readers) and counts ("12 events")
  must all be computed from visible data only.

## 3. Enforcement architecture

1. **`VisibilityPolicy`** (core) is constructed per request: `AuthorPolicy` (sees everything) or
   `ReaderPolicy` (read-only mode or `?as_reader=true`). Every repository/query helper takes the
   policy and applies SQL-level filters (`visibility != 'private'` plus endpoint visibility
   joins). Python-side post-filtering is allowed only for rich text.
2. **Rich-text filtering** (`lore.core.richtext.filter_for_reader`) removes private
   `visibilityBlock`s, keeps spoilers flagged, and strips links to hidden entities. It is applied
   to bodies, rich-text fields and per-timeline notes.
3. **Search:** reader queries use only the `*_public` FTS columns (`data-model.md` §9) and join
   `search_docs.visibility`. Snippets are generated from public columns only.
4. **Modules** declare `visibility_filters` for their tables and `richtext_nodes` handlers for
   their node types. The module registry refuses to register a module whose read endpoints aren't
   covered (checked by the leak test suite, §5).
5. **Defense in depth:** reader-facing deployments serve **published snapshots** (§4), where
   private data does not exist at all.

## 4. Published snapshots

`lore vault publish <vault> --out <dir>` (and a button in settings):

1. `VACUUM INTO` a temporary copy of `lore.db`.
2. Run the **publish sanitizer** on the copy, in one transaction:
   - delete private entities and everything owned by them (aliases, facts, links, extension
     rows, notes, module rows),
   - delete private aliases, facts, links, segments, correspondences, notes and module rows,
   - remove private field values (and their facts), rewrite bodies/rich-text fields with
     `filter_for_reader` (spoilers kept, flagged),
   - drop history (`changesets`, `changes`), consistency findings/suppressions and proposals,
   - freeze anchors that reference deleted records (convert to absolute at the resolved moment),
   - module `publish_contributors` run their own sanitization,
   - rebuild search tables, `VACUUM`, set `journal_mode=DELETE`.
3. Copy only the media referenced by remaining visible contexts.
4. Write `vault.json` with `"published": true` and the source vault id. A published vault opens
   **read-only only**. The author UI refuses to open it in author mode, to avoid confusion.
5. Run the leak checker (§5) against the snapshot as a final gate. Publishing fails if any canary
   or private-marked data remains.

## 5. Leak tests (mandatory)

`backend/tests/visibility/` contains a **canary vault fixture**. Every kind of private content
(entities, aliases, field values, facts, links, blocks, notes, segments, correspondences, map
pins, lexicon entries, media, branch timelines) contains unique canary strings (`CANARY-<n>`) and
canary ids. The suite:

1. Enumerates **every GET route** in the OpenAPI document (including module routes). A route
   that isn't covered by a request recipe fails the test, so new endpoints must add recipes.
2. Calls each route in reader mode with realistic parameters (ids of public entities, windows
   covering everything, `at` cursors, searches for each canary string).
3. Asserts that no response body contains any canary string or canary id, that media downloads
   of private-only media return 404, and that counts exclude private items.
4. Runs the same assertions against a **published snapshot** of the fixture, served in read-only
   mode.

These tests run in CI on every PR that touches the backend.

## 6. Reader-facing read surface (static-export contract)

The reader UI may only use these read operations (DataSource methods). The post-MVP
`StaticDataSource` must implement all of them from a snapshot:

`meta`, `registry`, `entities` (list/filter), `entity` (+ `state` as-of), `tree`, `children`,
`links`, `backlinks`, `timelineWindow`, `eventTree`, `occurrences`, `search`, `quickSearch`,
`graph`, `familyTree`, `orgChart`, `locationTree`, `lexicon`, `languageFamilyTree`, `maps`/`pins`,
`mediaFile`, `correspondenceMap`, `personalTimeline`, `timelines` (tree).

Adding a reader-facing endpoint means adding it here, adding a leak-test recipe, and (post-MVP)
implementing it in `StaticDataSource`.

## 7. Read-only server mode

- Enabled by `LORE_READ_ONLY=true`. `LORE_EXPOSED_VAULTS` (comma-separated vault ids or folder
  names) limits what is served. The default is all vaults found, but published snapshots are
  recommended.
- Middleware rejects non-GET methods with `403 read_only` (before routing). The vault registry
  never creates, migrates, locks or writes anything. SQLite is opened `mode=ro` (published
  snapshots: `immutable=1`).
- `/meta` reports `read_only: true`. The SPA runs in reader mode.
- Docker compose ships a `reader` profile (`deployment.md`).

## 8. Static export (post-MVP, M13)

`lore vault export-static <vault> --out dist/`: build from a published snapshot. It writes the
SPA build (configured for `StaticDataSource` and hash routing) plus `data/` JSON chunks
(registry, entity index, entities sharded by id prefix, link adjacency, timeline tiles per
dimension/timeline at a few zoom levels, series rules, calendars, search index for MiniSearch,
media). The result is hostable on any static host ("run an http server serving the exposed
project", brief).

## 9. Backups vs sharing

Backups (`persistence-and-migrations.md` §5) are **full copies including private data** and are
never meant for sharing. The UI states this next to backup and publish actions.
