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
correspondences · timelines (as entities) · module rows (map pins and regions, gallery items, lexicon entries)
· media (derived from references).

**Effective visibility** (the most restrictive wins):

- A link, fact, alias, note, segment, pin or map region is visible only if its own level allows it **and**
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

1. **`VisibilityPolicy`** (`lore.core.visibility`) is constructed per request by the `PolicyDep`
   dependency: `AuthorPolicy` (sees everything) or `ReaderPolicy` (read-only mode or
   `?as_reader=true`). Every repository/query helper takes the policy and applies SQL-level
   filters (`visibility != 'private'` plus endpoint visibility joins): `entities(e)`,
   `entity_ref(column)`, `rows(row)`, `links(link)`, `field(entity, field)`,
   `module_rows(filter)`. Python-side post-filtering is allowed only for rich text
   (`filter_richtext`, `fields`). Reader rules beyond §2 (decided 2026-10-04):
   - An entity is hidden when it is private, **in the trash**, or its home dimension or origin
     timeline is hidden. The trash is author-only, like history: `GET /trash`, history and
     changesets answer `404`, `include_trashed` has no effect, and a trashed entity is `404` by id.
   - A visible entity whose **parent is hidden** stays visible as a root: `parent_id` is `null`
     in every response, and the tree lists it among the roots.
   - Hidden entities are `404 not_found` by id (checked before anything else, so readers can't
     tell them from missing ones), and filters naming them (`parent`, `dimension`, `tag`) match
     nothing.
   - A field value is hidden when its effective visibility (the entity's `field_visibility`
     override, else the field's `default_visibility`) is private. `field_visibility` only lists
     the fields readers see. `rich_text` values are filtered like bodies.
   - Backlinks report no private mention counts (`private: 0`), and an entity whose only mentions
     are in private blocks isn't listed.
   - Unlinked mentions search only the aliases readers see, and find occurrences in sources'
     bodies as filtered for readers (no private blocks), among entities readers see.
2. **Rich-text filtering** (`lore.core.richtext.filter_for_reader`) removes private
   `visibilityBlock`s, keeps spoilers flagged, and strips links to hidden entities. It is applied
   to bodies, rich-text fields and per-timeline notes.
3. **Search:** reader queries use only the `*_public` FTS columns (`data-model.md` §9) and join
   `search_docs.visibility`. Snippets are generated from public columns only.
4. **Modules** declare `visibility_filters` for their tables
   (`VisibilityFilter(model, visibility_column="visibility", entity_columns=())`: a row is visible
   when its own column isn't private and every entity it references is visible; queries apply it
   with `policy.module_rows(filter)`) and `richtext_nodes` handlers for their node types. The
   registry validates the filters (the module's own models, existing columns). A module whose read
   endpoints aren't covered fails the leak test suite (§5).
5. **Defense in depth:** reader-facing deployments serve **published snapshots** (§4), where
   private data does not exist at all.

## 4. Published snapshots

`lore vault publish <vault> [--out <dir>]` (default `LORE_PUBLISH_DIR`), `POST /vaults/{v}/publish`
and **Settings → Publishing** (`lore.core.vaults.publish`). `<dir>` is a data-dir root; the
snapshot replaces an earlier one of the same vault in `<dir>/vaults/<folder>/`.

1. Copy `lore.db` into a staging folder inside `<dir>` (SQLite's online backup: a consistent copy
   while the author server keeps writing).
2. Run the **publish sanitizer** on the copy, in one transaction, with the consistency engine in
   record-only mode and foreign keys deferred:
   - **freeze time points** first, while everything they reference is still there: every stored
     point (event start/end, fact and link validity and `time_point` values, entity `time_point`
     fields and their `entity_time_fields` rows, branch points, dimension presents, worldline
     segments, correspondence points, module rows with `valid_*_spec`) becomes what readers are
     shown (`ReaderTimes`: an anchor into a hidden record turns absolute at its moment). A series'
     rule in a calendar readers can't see is dropped: the snapshot can't keep that calendar, so
     the series becomes a single event at its first occurrence (live readers still get the
     occurrences, computed on the server),
   - delete the entities readers can't see (private, effectively private, trashed, of a kind no
     enabled module offers), private aliases, hidden or trashed links and facts, facts of fields
     readers can't see, each module's hidden rows (its `visibility_filters`), and in every table
     the rows with `visibility = 'private'` or a `deleted_at`,
   - repair references: an optional reference to a deleted row (`parent_id`, a fact's source
     event, a dimension's default calendar, a pin's child map, a segment's arrival/departure) is
     cleared; any other row referencing a deleted row is deleted, until nothing changes,
   - rewrite bodies, fields and per-timeline notes as readers get them (`filter_for_reader`:
     spoilers kept, flagged; hidden fields and overrides removed); unused tags go,
   - module `publish_contributors` run their own sanitization (`modules.md`; media copies the
     visible items' files and thumbnails, maps drop hidden maps),
   - drop history (`changesets`, `changes`, `change_entities`), consistency findings and
     suppressions, and proposals.
3. Rebuild every derived table (search, mentions, time, module checks: `lore vault reindex`) and
   rescan consistency, then drop the findings again; `VACUUM`, `journal_mode=DELETE`.
4. Write `vault.json` with `"published": true`, `source_vault_id` and `published_at`. A published
   vault opens **read-only only**: an author server refuses it with `409 vault_published`.
5. Run the **leak gate** on the staging folder: no rows in the dropped tables, no
   `visibility = 'private'` row, no private `visibilityBlock` in any text column, no SQLite side
   files. Any problem fails the publish (`409 publish_failed`) and the staging folder is deleted;
   only a clean snapshot is moved into place. The tests publish the canary vault and byte-scan
   every output file for canary strings and ids, then run the whole leak suite (§5) against the
   snapshot served read-only.

## 5. Leak tests (mandatory)

`backend/tests/visibility/` contains a **canary vault fixture** (`canary.py`). Every kind of
private content
(entities, aliases, field values, facts, links, blocks, notes, segments, correspondences, map
pins, lexicon entries, media, branch timelines) contains unique canary strings (`CANARY-<n>`) and
canary ids. The suite:

1. Enumerates **every GET route** in the OpenAPI document (including module routes). A route
   that isn't covered by a request recipe (`recipes.py`, keyed by the OpenAPI path) fails the
   test, so new endpoints must add recipes. A meta-test checks that an added route without a
   recipe fails.
2. Calls each route in reader mode with realistic parameters (ids of public entities, windows
   covering everything, `at` cursors, searches for each canary string).
3. Asserts that no response body contains any canary string or canary id (an error may echo
   the id the request named), that each call returns the recipe's expected status, that media
   downloads of private-only media return 404, and that counts exclude private items. It runs on
   a read-only server and with `?as_reader=true`. A positive control checks that the author sees
   every canary through the same recipes, so a missing canary means it was filtered.
4. Runs the same assertions against a **published snapshot** of the fixture, served in read-only
   mode (reader mode `published` in `test_leaks.py`).

5. Calls every **MCP tool and resource** (`test_mcp_leaks.py`, `mcp.md` §8) with the module's
   `access = readers`, on a read-only server and on a published snapshot, with the same byte
   scan, and checks that `access = author` reaches the private content. The MCP endpoint is a
   POST route outside the OpenAPI document and the static-export contract (§6).

These tests run in CI on every PR that touches the backend.

## 6. Reader-facing read surface (static-export contract)

The reader UI may only use these read operations (DataSource methods). The post-MVP
`StaticDataSource` must implement all of them from a snapshot:

`meta`, `vaults`/`vault`, `registry`, `settings`, `entities` (list/filter, by existence at `at`), `entity` (+ `state` as-of), `facts`, `causedFacts`, `tree`, `tags`, `fieldValues`, `children`,
`links`, `backlinks`, `unlinkedMentions`, `linkTypes`, `calendarPresets`, `timelineWindow`, `eventTree`, `causality`, `occurrences`, `search`, `quickSearch`,
`graph`, `characterRelationships`, `characterLife`, `characterFamilyTree`, `groupMembers`, `groupLeaders`, `groupTerritory`,
`groupOrgChart`, `locationTree`, `locationEvents`, `locationResidents`, `speciesMembers`,
`speciesDescentTree`, `lexicon`, `lexiconEntry`, `lexiconExport`, `languageFamilyTree`, `maps`/`mapDetail`, `entityPins`, `mediaItems`, `mediaItem`, `mediaFile`, `mediaTile`,
`gallery`, `correspondences`, `correspondence`, `correspondenceMap` (`mapMoment`), `worldline`, `personalTimeline`, `presence`, `timelines` (tree),
`timelineDiff` (`branchDiff`), `timelineNotes` (`timelineNote`).

Names are the `DataSource` methods (`frontend/src/data/source.ts`; `lexiconExport`,
`mediaFile` and `mediaTile` are URLs the SPA links to). Every other GET route is author-only (`404` for readers:
history, trash, consistency, backups, custom field and kind definitions). The audit of #139 lists
each route's reader status from the leak recipes: a route a reader gets `200` from belongs here.

Adding a reader-facing endpoint means adding it here, adding a leak-test recipe, and (post-MVP)
implementing it in `StaticDataSource`.

## 7. Read-only server mode

- Enabled by `LORE_READ_ONLY=true`. `LORE_EXPOSED_VAULTS` (comma-separated vault ids or folder
  names) limits what is served. The default is all vaults found, but published snapshots are
  recommended.
- Middleware rejects non-GET methods with `403 read_only` (before routing, also for paths no
  route has; `ReadOnlyMiddleware`). The vault registry never creates, migrates, locks or writes
  anything, and the maintenance scheduler is off. SQLite is opened `mode=ro`, with
  `immutable=1` for published snapshots and databases no author is writing, so a read-only run
  changes no file in the data folder (`backend/tests/test_read_only.py`). Vaults not at head are
  refused (`409 vault_needs_migration`).
- `/meta` reports `read_only: true`. The SPA runs in reader mode.
- Docker compose ships a `reader` profile (`deployment.md`).

## 8. Static export (post-MVP, M13)

`lore vault export-static <vault> --out dist/`: build from a published snapshot. It writes the
SPA build (configured for `StaticDataSource` and hash routing) plus `data/` JSON chunks
(registry, entity index, entity shards, the rows timeline windows are computed from, series
rules, calendars, module reads, the search documents, media). The result is hostable on any static host ("run an http server serving the exposed
project", brief).

Implementation (ADR 0016; #147, split into #373–#378):

- **Builder** (`lore.static_export`, #373): refuses anything but a published snapshot and an
  output folder that isn't empty; starts the app read-only over the snapshot, in process, and
  records reader GET responses: `/api/v1/<route>` → `data/<route>.json`. Copies the SPA build
  (`--spa`, default `LORE_STATIC_DIR`), marks its `index.html` (`<meta name="lore-static">`, the
  `<base>` made relative) and writes `static.json` (`format: 1`, vault, app version, published
  and exported times). The tests byte-scan the canary vault's export like a snapshot (§5).
- **StaticDataSource** (`frontend/src/data/static.ts`): the HTTP data source over a `fetch` that
  reads the files, with hash routing. Reads with free parameters have a handler answering from a
  recorded full answer (tags: the full list, filtered by prefix and limit); anything else not in
  the export answers `404 not_in_export`.
- **Entity reads** (#374, `lore/static_export/entities.py`, `frontend/src/data/static-entities.ts`):
  - an **index** (`data/vaults/<v>/static/index.json`): every listed entity's summary as the
    server lists it, the server's own order for each sort (read with its keyset columns, so the
    browser never compares names), tags, aliases, branch origin, existence over time per
    timeline, and each timeline's lineage. `entities` (filters, sorts, paging, the cursor),
    `tree` and `children` are answered from it; the export's paging cursors are its own;
  - a **shard** per entity (`static/entities/<id>.json`): the entity, its facts (per
    timeline), links, backlinks, unlinked mentions, the facts it caused, and per timeline its
    state, links and backlinks **at each moment they can change** (`bound_moments`: each
    bound's first and last moment, from the resolver's extents). An as-of read is the same
    between two such moments, so the browser takes the last one at or before the cursor;
  - `fieldValues` is not exported: only editors call it.
- **Time reads** (#375, `lore/static_export/time.py`, `frontend/src/data/static-time.ts`):
  per timeline its event tree (every level) and the cause → effect graph around each event (at
  depth 6 and 500 nodes, trimmed in the browser to the depth and limit asked; one file per
  event), a branch's diff;
  per entity its notes, worldline segments and personal timeline per timeline, and its presence
  in every timeline at each moment it can change; correspondences, with mapping computed by
  `@lore/chronology` along the server's path for each pair of dimensions.
- **Timeline windows and occurrences** (#375, `lore/static_export/windows.py`,
  `frontend/src/data/static-windows.ts`) are **computed in the browser** (ADR 0016's exception):
  a port of `core/time/window.py` and `series.occurrences` over each timeline's rows as its view
  resolves them (each root's candidate rows nearest first, with the item each shows), the
  filters' inputs (tags, visible participants and their kinds, the events above each event), and
  the series rules with their calendars, expanded with `@lore/chronology`. Any range, zoom,
  budget and filter answers like the server.
- **Module reads and media** (#376, `lore/static_export/modules.py`,
  `frontend/src/data/static-modules.ts`): each module declares the reads a static export records
  (`ModuleSpec.static_reads`, `modules.md`), so the builder never imports modules. Each read is
  recorded per route into `static/reads/<route>`: the answer for each query the app sends, and
  as-of answers at each moment they can change in each timeline (the bounds of the facts and links
  of every entity the read names, and the moments it names itself), kept where they change. The
  lexicon and the media library are recorded whole and filtered and paged in the browser like
  the server does (ASCII-lowercase prefix and substring matching). A read naming its entity in
  the query (the local graph's `center`, a location's `root`) has a file per entity under
  `static/split/` (listed in `static/split`), and each file stores the objects of its answers'
  lists once (`pool`; the lists are `{"#": [index, …]}`), since answers in other timelines and
  at other moments mostly repeat them. Downloads (media files and
  their thumbnails, lexicon CSVs) are copied under `static/files/`, listed in `static/files`, and
  `mediaFileUrl`/`lexiconExportUrl` point at the copies. Org charts are recorded at each number
  of levels the page offers (1–6).
- **Computed module views** (#386; ADR 0016's exception, like windows): views whose settings
  multiply are computed in the browser from data the module exports (`ModuleSpec.static_data`,
  written to `static/m/<module>/`):
  - **family trees** (`frontend/src/data/static-family.ts`, a port of `family_tree`): every
    family link a reader sees and each character's lifespan per timeline, with names and
    existence from the entity index; any generations up and down, with or without spouses and
    siblings, any limit;
  - **the graph** (`frontend/src/data/static-graph.ts`, a port of `GraphReader`): every link a
    reader sees with where each bounded one is valid in each timeline (read with the module's
    own query at every moment a record of the timeline can change at), and the mentions; nodes,
    tags, parents, branch scope and existence from the index. Any filters (kinds, link types,
    tags, mentions, hierarchy, scope), center and depth, limit and cursor give the server's
    nodes in its order and its edges (in another order).
- **Search** (#377, `lore/static_export/search.py`, `frontend/src/data/static-search.ts`): the
  documents a reader can search (in any timeline, with their entity's branch origin) and their
  public columns, from the snapshot, loaded on the first search. `search` and `quickSearch` are
  the server's ported: the expression grammar, matching as FTS5's `unicode61 remove_diacritics 2`
  tokenizer (word starts, exact phrases, OR, NOT, groups), the filters, snippets, and the quick
  switcher's word starts then substrings (the `trigram` table). The same queries find the same
  documents with the same snippets; their order follows the same bm25 formula and column
  weights over the exported documents' statistics, so ties and near ties can be ordered
  differently from the server's (whose statistics count every row of its FTS table).
- **Parity** (`e2e/static-parity.spec.ts`): the tiny sample world's export answers what the
  read-only server answers for the same snapshot: every entity's reads, as-of reads around every
  bound in every timeline, lists with each filter and sort, trees, paging; the time reads; windows
  over the whole dimension and at every zoom (by powers of ten), at several budgets and with each
  filter, and every series' occurrences as each timeline sees them, at several windows and limits;
  every declared module read at every moment around every bound, the lexicon and media lists
  filtered and paged, and the copied files byte for byte; family trees at every generations,
  spouses and siblings setting, and the graph with each filter, at every moment, and around every
  entity at each depth (edges compared as sets); search and the quick switcher for many
  queries, filters and timelines (the same hits and snippets; order not compared).
- **Recording** runs the reads in a pool of worker processes (`LORE_EXPORT_WORKERS`, default
  the CPU count up to 8), each with its own read-only app over the snapshot; reads are
  independent, so the files are the same as one process would write. Tests pass their own
  modules and record in process.
- **From the app** (#378): **Settings → Publishing → Export static site**
  (`POST /vaults/{v}/publish/static`, author-only) exports the latest snapshot into
  `LORE_PUBLISH_DIR/static/<vault folder>/` with the SPA build `LORE_STATIC_DIR`. It is built
  beside the old site and swapped in once complete; the publish status says when and where.
- **Loading**: the app loads no data before the first page but `meta`, `vaults`, `settings`,
  `registry` and the downloads list; each page then loads the files its reads need (the entity
  index on the first entity read, one shard per entity, a timeline's rows on its first window,
  the search documents on the first search). Budgets: `testing.md` §4.
- **Exported**: `meta`, `vaults`/`vault`, `settings`, `registry`, `linkTypes`,
  `calendarPresets`, `tags` (#373), the entity reads (#374), the time reads, windows and
  occurrences (#375), module reads and media (#376), search (#377); the Publishing UI, budgets
  and the reader journeys end to end (#378), module views at every setting (#386).

## 9. Backups vs sharing

Backups (`persistence-and-migrations.md` §5) are **full copies including private data** and are
never meant for sharing. The UI states this next to backup and publish actions.

The **Markdown export** (`markdown-export.md`) reads the vault with the policy of its audience:
`readers` (the default) holds exactly what readers see and is safe to share; `author` holds
private content too and is treated like a backup (the UI says so). Its download is author-only
(`404` for readers); the tests byte-scan the canary vault's readers' export like a snapshot.
