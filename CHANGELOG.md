# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Releases happen at the milestones listed in
`docs/plan/roadmap.md` (the first is v0.1.0, at the end of M2).

## [Unreleased]

### Added

- **Calendar editor I** (#76): build a calendar without JSON. You edit its levels, its templates
  (uniform, or named and numbered units, with shared slot ids highlighted), its years (fixed,
  cycle, or rules with a predicate builder, plus exceptions) and its alignment. A JSON tab and a
  live preview by the TS engine sit alongside: problems focus their field, there is a year grid
  and a converter. New calendars start blank or from a preset. A calendar that nothing depends
  on saves directly.
- **Dimension wizard and overview** (#75): the vault home lists dimensions with "Create dimension";
  a five-step wizard (name, base unit, duration with lifetime presets, first calendar from a
  preset with a live preview, review) creates a dimension with its prime timeline and default
  calendar; the dimension overview shows and edits its duration (explaining what blocks a
  shrink), present moment and default calendar, with timelines, counts and recent events.
- **Relative anchors and end specs** (#74): the time point picker's Relative tab (target search,
  edge, occurrence key, offset, live server resolution with the resulting precision, problems
  inline) and `EndSpecPicker` (end date, duration, instant, end of time, unknown; an end before
  the start is refused). `GET /registry` lists `referenceable_slots`, and `/time/resolve` items
  carry `default_precision`.
- **Time inputs** (#73): `BigNumberInput` (grouping, `1e100`, powers, a unit calculator like
  `10^100 years × 31,557,600 s`), `TimePointPicker` (Date tab driven by the calendar's valid
  units per parent, eras, precision, circa, live preview; Absolute tab bounded by the dimension)
  and `DurationPicker` (base units or calendar amounts, with a sign).
- **Consistency UI** (#85): the findings panel (filters for severity, certainty, rule, owner,
  entity and timeline, kept in the URL; explain; suppress with a note; re-check the vault),
  finding badges on entity headers and sidebar trees, Settings → Consistency with rule severities
  (hard rules locked), and a "Save anyway (intentional)" dialog for every write that consistency
  rules refuse.
- **Time display and context** (#72): every moment can be shown in the chosen display calendar
  (`MomentDisplay`, `SpanDisplay`), with a tooltip listing it in all the dimension's calendars,
  the absolute value and its distance from the present; huge years use scientific notation. The
  top bar has a dimension switcher and a display-calendar selector (with Absolute); the
  dimension, timeline, cursor and calendar live in the URL (`tl`, `at`, `cal`) and are
  remembered per vault and dimension. Calendars compile client-side with `@lore/chronology` and
  are cached by id, revision and resolved anchors.

## [0.3.0] - 2026-10-11

The frontend foundation (M4): a generic wiki usable in the browser. Every kind has an entity page
with fields, a rich-text body with entity links, relations, backlinks and history; the sidebar,
command palette and search find things; settings cover modules, link types and backups. The
editor-linking journey (E5) runs end to end.

### Added

- **Frontend data layer** (#59): `DataSource` (every read, static-export ready) and `Mutations`
  (author-only) over the HTTP API, with hooks for vaults, entities, trees, links, search and
  history, query keys and `invalidateAffected`. Resolved moments are `bigint` in the UI: `make
  gen` brands them `MomentString` and records where they sit (`moments.gen.ts`), and the
  `lore/no-number-moment` lint rule keeps them out of JS numbers.
- **Frontend module framework and KindRegistry** (#60): `defineModule` with typed extension points
  (kinds, routes, nav sections, entity panels, renderers, timeline layers, graph styles, editor
  extensions, commands, settings pages, header media), activation per vault from `GET /registry`
  (dependencies included), lazily loaded module routes, and the KindRegistry merging server kinds
  and link types with module UI configs (`useKind`, `useLinkType`, curated `iconMap`).
- **Entity page and create/trash flows** (#61): one page for every kind (header with inline rename,
  badges, breadcrumbs, aliases, tags and visibility; slots for fields, body, relations, time and
  module panels), a "New…" menu with a create dialog (dimension or multiversal, allowed parents),
  and move to trash, restore and permanent deletion.
- **Renames relabel links** (#70): renaming an entity updates the link text that read its old name
  in other entities' bodies and rich-text fields, in the same undoable change; custom labels stay.
- **E2E harness and journey E5** (#70): a fresh vault per test with API setup helpers, traces on
  failure, and the editor-linking journey (`[[` link, backlink, rename).
- **Rich-text fields use the editor** (#259): the fields panel shows `rich_text` fields with the
  renderer (entity links with kind icons) and edits them in the TipTap editor, so links and other
  marks survive a save.
- **Settings UI** (#69): vault name, default visibility and theme; module toggles that confirm
  the dependencies or dependents they switch too; custom link types (create, edit, archive,
  delete) next to the built-in ones; backups with the private-data notice, downloads, a schedule
  and restore with upload progress; module settings pages in the settings navigation.
- **History UI** (#68): an entity History tab and a recent changes page (filterable by origin)
  with readable diffs and undo, showing why an undo was refused; "Undo the last change" in the
  palette. `GET /changes` takes `origin` filters.
- **Command palette and search** (#67): `Ctrl/Cmd+K` opens a palette with recent entities, a quick
  switcher and commands (new entity, go to a dimension, its timeline or a page, theme, shortcuts,
  module commands). The search page has kind and dimension filters, highlighted snippets and
  module result renderers. `?` lists the keyboard shortcuts.
- **Rich-text editor II** (#64):
  - Spoiler and private blocks with labels, and callouts in three tones, shown framed in the
    editor; spoilers fold for readers.
  - A slash menu with every block type, including module ones.
  - Markdown paste that turns `[[Name]]` into entity links when the name is unique.
- **Links UI** (#66):
  - Relations panel: links grouped by type with labels from the entity's side, roles, details and
    visibility, with edit and remove.
  - Add-link dialog: target search, the link types that fit both kinds (either direction), role,
    details from the type's schema, and visibility.
  - Backlinks and mentions in the context panel.
- **Navigation** (#65):
  - Sidebar: a lazily loaded tree per kind, with multiversal badges. Drag and drop moves an entity
    to an allowed parent, by mouse or keyboard. A context menu offers new child, rename, pin and
    move to trash. Pinned and recently visited entities are kept per vault.
  - Entity lists per kind: virtualized, with name and dimension filters, sorting, and columns from
    the kind's UI config.
  - Trash page: restore, or delete permanently.
- **Rich-text editor** (#63): the body editor (TipTap, loaded lazily) with headings, lists,
  quotes, code, tables, links, markdown shortcuts and a word count. Typing `[[` or `@` links an
  entity, or creates it first. It autosaves after a pause, on blur and when you leave the page,
  and shows its save status. Readers see the read-only renderer: links carry their kind icon and a
  hover card, and missing targets render as plain text. Writes now report the entities whose
  mentions changed, so their backlinks refresh.
- **Field editors** (#62): display and inline editors for every core field type, checked against
  zod schemas built from the field definitions, saved on Enter or blur, with per-field
  visibility, collapsible sections, required fields in the create dialog, module field
  renderers, and a revision-conflict dialog (reload theirs, overwrite, copy mine).
- The golden fixture vault `v0.3.0`.

## [0.2.0] - 2026-10-11

The time core (M3): the full time model is usable through the API, from a dimension's inception
to its end, at cosmic scales and within the performance budgets on the `large` sample world. The
release also carries the first piece of M4, the app shell and vault picker.

### Added

- **M3 Time core** (#44–#56):
  - Time specs on records with a slot registry and the `time_dependencies` graph; dimensions
    and prime timelines (time spec, duration limits, present moment).
  - Calendars: storage, compilation cache, presets, preview endpoints and the dimension wizard.
  - Anchor resolution (absolute, calendar, relative with calendar offsets, occurrence refs) and
    the `/time` endpoints; dependency propagation with cycle rejection, topological
    re-resolution, hard checks and anchor freezing.
  - `TimelineView` (lineage visibility and override resolution for time-bound tables).
  - Events: CRUD with time specs, sub-events, causality, participants and the event tree; the
    timeline window API (overlap queries, importance-based level of detail, density buckets).
  - Recurring series (rule validation, cached series bounds, occurrence expansion in windows)
    and materialized occurrences (materialize, modify, cancel, occurrence anchors, sub-events).
  - Proposals with impact previews: calendar edits (keep dates / pin / constrain) and
    recurrence-rule reconciliation (keep key / rekey / detach / trash).
  - The consistency engine: findings and suppressions API, precision-aware comparisons, core
    structural and event rules, and checks on every changeset.
  - The sample world generator writes time data (`make sample-vault`), and `make perf` checks
    the backend budgets on the `large` world.
  - The golden fixture vault `v0.2.0`.
- **App shell and vault picker** (#58): the SPA's frame (top bar, resizable and collapsible
  sidebar, context panel, mobile drawer), every route of `frontend.md` §4 (placeholders until
  their pages land), light/dark/system themes, per-route error boundaries, toasts for API errors,
  and a vault picker to create, rename and move vaults to the trash that reopens the last vault.

### Changed

- **Write responses report what moved** (#224): `affected.entities` lists every entity whose
  stored moment or time status the write changed through propagation (the events anchored to a
  moved event, the dates of an edited calendar, …), `affected.dimensions` their dimensions, and
  `affected.time_changed` is `true` when any moment or status changed (it was always `false`).
- **Large vaults** (#235–#238), measured on the `large` sample world (100k events, 500k links):
  - Timeline windows: cold windows take 20–100 ms zoomed in and about 330 ms over the whole
    dimension (were 250 ms to 5 s; readers were slowest). Series are looked up through their
    index and their occurrences remembered, sub-event markers cost one probe per event, and a
    reader's window asks what is visible once.
  - Consistency: a full scan takes 8 s (was more than 15 minutes), enabling the duplicate-name
    rule under a second (was 28 minutes), and a write's check no longer grows with the vault.
    Writing a link costs 1.2 ms (was 10 ms): it only re-checks rules about its link type.
  - Calendar proposals: preview under 5 s (was 9 s), apply 22 s (was 2 minutes; the budget
    for an apply on a vault this large is now 30 s). The backup
    taken before a large apply is deflated at the fastest level.
  - A full garbage collection no longer stalls about one request in ten for 85 ms.
  - Series bounds of a far count limit (`count` 10^12 on a yearly rule) take about 5 ms (were
    90 ms, close to their 100 ms budget): both engines go to the super-period counter after 64
    enumerated periods instead of 10,000 (#247).

### Fixed

- A materialized occurrence kept on its key through a recurrence change (`keep_key`, or a direct
  edit that moves it) takes the key's new start as `original_start_t`, so later proposals report
  it as `moved` only when they move it (#230).
- A modified occurrence anchored to its own occurrence ("two days after occurrence 4", said by
  occurrence 4) resolves against the computed occurrence (#234). It used to resolve against its
  own stored moment: `lore vault check` reported `time_moment_stale` and every re-resolution
  moved it again.
- SQL compiled with literal binds renders moments quoted once (`'00015'`, was `'''00015'''`),
  so such statements compare against the right key (#222).
- Pinning an item a calendar edit broke without moving it no longer makes the proposal apply
  answer `409 proposal_stale` (#233).

## [0.1.0] - 2026-10-05

The first release that writes vaults: the core platform (M2) on top of the foundations (M0) and
the chronology engine (M1). It has no UI for worlds yet (M4); everything is reachable through the
`/api/v1` API and the `lore` CLI.

### Added

- **M0 Foundations** (#1–#7, #167):
  - Backend scaffold: FastAPI app factory, `LORE_*` settings, `lore` CLI (`serve`, `openapi`),
    `/api/v1/health` and `/api/v1/meta`, structured logging with request ids.
  - HTTP hardening: Host allowlist, mutation guard (`X-Lore-Client`, `Origin`), security headers
    and CSP, request size limits, problem+json errors.
  - Frontend workspaces: `@lore/web` SPA shell (React, TanStack Router/Query, Tailwind, shadcn)
    and the `@lore/chronology` package skeleton.
  - API contract pipeline: OpenAPI → generated TypeScript types, typed client, drift check.
  - Makefile entry point, dev orchestration (`make dev`), GitHub Actions CI (backend, frontend,
    contract, chronology, e2e, docker) and Dependabot.
  - Multi-stage Docker image and `docker-compose.yml` (author instance on `127.0.0.1:8080`).
- **M1 Chronology engine** (#8–#29):
  - The time engine in Python (`lore.chronology`) and TypeScript (`@lore/chronology`), sharing one
    spec, exported JSON Schemas and conformance vectors that both engines pass.
  - Calendars: definition validation and compilation, moment ⇄ fields conversions, unit bounds,
    ordinals and picker options, parallel cycles (weeks), intercalary units, eras, regimes
    (calendar reforms) and local anchors, astronomical overlays (moons, seasons).
  - Calendar arithmetic (add with constrain/reject, diff by largest unit) and formatting
    (patterns, defaults, intercalary formats, spans, large numbers).
  - Calendar preset library with base-unit scaling.
  - Recurrence rules: intervals, calendar rules, filters and selectors, cycle frequencies,
    counts, exclusions, occurrence numbers and window expansion without bulk storage.
  - Correspondence mapping between dimensions.
  - Timeline viewport math, calendar-aware ticks and tiles.
  - Cross-engine differential fuzzing (`make test-differential`) and benchmarks (`make bench`).
- **M2 Core platform** (#30–#43):
  - Vaults: a data directory of vault folders (`vault.json` + one SQLite database each), with a
    registry, per-vault locks and engines, and the vault API and `lore vault` CLI.
  - Migrations: per-vault Alembic upgrades on open with an automatic pre-migration backup,
    `lore vault migrate` and `lore db check`/`revision` tooling.
  - Core schema v1 (entities, aliases, tags, links, link types, mentions) with exact sortable
    integers and UUIDv7 ids.
  - The backend module framework: module specs, registries of kinds, fields and link types,
    per-vault module enablement.
  - Entities: create, read, update, trash, restore and purge with parent rules and optimistic
    concurrency; listing, the navigation tree, children, the trash and field value suggestions.
  - Links: core and custom link types, link CRUD, per-entity links and backlinks.
  - History: every write is a changeset; the recent changes feed, per-entity history and undo.
  - Rich text: document validation, text and mention extraction, mentions and reader filtering.
  - Search: FTS5 full-text search (incl. trigram matching) and the quick switcher, kept current in
    the write transaction, with reindexing.
  - Visibility: author and reader policies (public, spoiler, private), `?as_reader=true` previews
    and the canary leak-test harness.
  - Backups: manual zip backups, scheduled backups with retention, and restore into a new vault.
  - Maintenance: `lore vault check` (integrity, foreign keys, derived data), `reindex` and
    `optimize`, plus a daily `PRAGMA optimize`.
  - The sample world generator (`make sample-vault SIZE=tiny|small|medium|large`) and the first
    golden fixture vault, which every later migration is tested against.

[Unreleased]: https://github.com/Hidoni/lore-world-tracker/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Hidoni/lore-world-tracker/releases/tag/v0.1.0
