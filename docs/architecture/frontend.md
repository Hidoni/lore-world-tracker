# Frontend architecture

> The SPA is the author's workbench and the reader's wiki. It is desktop-first and
> keyboard-friendly. Most of the UI is **generated from the vault registry** (kinds, fields, link
> types), with module-specific panels and views layered on top.

## 1. Stack

React 19 · TypeScript (strict, `noUncheckedIndexedAccess`) · Vite · TanStack Router (code-based
route tree) · TanStack Query · Zustand · Tailwind CSS v4 · shadcn/ui (Radix) · lucide-react ·
sonner (toasts) · cmdk (command palette) · react-hook-form + zod · TipTap v3 · sigma.js v3 +
graphology (+ ForceAtlas2 worker) · @xyflow/react + elkjs · Leaflet + react-leaflet · dnd-kit ·
TanStack Virtual · openapi-typescript + openapi-fetch · Vitest + Testing Library + MSW ·
Playwright.

## 2. Source layout

```
frontend/src/
  main.tsx
  app/              # providers (QueryClient, DataSource, theme), route tree assembly, shell layout, error boundaries
  api/              # schema.gen.ts (generated), client.ts (openapi-fetch + middleware), errors.ts
  data/             # DataSource & Mutations interfaces, HttpDataSource, query keys, domain mappers, hooks
  core/
    registry/       # kind/field/link-type registry (server registry merged with module UI configs)
    modules/        # defineModule, module activation, extension-point registries
    shell/          # top bar, sidebar navigation, right panel, command palette
    entities/       # generic entity page, create dialogs, lists, trash
    fields/         # field renderers/editors per type, temporal field history UI
    links/          # relations panel, add-link dialog, backlinks/mentions
    time/           # MomentDisplay, TimePointPicker, DurationPicker, EndSpecPicker, RecurrenceEditor,
                    # CalendarEditor, BigNumberInput, TimeCursorControl, ImpactPreviewDialog
    timeline/       # TimelineView and its layers
    events/         # event page sections, event outline, causality view
    consistency/    # findings panel, badges, rule settings
    history/        # entity history, recent changes, undo
    search/         # search page, quick switcher
    settings/       # vault/app settings pages
    reader/         # reader-mode presentation helpers (spoilers, mobile layout)
  editor/           # TipTap setup, custom nodes/marks, suggestion menus, renderers
  components/ui/    # shadcn/ui components (generated, owned)
  components/       # shared presentational components
  modules/          # module frontends (see modules.md §3)
  lib/              # small utilities (no domain logic)
  styles/
frontend/e2e/       # Playwright
```

Each top-level folder of `src/` is an element for eslint-plugin-boundaries (root
`eslint.config.js`). The enforced rules are:

- `core` never imports `modules` (modules.md §3).
- `lib` and `components` never import `app`, `core`, `modules`, `data` or `editor`.
- Only `app` imports `app`.

`frontend/src/test/boundaries.test.ts` lints synthetic imports against the real config, so a
boundary that silently stops matching fails the test suite.

`@lore/chronology` is consumed from source (its `exports` points at `src/index.ts`, see
`packages/chronology/README.md`), so no build step runs before the frontend.

TypeScript is pinned to `~6.0` because typescript-eslint supports `<6.1`. ESLint stays on 9
until eslint-plugin-jsx-a11y supports 10.

## 3. App shell

- **Top bar:** vault switcher · dimension switcher · timeline switcher (only when branches exist) ·
  display-calendar selector · **time cursor control** (Present / All time / pick a moment /
  step ±1 unit) · search (`Ctrl/Cmd+K`) · mode badges (Read-only, Previewing as reader) ·
  settings.
- **Left sidebar (resizable, collapsible):** dimension overview, timeline, **event hierarchy**
  (top-level events by time, lazily expandable into sub-events), one section per enabled kind
  (tree by `parent_id`), misc tree, pinned, recent. Multiversal entities appear with a badge in
  every dimension.
- **Main area:** the current route.
- **Right panel (context, collapsible):** backlinks and mentions, local graph (graph module),
  document outline, consistency findings for the current entity, history, and the as-of summary.
- Mobile/reader: the sidebar becomes a drawer, the right panel moves below content, and editing UI
  is absent.

Implementation (`core/shell/`, #58): the sidebar width (180–480 px, keyboard-resizable through its
`separator` handle) and the open/closed sidebar and context panel persist in `localStorage`
(`lore.shell`). Below `md` the sidebar is a `Sheet` drawer opened from the top bar. A skip link
leads to `#main`. `Ctrl/Cmd+K` (or the top bar's Search button) opens the command palette
(#67, `core/palette/`). With nothing typed it shows recent entities and every command. Typing
finds entities by name or alias (`/search/quick`), filters the commands and offers "Search
everything for …" (the search page). Core commands: new entity of each creatable kind, go to a
dimension or its timeline, go to a vault page, toggle the theme, show shortcuts. Modules add
commands through `commands` (run with `{vault, navigate}`). When results arrive, the first entry
is selected, so typing a name and pressing Enter opens it. `?` (outside text fields and the
editor) opens the keyboard shortcuts sheet. The top bar's dimension switcher is a placeholder until M5. API errors become `sonner` toasts
through the `QueryClient` caches (`app/query-client.ts`); a query or mutation that shows its error
itself passes `meta: { toast: false }`. Every route gets the default error boundary
(`app/route-error.tsx`) and unknown paths a 404 page.

Sidebar navigation (`core/navigation/`, #65):

- **Sections:** one per kind, for dimensions and every non-system kind except events (their
  hierarchy arrives in M5). Each is a tree by `parent_id`, loaded one level at a time from `/tree`
  (`kind=<key>`, then `parent=<id>` when a node opens, with "Show more" past 200). Roots are
  entities whose parent isn't of the same kind. Multiversal entities carry a ∞ badge. Collapsed
  sections are remembered (`lore.sidebar.collapsed`). Each heading links to the kind's list and
  has a "New …" button.
- **Drag and drop** (dnd-kit; pointer, or Space then arrow keys from a focused row): drop on an
  entity to move inside it, or on a section heading to move to the top. `canReparent` mirrors the
  server's parent rules (`data-model.md` §3.4): allowed parent kinds, no cycles, same dimension
  unless one side is multiversal. A refused drop says why in a toast, and the screen-reader
  announcements use entity names.
- **Context menu** on every row: new child (create dialog with the parent and its dimension
  filled in), rename, pin/unpin, move to trash (with undo). Readers only get pin.
- **Pinned and recent** per vault in `localStorage` (`lore.pinned.<vault>`, `lore.recent.<vault>`,
  last 10). The entity header has a pin button; visiting an entity records it, and a purge
  forgets it.

## 4. Routing

Code-based TanStack Router tree assembled in `app/` from core routes plus module route factories.

```
/                                       vault picker (redirects to last-opened vault)
/v/$vault                               vault home: dimensions, recent changes, pinned
/v/$vault/d/$dimension                  dimension overview: time spec, calendars, timelines, stats
/v/$vault/d/$dimension/timeline         timeline view
/v/$vault/d/$dimension/events           event outline (tree table)
/v/$vault/e/$entity                     entity page (any kind; `?tab=` for module tabs)
/v/$vault/k/$kind                       entity list of a kind
/v/$vault/calendars/$calendar/edit      calendar editor
/v/$vault/search                        search results
/v/$vault/changes                       recent changes
/v/$vault/trash                         trash
/v/$vault/consistency                   findings
/v/$vault/settings/*                    general, modules, consistency, link types, backups (+ module settings pages)
/v/$vault/m/<module>/*                  module routes (graph, lexicon, maps, …)
```

Global search params (validated with zod): `tl` (timeline id), `at` (moment string, `present` or
`all`), `cal` (display calendar id). Timeline view adds `from`, `to` and filter params. The last
used values are remembered per vault/dimension in `localStorage` (wrapped in try/catch).

- **Search serialization** (`app/search.ts`): values stay strings (TanStack Router's default
  parser would turn `?at=123` into a number and long moments into lossy floats). Only JSON arrays
  and objects (filters) are parsed; invalid global params are dropped, not errors.
- **Search page** (`/v/$vault/search?q=&kind=&dimension=`, #67): the query (words, "phrases", OR,
  -word) and kind/dimension filters live in the URL. Hits show the kind icon, a highlighted snippet
  with its source (body, aliases, fields…), and module documents (`doc_type` `<module>.<type>`)
  through the module's `searchResultRenderers`. Pages of 20 load with "Show more results".
- **Settings** (`/v/$vault/settings/*`, `core/settings/`, #69): General (the vault's name, the
  default visibility of new entities, and the theme, kept in this browser), Modules, Link types,
  Backups, then the active modules' `settingsPages` (at `settings/<id>`), in a side navigation.
  Modules: switches with the module's description and needs. Enabling one whose dependencies are
  off, or disabling one that enabled modules need, first lists what else will switch, then sends
  `{enabled}` or `{enabled: false, cascade: true}`. A `409 module_has_dependents` (state changed
  meanwhile) asks again with the server's list. Every query of the vault refreshes after a toggle.
  Link types: built-in ones read-only. Custom ones are created and edited (label, inverse label,
  description, source/target kinds or any, symmetric (fixed after creation), dates, repeats),
  archived and deleted; a `409` explains itself ("archive it instead"). Backups: the private-data
  notice, the list with downloads (`backupDownloadUrl`), "Back up now" (with or without media),
  the schedule, and restoring a zip into a new vault. The restore upload uses XHR for its
  progress bar (`restoreBackup(file, onProgress)`), and the page links to the restored vault.
- **Vault picker:** `/` lists the vaults (create, rename, move to trash) and opens the last-opened
  vault (`lore.lastVault`, set by every `/v/$vault` route) when it still exists. `/?pick=true`
  always shows the picker (the top bar's vault switcher links there).

## 5. Data layer

### 5.1 DataSource and Mutations

```ts
interface DataSource {          // reads only — implementable from a static snapshot (post-MVP)
  meta(): Promise<Meta>
  registry(vault): Promise<Registry>
  entity(vault, id, ctx?: TimeCtx): Promise<Entity>
  entities(vault, query): Promise<Page<EntitySummary>>
  tree(vault, query): Promise<TreeNode[]>
  links(vault, id, query): Promise<Link[]>
  backlinks(vault, id): Promise<Backlinks>
  timelineWindow(vault, timeline, query): Promise<TimelineWindow>
  graph(vault, query): Promise<Graph>
  search(vault, query): Promise<Page<SearchHit>>
  // … one method per reader-facing endpoint (visibility-and-sharing.md §6)
}
interface Mutations { /* author-only writes; absent in read-only/static contexts */ }
```

- Components use **hooks** (`useEntity`, `useTimelineWindow`, …) built on TanStack Query and the
  DataSource from context. They never call `fetch` or the generated client directly.
- `HttpDataSource` wraps the generated `openapi-fetch` client. Its middleware adds
  `X-Lore-Client: web` and converts problem+json into `ApiError {status, code, errors, context}`.
- **Domain mapping:** data-layer mappers convert every **resolved moment** (`*_t`, window items,
  bounds) from string to `bigint`. Time **specs** stay JSON (strings) and are consumed by
  `@lore/chronology`. Implementation (#59): `make gen` types every `format: bigint` field of the
  OpenAPI document as the branded `MomentString` (`api/moment.ts`) and writes
  `api/moments.gen.ts`, which says where moments sit in each schema. `toDomain(value, schema)`
  converts a response along it and `Domain<T>` is its type (moments → `bigint`). Moments inside
  an entity's `ext` (kind-specific JSON) are listed per kind in `data/domain.ts` (`EXT_MOMENTS`;
  module kinds add theirs with the KindRegistry, #60). Requests take `bigint` (`toWire`,
  `momentString`). `stringifyDomain`/`parseDomain` keep bigints through JSON (`{"$bigint": "…"}`).
  The ESLint rule `lore/no-number-moment` (`eslint-rules/`) rejects `Number()`, `parseInt()`,
  `parseFloat()` and unary `+` on `bigint` or `MomentString` values in the frontend.
- **Boundaries:** only `data/` and `app/` import `api/` (eslint-plugin-boundaries); components use
  hooks. `DataProvider` (in `AppProviders`) supplies `createHttpDataSource()` and
  `createHttpMutations()`; reader and static contexts pass `mutations={null}`, and mutation hooks
  then reject with "This view is read-only".
- **Invalidation:** every write response includes
  `affected: {entities: id[], dimensions: id[], time_changed: bool, search_changed: bool}`. A
  central `invalidateAffected()` maps that to query keys (entity, lists, tree, backlinks, windows
  of affected dimensions…). `entities` includes the records the write moved through time
  propagation (the dependents of a moved event, …), and `time_changed` says that some stored
  moment or status changed, so timeline windows of `dimensions` are stale (`api.md` §2).
- **Query keys:** `[vault, area, id?, params?]`, defined in `data/keys.ts` only (`meta` and the
  vault list sit outside any vault). `invalidateAffected` (`data/invalidate.ts`) marks the vault's
  lists, trees, change feed and findings stale on every write, plus each affected entity's own
  queries; `time_changed` refreshes the vault's windows, event trees, occurrences and timelines
  (windows are keyed by timeline, not dimension), and `search_changed` the search queries.
- **Errors:** `ApiError`s become toasts (`app/query-client.ts`) except `409 revision_conflict`
  (`isRevisionConflict(error)`: the conflict dialog) and calls with `meta: { toast: false }`.
  `fieldErrors(error)` maps a problem's `errors[]` to form fields.
- **Autosave:** field edits save on blur/enter. Rich text autosaves 1.5 s after the last
  keystroke and on navigation. `409 revision_conflict` opens a conflict dialog (reload theirs /
  overwrite / copy mine to clipboard).

### 5.2 Generated API types

`make gen` (`npm run gen:api -w frontend`, i.e. `frontend/scripts/gen-api.ts`) runs
`uv run lore openapi` (dumps the OpenAPI JSON), then `openapi-typescript`, which writes
`src/api/schema.gen.ts` (committed, excluded from ESLint and Prettier). `make check-contract`
(part of `make check`, `npm run check:api`) regenerates it in memory and fails on diff. Never edit
generated files.

`src/api/client.ts` wraps it in an `openapi-fetch` client with two middlewares: non-GET/HEAD/OPTIONS
requests get `X-Lore-Client: web` (`security.md` §2), and every non-2xx response is thrown as an
`ApiError` (`src/api/errors.ts`: `status`, `code`, `title`, `detail`, `errors`, `context` from the
problem body; non-problem responses get `code: http_<status>`). `unwrap(api.GET(…))` returns the
body. Only the data layer calls the client.

## 6. Rich-text editor (TipTap)

Document JSON is stored as-is (`entities.body`). Node/mark schema, versioned by
`body_schema_version` (shared constant with the backend):

| Node / mark | Purpose |
|-------------|---------|
| StarterKit subset | paragraphs, headings 1–4, lists, blockquote, code block, hr, bold/italic/strike/code |
| `link` (mark) | external links; `http(s)`/`mailto` only |
| `table`, `tableRow`, `tableCell`, `tableHeader` | tables |
| `entityLink` (mark, attrs `{entityId}`) | internal link. Created by `[[` or `@` autocomplete (search + "create new …"). Renders with the kind icon. Missing/trashed/hidden targets render as plain text. |
| `timeRef` (inline atom, attrs `{timePoint}` or `{ref: slot ref}`) | a date rendered **in the reader's display calendar** ("in {Year 1023} the empire fell"). Click opens a popover with all calendars and "show on timeline". |
| `visibilityBlock` (block wrapper, attrs `{level: 'spoiler' \| 'private', label?}`) | block-level secrets (D12). Author mode shows a labeled frame. Reader mode: private is removed server-side, spoiler folds. |
| `callout` (block, attrs `{tone}`) | notes, warnings, quotes |
| `image` (media module, attrs `{mediaId, alt, caption, width}`) | embedded media |
| module nodes (registered via `editorExtensions`) | e.g. lexicon word references |

Behaviors: a slash menu (`/`), markdown shortcuts, paste-from-Markdown (`[[Name]]` turns into
`entityLink` when the name resolves uniquely), and a word count. The backend validates allowed node
types and extracts mentions, time refs, media refs and plain text (`lore.core.richtext`).

Implementation (`src/editor/`, #63):

- `RichTextEditor` (lazy-loaded as `LazyRichTextEditor`, its own chunk) configures StarterKit and
  the table kit to the stored schema. Attributes TipTap adds but the server doesn't store
  (`orderedList.type`, `link.title`, table cell `align`) are removed, and underline is off. A test
  checks every node, mark and attribute the editor produces against the server schema, and that
  `RICH_TEXT_SCHEMA_VERSION` equals the backend's. `callout`, `visibilityBlock` and `timeRef`
  are kept as they are until #64/#86 give them a UI.
- `[[` (names may contain spaces; a closing `]]` is ignored) and `@` open a menu fed by
  `/search/quick`: arrow keys, Enter/Tab and Escape work, and the last entry, "Create “…” as…",
  opens the create dialog with the name filled in, then links to the new entity.
- Autosave: 1.5 s after the last change, on blur and when the editor unmounts (navigation); one
  save at a time. A status shows "Unsaved changes", "Saving…" and "Saved", and the page warns
  before closing with unsaved changes. Saves go through `useEntitySaver`, which keeps the revision
  of its last save, so successive autosaves don't conflict with themselves. A conflict stops
  autosaving, and the conflict dialog decides.
- `RichTextView` renders the same schema without TipTap (readers and the trash). `EntityLinkView`
  shows the target's kind icon, links to it and has a hover card with its summary. Missing,
  trashed and hidden targets render as plain text.
- Renaming an entity relabels the links reading its old name in other entities' text, on the server
  (`api.md` §2, decided 2026-10-11).
- Writes report the entities whose mentions changed in `affected.entities` (`api.md` §2, Entities), so
  backlinks refresh after a save.

Editor II (#64):

- `visibilityBlock` and `callout` are React node views (`blocks.tsx`). Authors see a dashed frame
  with its level (spoiler / private, changeable) and an optional label; a callout shows its tone.
  Both can be removed while keeping their content. The renderer folds spoilers (`<details>`, labelled)
  and frames private blocks for authors (readers never receive them).
- The slash menu (`/` at a word start) lists the core block types: text, headings 1–4, lists,
  quote, code, divider, table, the three callout tones, and spoiler and private blocks. Module
  extensions add theirs through the option `slashItems: SlashItem[]` of an `editorExtensions`
  entry. Typing filters by title words and keywords; arrow keys, Enter and Tab work. The toolbar
  also has callout, spoiler and private buttons.
- Pasting plain text that looks like Markdown (headings, lists, quotes, code, emphasis, links) or
  holds `[[Name]]` converts it (`marked`). Raw HTML stays text, images become their alt text, and a
  code block keeps its language only if the server accepts it. A single line is pasted inline.
  `[[Name]]` and `[[Name|label]]` become entity links when the quick switcher finds exactly one
  entity with that name or alias (case-insensitive); otherwise the text stays plain and a warning
  toast lists the names. Pastes that carry HTML are left to the editor.
- Contract: `spec/richtext/fixtures/*.json` are documents the editor produces (every slash item,
  marks and tables, a Markdown paste). `frontend/src/editor/fixtures.test.ts` keeps them equal to
  the editor's output (`UPDATE_FIXTURES=1` rewrites them), and `backend/tests/test_richtext.py`
  checks that the server accepts each without loss.

Server rules for saved documents (bodies and `rich_text` fields; `lore.core.richtext.schema`):

- Node and mark types, where each may appear (blocks vs inline content, list items in lists,
  rows/cells in tables, plain text in code blocks) and their attributes are validated. Unknown
  node types, mark types **and attributes** fail the save with `422` and a path into the document
  (decided 2026-10-04): an editor feature the server schema doesn't know must surface in tests,
  not be silently lost, so adding one updates the server schema in the same PR. The only ignored
  attributes are editor defaults deliberately not stored: the `link` mark's `target`, `rel` and
  `class` (the app sets them when rendering).
- `link` marks whose `href` isn't `http(s)`/`mailto` are **removed, keeping the text** (decided
  2026-10-04), so a pasted unsafe link never makes autosave fail.
- Attribute values per node: `heading.level` 1–4, `orderedList.start` ≥ 0, `codeBlock.language`,
  table cells `colspan`/`rowspan`/`colwidth`, `visibilityBlock.level` spoiler/private with an
  optional `label`, `callout.tone` note/warning/quote, `timeRef` exactly one of `timePoint`
  (TimePoint JSON) or `ref` (slot ref), `entityLink.entityId` (a UUID; missing entities are
  allowed). Missing defaults are filled in. Nesting is limited to 64 levels.
- Module node types come with a `RichTextNodeHandler` (`ModuleSpec.richtext_nodes`): attribute
  validation, reader filtering, text and reference extraction. Handlers of every module apply,
  enabled or not.

## 7. Registry-driven entity UI

- On vault open, `GET /registry` is merged with module UI configs into the **KindRegistry**
  (labels, icons, colors, fields, allowed parents, link types, panels). Implementation:
  `modules.md` §3 (#60).
- **Entity page** (generic for every kind):
  1. Header: icon, name (inline edit), kind badge, aliases, tags, visibility toggle, home
     dimension or multiversal badge, branch-only badge, breadcrumbs (parent chain).
  2. Fields panel: grouped by `section`, with renderers/editors per field type. Temporal fields
     show their as-of value and a history popover (facts timeline with add/edit).
     There is a per-field visibility toggle.
  3. Body: TipTap editor (reader: renderer).
  4. Relations: links grouped by link type (forward/inverse labels), validity shown, with an
     add-link dialog (target search, type filtered by kinds, role, validity pickers, visibility).
  5. Time: existence intervals, events the entity participates in (sorted, with roles), and for
     events: dates in **all** calendars, duration, parent chain, sub-events, causes/effects,
     occurrences.
  6. Module panels/tabs (family tree, lexicon, map, gallery…).
  7. History (per-entity changes with undo).
- **Links** (`core/links/`, #66): the relations panel groups the entity's links by type and
  direction, labelled from its side (forward or inverse label; symmetric links once). Each link shows
  its role, its `data` (the link type's `linkTypeRenderers` component, which gets role and data, or a
  `key: value` summary) and a visibility badge, with edit and remove for authors. The add-link
  dialog searches targets (`/search/quick`), then offers the link types whose source/target kinds
  fit both ends, in either direction (the inverse label when the entity is the target; archived types
  excluded). It also takes a role, `data` (a form for object schemas of simple properties, JSON
  otherwise) and visibility. Validity fields are shown disabled until temporal links (M7). The
  context panel shows the current entity's backlinks: linking entities with the links' labels, and
  mention counts. It refreshes after a save that changes mentions (`affected`).
- **Entity lists** (`/v/$vault/k/$kind`, #65): a table of the kind's entities. Filter by name prefix
  and dimension, and sort. Columns come from the kind's UI config `listColumns`, or else its first
  three short fields, plus dimension and last update. Rows are virtualized (`@tanstack/react-virtual`),
  and pages of 200 load while scrolling, so 10k+ rows stay smooth.
- **Trash** (`/v/$vault/trash`, #65): trashed entities, most recently trashed first, with restore and
  permanent deletion. Children left outside the trash are counted.
- **History** (`core/history/`, #68): the entity page's History tab lists the changesets touching
  the entity, and `/v/$vault/changes` lists the vault's, filterable by origin (`?origin=ui,undo`).
  Opening a changeset loads its row changes and shows them as readable lines (`describeChanges`):
  name, summary and visibility as old → new, field values and field visibility by field label,
  body edits as word counts, trash and restore, parent and dimension by name, aliases, tags, and
  links named by type label and other end; module tables get a generic line. Authors undo a
  changeset from its row. A `409 revert_conflict` is shown in place: "changed again since"
  (`rows`) or the broken rules (`problems`). Undone changesets are struck through, and undos are
  badged. The palette's "Undo the last change" undoes the newest changeset not yet undone.
- **Create flows:** a "New…" menu per kind (and in the command palette), a quick create from
  autocomplete, and "create sub-event here" / "create child" actions.
- Implementation (`core/entities/`, #61): `EntityPage` renders the header (icon, inline rename,
  kind badge, dimension/multiversal and branch-only badges, breadcrumbs loaded up the parent
  chain, aliases and tags as chip editors, a visibility select, "Move to trash") and sections for
  fields, body, relations, time (time-bound kinds) and module `main` panels, with `side` panels in
  a column and a History tab; sections not built yet say which issue fills them. Every edit is a
  PATCH with the entity's revision. Without `Mutations` nothing is editable. The trash dialog
  warns when the entity has children (they stay, shown as roots); a trashed entity's page offers
  Restore and Delete permanently (`?purge=true`). The top bar's "New…" menu lists the kinds that
  aren't system kinds (dimensions, timelines and calendars have their own flows); the create
  dialog takes a name, the dimension (or multiversal, where the kind allows it) and a parent
  among entities of the kind's `allowed_parents`, then opens the new entity.
- Fields (`core/fields/`, #62): zod schemas built from field definitions (`fieldSchema`,
  `fieldsSchema`) mirror `lore.core.fields.values`, so values are checked (and colors lowercased,
  units trimmed) before saving; integers and decimals stay strings. Every core type has a display
  and an editor; `rich_text` is shown by the renderer and edited in the TipTap editor (§6: `[[`
  links, autosave, "Done" closes it; the create dialog asks for a required one as plain
  paragraphs, and lists of rich text are shown but not edited yet), `duration` and
  `time_point` are shown but not editable until M5, and a module's `fieldTypeRenderers` replaces a
  type's display. The fields panel groups by `section` (collapsed sections are remembered per
  kind in `localStorage`), saves text on Enter or blur (multi-line: Ctrl/Cmd+Enter), choices at
  once, clears with an empty value (`null`), shows server field errors under the field, and sets
  per-field visibility overrides. The create dialog (react-hook-form) also asks for the kind's
  required fields.
- Saving and conflicts: `useEntitySaver` sends every change at the entity's revision; `409
  revision_conflict` opens a dialog: **Reload theirs** (drop mine), **Overwrite** (re-read the
  revision and save mine on top) or **Copy mine** (JSON on the clipboard).

## 8. Time components (core)

| Component | Behavior |
|-----------|----------|
| `MomentDisplay` | Formats a moment at a precision in the display calendar (with circa). Tooltip: all calendars of the dimension, absolute value, and "N years before present". |
| `TimePointPicker` | Tabs **Date** (calendar + level-by-level selects from `options()`, precision selector, circa toggle, era selector), **Relative** (target search → event/fact/link/segment slot, edge, offset via `DurationPicker`), **Absolute** (`BigNumberInput`). Calendar and absolute inputs are validated live client-side by the TS engine. Relative previews call `/time/resolve`. |
| `DurationPicker` | Base units, or calendar amounts per level. |
| `EndSpecPicker` | end date / duration / instant / end of time / unknown. |
| `RecurrenceEditor` | Presets plus an advanced builder (freq, interval, filters, selectors, time, limit, exclusions). Natural-language summary, next-10 preview (TS engine). |
| `CalendarEditor` | Structured editor: levels, templates (sequence/uniform), year pattern (fixed/cycle/rules with a predicate builder) plus exceptions, cycles, eras, regimes, overlays, formats. A JSON tab for power users. Live preview: month/year grid for any year, conversion tester, sample formats. Errors come from the TS engine's `compile` (client) and `/calendars/preview` (server). Saving goes through proposals → `ImpactPreviewDialog`. |
| `BigNumberInput` | Arbitrary-size integer input with grouping, `1e100` notation and a unit calculator ("10^100 years × 31,557,600 s"). |
| `TimeCursorControl` | Present / all time / pick / step. Updates `at` in the URL. |
| `ImpactPreviewDialog` | Table of affected records (old/new display, status) with per-row and bulk strategies. Used for calendar proposals and recurrence reconciliation. |

## 9. Timeline view (core)

### 9.1 Layers

`TimeAxis` (ticks/labels from `@lore/chronology` `ticks()`), `EraBands`, `OverlayStrip` (moon
phases etc. once zoomed in enough), `EventLanes`, `SeriesBands`, `DensityStrip` (server buckets
for culled regions), `CursorLine` (draggable as-of cursor), `BranchMarker`s, plus module
`timelineLayers` (e.g. character lifespans, worldline jump arcs). A `Minimap` shows the whole
dimension with density and the viewport rectangle.

### 9.2 Viewport and data

- Viewport math comes **only** from `@lore/chronology/viewport` (bigint-exact). URL keeps
  `from`/`to` (debounced).
- **Tile-based fetching:** zoom level `z = floor(log2(D / span))` (0 when `span ≥ D`). Tiles at
  level `z` split `[0, D]` into `2^z` tiles of `ceil((D + 1) / 2^z)` base units (the last one is
  shorter), computed by `tileFor`/`tileBounds` in `@lore/chronology/viewport`. The visible range
  maps to 1–3 tiles. `/timelines/{id}/window`
  is called per tile with a pixel budget and cached by `(timeline, z, tile index, filters)`, so
  panning reuses tiles and neighbors are prefetched.
- The server applies LOD: items ordered by importance until the pixel budget is met. The rest
  become density buckets. Series that would expand to too many occurrences become bands.
  Buckets carry `starts` (culled events starting there: label "+N", they add up to `culled`) and
  `active` (culled events covering the slice: shade with this, so an era begun before the
  window doesn't pile up at its left edge). Decided 2026-10-07.

### 9.3 Layout and rendering

- Lane packing: greedy interval partitioning by start, **sticky** per entity id across
  pans/zooms, with a minimum label width in pixels. Grouping modes: auto, by category, by
  participant (swimlanes per character), by location, by importance.
- Rendering: React + SVG for items (virtualized to the viewport + margin; target ≤ 1,500 SVG
  nodes). Instants are diamonds. Spans are bars with **fuzzy edges** for coarse precision or circa
  (gradient over the uncertainty extent). Open ends fade out. Occurrences are ticks, and series
  bands are hatched bars with a count. Sub-events expand inline as nested lanes under their parent,
  or "drill in" (viewport = parent span).
- If SVG performance becomes insufficient, switch the item layer to Canvas behind the same
  component API. Measure first (testing.md performance budget: 60 fps pan/zoom with 1,000 visible
  items).

### 9.4 Interaction

Wheel zoom at the cursor, drag to pan, `+`/`-` zoom, `Home` fits the whole dimension, `F` fits
the selection, `G` goes to a date (TimePointPicker). Click selects (preview in the right panel),
double-click opens the page. Double-click on empty space creates an event there, with precision
chosen from the zoom level. Dragging an event's body or edges edits absolute/calendar anchors
(snapping to tick units). Relative-anchored items show a lock and offer to edit the offset
instead. A context menu offers create sub-event, add participant, link cause/effect, and
materialize this occurrence.

### 9.5 Advanced time (M9)

Compare mode stacks lane groups for several timelines (with divergence markers and highlighted
differences). Dimension lanes map another dimension's events through a correspondence (warped
axis, plus a secondary tick row in that dimension's calendar). The worldline layer draws arcs for
jumps of selected entities.

### 9.6 Accessibility

Every visualization has a **list/table alternative** (event outline, link lists). The timeline
supports keyboard navigation between items (arrow keys) and announces focused items.

## 10. Other views

- **Event outline:** tree table (name, start, end, duration, importance, participants), lazily
  expanded; sortable by time.
- **Causality view:** React Flow + elkjs layered layout of cause → effect chains around an event
  (depth control, time-ordered left → right).
- **Graph view (module):** see `docs/modules/graph.md`.
- **Hierarchy views:** location tree, org chart, family tree and language family tree come from
  their modules (React Flow + elkjs where diagrams are needed).

## 11. Design system

- shadcn/ui components live in `src/components/ui` (generated with the shadcn CLI, then owned).
  Theme tokens are CSS variables with light and dark themes (system default, user toggle).
  - Files in `components/ui` stay **byte-identical to upstream** (Prettier ignores that folder),
    so `npx shadcn add <name>` adds components unchanged and `--diff` shows only real changes.
  - The class-name helper is shadcn's `cn` package (Tailwind v4 merging, replaces `clsx` +
    `tailwind-merge`), as upstream components import it. Own code imports it from
    `@/lib/utils`.
  - **Local edit:** `components/ui/sonner.tsx` reads the theme from `@/lib/theme` (Zustand
    store) instead of `next-themes`. Re-adding it with `--overwrite` brings `next-themes` back,
    so reapply the edit.
- Kind colors and icons come from the registry. Icons are lucide names mapped by a curated
  `iconMap`. Custom kinds pick from that set.
- Typography: a UI sans plus an optional serif reading font for bodies in reader mode.
- Accessibility: Radix primitives, visible focus, AA contrast, `?` opens the keyboard shortcut
  sheet.

## 12. Performance rules

- Lazy-load heavy dependencies per route/module: TipTap, sigma, Leaflet, elkjs, React Flow.
- Virtualize long lists and trees.
- Cache compiled calendars in `@lore/chronology` keyed by `(calendar id, definition revision,
  resolved anchors hash)`.
- Graph layout runs in a web worker.
- Budgets (checked in CI with Playwright traces where practical): initial JS < 400 kB gzip for
  the shell, entity page interactive < 300 ms locally, timeline pan/zoom 60 fps at 1,000 items.

## 13. Reader mode and static-export readiness

- `meta.read_only` (or `?as_reader=true` preview) puts the app in reader mode: the `Mutations`
  context is absent, so editing UI does not render. Spoilers fold. The layout is optimized for
  reading.
- Reader screens may only use `DataSource` methods. Post-MVP, `StaticDataSource` implements them
  from JSON chunks of a published snapshot, using `@lore/chronology` for occurrence expansion and
  MiniSearch for search, with hash-based routing (`visibility-and-sharing.md` §6).
