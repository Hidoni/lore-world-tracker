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
editor) opens the keyboard shortcuts sheet. The top bar's dimension switcher and display-calendar
selector are described in §8. API errors become `sonner` toasts
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
- **Events** (`core/events/`, #78): the entity page of an event shows four sections, and its
  relations panel leaves `core.causes` and `core.participant` links to them.
  - **Time:** start and end in the display calendar, each with how it was given ("Typed in
    Gregorian.", a fixed moment, or "3 days after the end of <Coronation>." with the target
    linked; the end as a date, "Lasts 2 months.", an instant, the end of time or unknown).
    The duration comes from the calendar's `diff`, down to the start's display level. A table
    gives start and end in **every** calendar of the dimension. Badges show the timeline (a
    branch is marked), importance, category and recurrence, and a problem status is spelled out.
    "Edit time" opens the event dialog.
  - **Sub-events:** the event's level of the outline (`/event-tree?parent=`), and "Create
    sub-event".
  - **Causes and effects:** causes (links into the event) and effects (out of it) with their
    descriptions, add and remove. "Add a cause/an effect" searches events, then asks for an
    optional description; "Create “…”" opens the event dialog and links the new event. A pair
    named by an open `core.event.effect_before_cause` finding is badged.
  - **Participants:** entities of any kind with their roles; add from search with role
    suggestions (attacker, defender, victim, witness, leader, …), and remove.
  - **Event dialog / form** (`EventForm`): name, dimension and timeline on creation (the
    timeline can't change later), start (`TimePointPicker` with relative anchors), end
    (`EndSpecPicker`), parent event (search), importance 1–5 and category. Server problems with
    the dates show under the fields, or as a cycle or constraint message. The "New…" dialog uses
    the same form for the event kind, since an event needs a start.
- Implementation (`core/entities/`, #61): `EntityPage` renders the header (icon, inline rename,
  kind badge, dimension/multiversal and branch-only badges, breadcrumbs loaded up the parent
  chain, aliases and tags as chip editors, a visibility select, "Move to trash") and sections for
  fields, body, relations, time (time-bound kinds) and module `main` panels, with `side` panels in
  a column and a History tab; sections not built yet say which issue fills them. Every edit is a
  PATCH with the entity's revision. Without `Mutations` nothing is editable. The trash dialog
  warns when the entity has children (they stay, shown as roots); a trashed entity's page offers
  Restore and Delete permanently (`?purge=true`). The top bar's "New…" menu lists the kinds that
  aren't system kinds (dimensions, timelines and calendars have their own flows), then "Dimension…" (the wizard); the create
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
| `MomentDisplay` | Formats a moment at a precision in the display calendar (with circa). Tooltip: all calendars of the dimension, absolute value, and "N years before present". `SpanDisplay` formats a start/end pair (`formatSpan`). |
| `TimePointPicker` | Tabs **Date** (calendar + level-by-level selects from `options()`, precision selector, circa toggle, era selector), **Relative** (target search → event/fact/link/segment slot, edge, offset via `DurationPicker`), **Absolute** (`BigNumberInput`). Calendar and absolute inputs are validated live client-side by the TS engine. Relative previews call `/time/resolve`. |
| `DurationPicker` | Base units, or calendar amounts per level. |
| `EndSpecPicker` | end date / duration / instant / end of time / unknown. |
| `RecurrenceEditor` | Presets plus an advanced builder (freq, interval, filters, selectors, time, limit, exclusions). Natural-language summary, next-10 preview (TS engine). |
| `CalendarEditor` | Structured editor: levels, templates (sequence/uniform), year pattern (fixed/cycle/rules with a predicate builder) plus exceptions, cycles, eras, regimes, overlays, formats. A JSON tab for power users. Live preview: month/year grid for any year, conversion tester, sample formats. Errors come from the TS engine's `compile` (client) and `/calendars/preview` (server). Saving goes through proposals → `ImpactPreviewDialog`. |
| `BigNumberInput` | Arbitrary-size integer input with grouping, `1e100` notation and a unit calculator ("10^100 years × 31,557,600 s"). |
| `TimeCursorControl` | Present / all time / pick / step. Updates `at` in the URL. |
| `ImpactPreviewDialog` | Table of affected records (old/new display, status) with per-row and bulk strategies. Used for calendar proposals and recurrence reconciliation. |

Implementation (`core/time/`, #72):

- **Time context** (`useTimeContext(vault)`, time-model.md §10.6): the dimension is the route's
  (`$dimension`), else the last chosen one (`lore.dimension.<vault>`), else the first. Its
  timeline, cursor and display calendar come from `tl`, `at` and `cal`, else the last used values
  for that vault and dimension (`lore.time.<vault>.<dimension>`, a Zustand store over
  `localStorage`), else the prime timeline, `present` and the default calendar. The cursor is
  `present`, `all` or a moment (`bigint`); `moment` is the present moment for `present` and
  `null` for all time. Setters write the URL (replacing the entry) and remember the value.
- **Top bar:** the dimension switcher lists the dimensions (switching on a dimension route opens
  the new dimension's page; elsewhere it only changes the context) and the display-calendar
  selector lists the dimension's calendars (default first, then by name) and Absolute.
- **Calendars:** `useDimensionCalendars` loads the dimension's calendar entities (their `ext`:
  definition, `definition_revision`, `resolved_anchors`). `compiledCalendar` compiles one with
  `@lore/chronology` (`resolved_anchors` is `CompileContext.resolved`) and caches it by id,
  definition revision, resolved anchors and the dimension's base unit and duration (§12). A
  calendar that doesn't compile is left out of the selector.
- **Formatting:** a moment shows at its precision when the display calendar has that level, else
  at the coarsest level whose unit fits in its extent (the extent given, or the precision's unit
  in the calendar that has it), like the backend's `display_level`. The Absolute calendar uses
  `formatAbsolute`; huge numbers follow `format_integer` (scientific notation). "N years before
  present" counts the display calendar's top level (the default calendar's under Absolute).

Recurrence (`core/events/recurrence/`, #79; recurrence.md §2, §7, §8, §10):

- **`RecurrenceEditor`** (in the event form, under "Repeats"; loaded lazily with the recurrence
  engine). It isn't shown for materialized occurrences, which can't recur.
  - **Presets** are built from the series start (`rule-model.ts`, `presetRule`): every year on
    this date (`select: null`), every month on this day, the nth weekday of the month (a
    continuous cycle at the day level), every week on these days (a cycle's rounds), and every N
    base units. Each has an "every N" step. Opening a series picks the preset its rule matches
    (`detectPreset`; stored defaults are ignored), else Advanced.
  - **Advanced** mode: the period (a level or a continuous cycle) and interval, filters (every
    Nth by number or ordinal, by number or slot, by cycle value; each can be negated), the
    selector path (numbers or slots, cycle values with nth, or every unit), the time-of-day fields,
    "when the position doesn't exist" (skip or constrain), excluded ranges (time points with
    notes), and the rule as JSON for anything the forms don't cover (nested filters).
  - **Ends:** never, after N occurrences, or until a time point (inclusive).
  - **Summary:** in words (`summarize`), e.g. "Every year on the last day of June at hour 9, odd
    years only, until 5 May 1200.".
  - **Preview:** the next 10 occurrences, and the rule's problems (`validateRule`; the
    start-not-an-occurrence warning in amber), both from the TS engine. The series start,
    `until` and exclusions are resolved by the server (`/time/resolve`).
  - **End dates:** a series lasts a duration, so an end date is saved as the base-unit time from
    the start.
- **Saving a rule change** PATCHes the event. The server answers `409` with `context.orphaned`
  when materialized occurrences would lose their key. The form then proposes the change
  (`POST /events/{id}/recurrence/proposals`) and opens **`ReconcileDialog`**:
  - Each customized occurrence with its status (unchanged, moves, no longer an occurrence), its
    date before and after the chosen strategy, and a strategy (move with the rule, re-key, detach,
    trash), defaulting to the server's.
  - Re-keying onto a key another occurrence keeps (it stays, or goes to the trash) blocks Apply.
  - Stale or expired proposals offer "Preview again".
  - After applying, the event's other changed fields are saved, and the toast's Undo reverts the
    "Changed the recurrence" changeset.
- **Occurrences** (a section of a series' page, lazy):
  - Pages of 20 by time. The window end is found with the TS engine on the rule without its end
    and exclusions; the server lists what happens in it, computed and materialized merged.
  - "Earlier" / "Later" / "From the present", and "Show cancelled".
  - Numbers ("58th") and states (customized, moved, cancelled).
  - Per occurrence: Open (materializes it), Modify time (the event dialog on the occurrence),
    Add sub-event, Add note (its page), Cancel / Restore (`ext.cancelled`), and Revert for a
    customized one (`DELETE …/occurrences/{key}`; with sub-events it asks before trashing them).
- **`OccurrenceHeader`** on a materialized occurrence's page: "Occurrence #58 of <series>" with
  its state, and the series' field values it doesn't set ("from the series"). Its participants
  section also lists the series' participants.

Calendar editor (`core/time/calendar-editor/`, #76, #77):

- **Routes:**
  - `/v/$vault/calendars/$calendar/edit`.
  - `/v/$vault/calendars/new?dimension=<id>`, which starts blank (a 360-day year) or from a preset
    instantiated in seconds. It is opened from the dimension overview.
  - Both load the editor lazily, as its own chunk.
- **Structure tab:** the definition is edited as a document (`edit(definition, recipe)` copies,
  then changes the copy). Renaming a level or a template updates every reference to it (templates,
  alignment and cycle fields, cycle levels, format keys and their tokens, the dates and
  precisions of time points in the definition).
  - Levels, coarse to fine: id, label, plural and abbreviation; the first number and the default
    template (below the top); add a level below, move, remove.
  - Templates by level: uniform (a count of a child template, or base units at level 0) or a
    sequence of named units (slot id, name, abbreviation, template, intercalary) and numbered
    runs. A slot id used by more than one template is highlighted, since it keeps typed dates
    across templates.
  - Years: the rules' id and name, then the pattern. A pattern is fixed, a cycle with its
    starting year, or rules whose predicate builder combines `mod`/`eq` with all/any/not and
    has a default. Exceptions per year.
  - Rules and reforms (#77): one tab per regime. "Reform" copies the selected regime to a new
    one starting at a date of this calendar; templates, years, alignment and cycles below edit
    the selected regime.
  - Alignment: fields from the year down, and the moment they begin at (a moment, or another
    time point of the dimension through the `TimePointPicker`).
  - Cycles (#77): id, level, length, first number, names/abbreviations/ids as comma lists,
    continuous or restarting at a coarser level, the anchor (fields and index) or "continues
    from the previous rules" in a reform. Exclusions are template flags ("Skips <cycle>" on a
    template's units) and are listed per cycle.
  - Eras (#77): an ordered list (move, remove, add) with name, abbreviation and its position,
    counting direction and first number; every era after the first starts at a time point
    (`DefinitionPointField`: a date of this calendar, a moment, or another time point,
    including event anchors).
  - Overlays (#77): period as an exact fraction of base units with an "in days" helper (from the
    first day's length), epoch, and phases by fraction of the period.
  - Formats (#77): a pattern per level (empty: the generated default), tokens suggested after an
    unclosed `{` (`tokensFor`), a live sample at a chosen moment, and optional intercalary
    patterns. Display options: circa prefix, digit grouping, scientific threshold, significant
    digits, range separator.
- **JSON tab:** the same document as text. Each valid parse replaces the draft, and a parse
  error blocks saving.
- **Preview:** the TS engine (`validateCalendar`) checks every change. Absolute anchors are
  resolved with `absoluteMoments`, others reuse the stored `resolved_anchors`. A new non-absolute
  anchor (`anchor.unresolved`) is resolved by the server on save and doesn't block it.
  - Problems are listed in words with their JSON pointer, and clicking one focuses its field
    (`data-path`). The problems also appear under the fields they belong to.
  - The year grid shows any year's units and their lengths (`options()`).
  - The converter has a `TimePointPicker` on the draft calendar for date → moment, and a
    `BigNumberInput` for moment → date.
- **Saving** (#77, time-model.md §7.4, D1):
  - An existing calendar is saved through a proposal (`POST /calendars/{id}/proposals`). With no
    items and no series it is applied at once; otherwise `ImpactPreviewDialog` opens.
  - `ImpactPreviewDialog` (`core/time/impact-preview.tsx`) shows the summary counts and a table
    of the items: record (linked), the date now, the date after for the chosen strategy (or the
    problem), and a strategy per row (`keep_date`, `pin_moment`, `constrain` where offered).
    Rows without a problem default to `keep_date`. Rows with a problem start undecided, and
    Apply waits until each has a choice: an explicit `keep_date` accepts the problem. The bulk
    actions are "Keep all dates" (which leaves broken rows alone) and "Keep all moments". Series
    whose bounds move are listed.
  - Apply sends the explicit strategies. On success a toast offers Undo, which reverts the
    newest unreverted "Edited the calendar" changeset. A `409 proposal_stale` or a `404` (the
    proposal expired) shows "Preview again", which proposes the same definition again. A
    `422 proposal_unresolved` shows its messages on their rows.
  - A new calendar is created with `POST /entities` (`kind: calendar`, `dimension_id`,
    `ext.definition`), then the editor opens.

Dimensions (`core/time/`, `core/shell/vault-home.tsx`, #75):

- **Vault home** (`/v/$vault`): the dimensions (links to their overview), "Create dimension"
  (for authors; a call to action when there are none), the pinned entities, and a link to
  recent changes.
- **`DimensionWizard`** (a dialog from the vault home and the "New…" menu), in five steps:
  1. Name and description.
  2. Base unit: its names and abbreviation, and how long it lasts (`num / den` seconds, which
     presets use).
  3. Duration `D`: a `BigNumberInput` with lifetimes to start from (10,000 years, 13.8 billion
     years, 10^100 years of 365.25 days), converted to base units.
  4. First calendar: a preset from `/calendars/presets`, its name, and "Year 1 begins at" (the
     preset's `origin`). It is previewed live with `/calendars/preview`. The wizard also checks
     that `D` reaches the preset's absolute anchors (`origin + duration_seconds` in base units),
     which the server would otherwise report as a compile error.
  5. Review.

  Creating sends `POST /dimensions` and opens the new dimension. Server problems are listed with
  a link back to their step.
- **`DimensionOverview`** (`/v/$vault/d/$dimension`):
  - Time: the base unit, and `D`, which can be changed. A `422 time_constraint` (R-DIM-3) shows
    its reason and names the records in the way.
  - The present: set, changed or cleared with a `TimePointPicker`.
  - Calendars: the default first, with "Make default" and links to the editor.
  - Timelines: the prime timeline and its branches.
  - Statistics: the event count, shown as "500+" past one page, and the calendar count.
  - Recent events: the five most recently updated.

Time inputs (`core/time/`, #73):

- **`BigNumberInput`:** reads digits with any grouping (`,`, spaces, `'`, `_`), exponents
  (`1e100`, `3.17e99`), powers (`10^100`) and products of factors with unit labels as a calculator
  (`10^100 years × 31,557,600 s`, `parseBigNumber`). The result must be whole and at most 1000
  digits, and non-negative unless `signed`. Optional `min`/`max` bounds are checked too. Below
  the input it shows the parsed value (scientific notation and the digit count when long) or the
  problem. On blur, plain numbers are rewritten grouped. Enter calls `onConfirm`.
- **`TimePointPicker`:**
  - **Date tab:** pick a calendar, an era (or none: astronomical years) and a precision. Levels
    finer than the precision are hidden. The top level is typed (any size). Each lower level
    offers `options()` for its chosen parents: named units are listed by slot id, so an odd
    year offers its own months, and ranges become choices, or a number input past 1000 units.
    A unit the parents no longer allow falls back to the first valid one.
  - **Reform dates:** an ambiguous date across a reform shows a "Calendar rules" (regime)
    select.
  - **Absolute tab:** base units, bounded by the dimension's duration.
  - **Both tabs:** a circa toggle, and a preview of the date in the display calendar and the
    moment.
  - **Output:** the picker reports a `TimePoint` only when the engine accepts it (`fromFields`
    with `overflow: 'reject'`), else `null`. Era dates keep the era-relative year with `era`.
    Enter on a field confirms.
  - **Relative tab** (with `vault`, authors only, #74):
    - Finds the target by name (quick search in the dimension) among the record types in the
      registry's `referenceable_slots` that are entity kinds (events and timelines today).
    - Picks the edge (slot), an occurrence key for a recurring event (empty means the series),
      an offset (`DurationPicker`, zero by default) and a precision. The precision defaults to
      **Default**: the picker resolves once at an explicit precision to learn
      `default_precision`, then stores that and resolves the final point for the preview.
    - Problems from `/time/resolve` (an unset, purged or hidden target, a cycle, out of bounds)
      show inline, and a reference to the picker's own slot (`owner`) is refused. Only a
      resolvable anchor is reported.
- **`EndSpecPicker`:** an end date (a nested `TimePointPicker`), a duration after the start,
  instant, end of time or unknown. With a `start`, the server resolves both, and an end before
  the start is refused with the reason (`/time/resolve` doesn't flag it). `timeWriteProblem`
  turns a save's `409 time_cycle` (its path) and `422 time_constraint` into plain words for
  forms.
- **`DurationPicker`:** a sign, then base units or amounts per level of one of the dimension's
  calendars. It reports `{kind: 'base', units}` (signed) or `{kind: 'calendar', amounts, sign}`.

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
  - Implementation (`EventOutline`, `/v/$vault/d/$dimension/events`, #78): the time context's
    timeline (a select when the dimension has branches), one `event-tree` level per expanded row,
    page by page ("Show more"), ordered by start (the server's order). Start and end are the
    server's displays (the dimension's default calendar). The duration is measured in the display
    calendar down to days (or its finest level), and the participant count is the server's
    (participants the request sees). It is an ARIA `treegrid`: ↑/↓ move, → expands or enters,
    ← collapses or goes to the parent, Home/End jump, Enter opens the event. "New event" opens the
    event dialog. The dimension overview and the command palette link to it.
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
