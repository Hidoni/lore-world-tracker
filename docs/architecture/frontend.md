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

## 4. Routing

Code-based TanStack Router tree assembled in `app/` from core routes plus module route factories.

```
/                                       vault picker (redirects to last-opened vault)
/v/$vault                               vault home: dimensions, recent changes, pinned
/v/$vault/d/$dimension                  dimension overview: time spec, calendars, timelines, stats
/v/$vault/d/$dimension/timeline         timeline view
/v/$vault/d/$dimension/events           event outline (tree table)
/v/$vault/e/$entity                     entity page (any kind; `?tab=` for module tabs)
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
  `@lore/chronology`. ESLint forbids `Number(` and `parseInt(` on fields typed as moment strings
  via a custom lint rule or code review checklist (see CLAUDE.md).
- **Invalidation:** every write response includes
  `affected: {entities: id[], dimensions: id[], time_changed: bool, search_changed: bool}`. A
  central `invalidateAffected()` maps that to query keys (entity, lists, tree, backlinks, windows
  of affected dimensions…).
- **Query keys:** `[vault, area, id?, params?]`, defined in `data/keys.ts` only.
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

## 7. Registry-driven entity UI

- On vault open, `GET /registry` is merged with module UI configs into the **KindRegistry**
  (labels, icons, colors, fields, allowed parents, link types, panels).
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
- **Create flows:** a "New…" menu per kind (and in the command palette), a quick create from
  autocomplete, and "create sub-event here" / "create child" actions.

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
- **Tile-based fetching:** zoom level `z = floor(log2(D / span))`. Tiles at level `z` have size
  `D / 2^z` (+ remainder handling). The visible range maps to 1–3 tiles. `/timelines/{id}/window`
  is called per tile with a pixel budget and cached by `(timeline, z, tile index, filters)`, so
  panning reuses tiles and neighbors are prefetched.
- The server applies LOD: items ordered by importance until the pixel budget is met. The rest
  become density buckets. Series that would expand to too many occurrences become bands.

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
