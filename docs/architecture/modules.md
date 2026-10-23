# Module system

> The brief asks for every non-core feature to be designed "as if [it is] in togglable modules"
> that "might be expanded upon or removed in the future". This document defines what a module is,
> how it plugs into both tiers, what toggling does, and which features are core vs modules.

## 1. Core vs modules

**Core** (always on, cannot be disabled):

- vaults, settings, backups, read-only mode, security
- entities, fields, links (incl. user-defined link types), facts/existence, aliases, tags
- dimensions, timelines (data model + `TimelineView`), calendars, time points, propagation,
  events (incl. sub-events, causality, participants, recurrence and materialized occurrences)
- the chronology engines
- rich text + mentions/backlinks, search, history/undo, visibility, consistency framework and core
  rules
- frontend shell, navigation, entity pages, editor, command palette, timeline view, causality and
  event-outline views, settings UI

**Modules** (toggleable per vault; the ids are used on both tiers):

| Module id | Provides | Depends on | Default |
|-----------|----------|------------|---------|
| `misc` | kind `misc` (category; parent of anything) | – | on |
| `locations` | kind `location`; spatial link types; location tree view | – | on |
| `species` | kind `species`; descent/origin link types | – | on |
| `characters` | kind `character`; relationship link types; relationship + family-tree views | – | on |
| `groups` | kind `group`; membership/relations/territory link types; org chart | – | on |
| `languages` | kinds `language`, `writing_system`; lexicon; language family view | – | on |
| `media` | uploads, media library, image nodes, covers, galleries | – | on |
| `maps` | image maps on locations, pins and regions, drill-down, time-aware pins | `locations`, `media` | on |
| `scripts` | writing systems' fonts: headwords and samples in the conlang's script | `languages`, `media` | on |
| `custom_fields` | custom fields on any kind, custom kinds, relation-field sugar | – | on |
| `graph` | global graph view + local graph panel | – | on |
| `branches` | alternate-timeline UI/API (create branches, overrides, comparison) | – | on |
| `correspondences` | cross-dimension correspondences UI/API, concurrent-time display | – | on |
| `worldlines` | personal timelines (segments, subjective time, personal timeline view) | – | on |

Notes:

- `branches`, `correspondences` and `worldlines` are modules over **core data structures**.
  Timeline awareness, override resolution and the slot registry are core because every time query
  depends on them. The modules own the APIs, UI and module-specific consistency rules. Disabling
  `branches` hides branch timelines (data preserved). Disabling `worldlines` falls back to implicit
  worldlines.
- Cross-module link types live in the module that owns the **semantics**. For example,
  `groups.controls` (group → location) belongs to `groups` and requires `locations` to be enabled
  to be offered. A link type whose source/target kinds are unavailable is hidden.
- Future modules (post-MVP): `static_export`, `markdown_export`, `json_io`, `mcp` (AI access to
  the vault), `territories` (map regions over time), `scripts` (custom fonts for writing systems).

## 2. Backend module anatomy

```
backend/src/lore/modules/<id>/
  __init__.py
  module.py        # MODULE = ModuleSpec(...)
  kinds.py         # KindDef(s) and FieldDef(s)
  links.py         # LinkTypeDef(s)
  models.py        # SQLAlchemy models for module tables (if any; prefixed table names)
  schemas.py       # Pydantic API schemas
  service.py       # business logic
  router.py        # APIRouter mounted at /api/v1/vaults/{vault_id}/m/<id>/
  rules.py         # consistency rules
  search.py        # search contributors (optional)
  api.py           # PUBLIC API for dependent modules (the only file other modules may import)
```

### 2.1 `ModuleSpec`

```python
@dataclass(frozen=True)
class ModuleSpec:
    id: str                                   # ^[a-z][a-z0-9_]*$
    name: str
    description: str
    depends_on: tuple[str, ...] = ()
    default_enabled: bool = True
    kinds: tuple[KindDef, ...] = ()
    field_contributions: tuple[FieldContribution, ...] = ()   # fields added to other modules' kinds
    field_types: tuple[FieldTypeDef, ...] = ()                # extra field value types (media: "media")
    field_providers: tuple[FieldProvider, ...] = ()           # fields kept in the vault DB (custom_fields)
    kind_providers: tuple[KindProvider, ...] = ()             # kinds kept in the vault DB (custom kinds)
    link_types: tuple[LinkTypeDef, ...] = ()                  # keys must start with "<id>."
    models: tuple[type, ...] = ()                             # ORM classes of the module's tables ("<id>_…")
    history_tables: tuple[HistoryTable, ...] = ()            # how history treats each table (all must be listed)
    routers: tuple[APIRouter, ...] = ()
    slot_providers: tuple[SlotProvider, ...] = ()             # module records with time slots
    timeline_tables: tuple[TimelineTableSpec, ...] = ()       # module tables readable through TimelineView
    search_contributors: tuple[SearchContributor, ...] = ()
    graph_contributors: tuple[GraphContributor, ...] = ()
    consistency_rules: tuple[RuleDef, ...] = ()               # ids must start with "<id>."
    visibility_filters: tuple[VisibilityFilter, ...] = ()     # how module rows are filtered for readers
    richtext_nodes: tuple[RichTextNodeHandler, ...] = ()      # extraction/filtering for module node types
    backup_contributors: tuple[BackupContributor, ...] = ()   # extra files (e.g. media blobs)
    publish_contributors: tuple[PublishContributor, ...] = () # how to sanitize module data in published snapshots
    markdown_contributors: tuple[MarkdownContributor, ...] = () # files and renderers for the Markdown export
    interchange_tables: tuple[InterchangeTable, ...] = ()       # keys and files of its tables in interchange files
    static_reads: tuple[StaticRead, ...] = ()            # reads a static export records (ADR 0016)
    static_data: StaticData | None = None                # data a static export computes views from
    kind_extensions: tuple[KindExtension, ...] = ()           # `ext` data of a kind (one per kind)
    purge_hooks: tuple[PurgeHook, ...] = ()                   # run before any entity is purged
    derived_hooks: tuple[DerivedHook, ...] = ()               # rebuild derived rows on every changeset
    maintenance_tasks: tuple[MaintenanceTask, ...] = ()       # daily, per open vault (author mode)
    derived_checks: tuple[DerivedDataCheck, ...] = ()         # extra `lore vault check`/`reindex` checks
    settings_model: type[BaseModel] | None = None
    on_enable: Callable[[VaultContext], None] | None = None
    on_disable: Callable[[VaultContext], None] | None = None
```

Implementation: `lore.core.modules.ModuleSpec`. The definition types (`KindDef`, `FieldDef`,
`FieldContribution`, `FieldTypeDef`, `LinkTypeDef`, `RuleDef`) live in `lore.core.registry`, which
also holds core's own definitions (the field types of `data-model.md` §4.2, kinds `dimension`,
`timeline`, `calendar`, `event`, and link types `core.participant`, `core.causes`,
`core.related`). `slot_providers` are `lore.core.time.SlotProvider(record_type, model, slots,
…)` (`time-model.md` §6; record types `<module id>.<type>`, models among the module's `models`).
Extension points whose machinery comes later (timeline tables, graph,
backup contributors) are accepted and stored as opaque objects
until their issue defines the protocol. `publish_contributors` (#140) are
`(PublishContext) -> None` (`lore.core.vaults.publish`): they run inside the publish sanitizer's
transaction on the snapshot's copy (`context`: its session, as a reader would see it), after core
has deleted what readers can't see, and remove or copy what core can't know about (the media
module copies the files of the items readers see from `source` into `target`; maps drop the maps
readers can't see). A module table with a `visibility` or `deleted_at` column loses its private
and trashed rows without help, and rows whose references were deleted go with them.
`interchange_tables` (#149) are `lore.core.interchange.spec.InterchangeTable`s: how a module's
table travels in interchange files beyond its rows (`interchange.md` §5): `reuse_by_key` (a row
whose unique key the target vault has is that row) and the `file`/`store` of rows with files
(media). Every table in `history_tables` is exported without declaring anything.
`markdown_contributors` (#148) are `(MarkdownExport) -> None` (`lore.core.markdown.export`): the
enabled modules' contributors run once per Markdown export, before any note is written, with the
vault read under the export's policy; they copy files into the export (`claim` a path, then
`sink.copy`) and register how their rich-text nodes, field types and covers render
(`markdown-export.md` §5). `static_reads` (#376) are `lore.core.modules.StaticRead`s: the
reads of the module's routes a static export records (`visibility-and-sharing.md` §8), for each
id (entities of a `kind`, or the items of another read: `ids_from`), each query the app sends
(`variants`), and optionally each dimension, timeline and as-of moment; `paged` lists are
recorded whole for the browser to filter and page, `file` reads (downloads) are copied. A
reader-facing read with free parameters the browser can't derive from these needs its own
handler (`frontend/src/data/static-modules.ts`). When recording each setting would multiply, a
module exports the data the browser computes the view from instead: `static_data` (#386) is
`(VaultContext, VisibilityPolicy, moments by timeline) -> {name: JSON}`, written to
`static/m/<module>/<name>` (characters: family links and lifespans; graph: links with their
validity per timeline, and mentions), and a handler ports the view. `derived_hooks` (#126) are
`(VaultContext, Sequence[RecordedChange]) -> None`: the enabled modules' hooks run with the
changes each changeset is about to record, before the consistency check, for every writer and
undo, to rebuild derived rows (the media module's `media_refs`); raising a typed error refuses the
write. `maintenance_tasks` are `(VaultContext, now) -> None`, run once a day per open vault in
author mode by the scheduler, in one write transaction (media garbage collection).
`derived_checks` are `lore.core.maintenance.DerivedDataCheck`s that `lore vault check` and
`lore vault reindex` run after core's, for the enabled modules. `search_contributors` are
`lore.core.search.SearchContributor(doc_type, documents, label, icon)`; `visibility_filters` are
`lore.core.visibility.VisibilityFilter(model, visibility_column, entity_columns)`
(`visibility-and-sharing.md` §3): `doc_type` is
`<module id>.<type>` (unique, not a kind key), and `documents(context, ids)` returns the current
`SearchDocument`s with these ids (every document when `ids` is `None`, for reindexing). The
module's services call `SearchIndexer(context).index_documents(doc_type, ids)` (or
`remove_documents`) in their write transactions and re-index from a `REVERT_HOOKS` hook after an
undo (`data-model.md` §9). A module field type can set `FieldTypeDef.search_text` (`(value,
field) -> str`) to make its values searchable. `field_types` and `models` were added to the original
design: the media module provides the `media` field type, and the explicit model list lets the
registry validate table prefixes and include module tables in the migration metadata
(`lore.modules.load_metadata`). `field_providers` (`(session, kind_keys) -> {kind_key: [FieldDef]}`, one cheap query) were added with custom fields (#133): they supply fields stored in the vault's database, `"*"` meaning every kind but the system ones. `kind_providers` (`(session) -> [KindDef]`, #134) supply the vault's live custom kinds the same way. `ModuleRegistry.vault_kinds(session, enabled)` merges both (dropping fields whose type the vault lacks, values kept) and is what every reader of the vault's kinds or a kind's fields uses (entities, links, link types, search, graph, history, consistency, `GET /registry`, media). Enabling or disabling a module with providers re-indexes every entity for search. `on_enable`/`on_disable` receive a `VaultContext` (vault,
request session inside its transaction, registry). `kind_extensions` and `purge_hooks`
(`lore.core.entities.extensions`) were added with the entity service: a `KindExtension(kind, write,
read)` validates and stores the `ext` object of entity writes (called on every create and on
patches that send `ext`) and supplies `ext` for reads (given the request's `VisibilityPolicy`, so
it can leave out ids of hidden entities), for kinds of enabled modules. Optional
hooks: `update` (after a PATCH applied its members), `trash` (before trash/restore; may refuse),
`purge` (before the purge checks; deletes the extension rows) and `stored_problems` (vetting an
undo, which also re-vets the owners of changed extension rows). Core registers its own for system
kinds (`lore.core.time.kinds`: dimension and timeline since #45, calendar since #46). `PurgeHook`s of **every** module (enabled or not) run before an
entity is purged. A module field type may set `FieldTypeDef.validate` (`(value, field) ->
normalized value`, raising `ValueError`). `richtext_nodes` are `RichTextNodeHandler`s
(`lore.core.richtext.handlers`: node type, block/inline group, attribute validation that rejects
unknown attributes, reader filter, text and reference extraction); node types must be unique and
not core's.

### 2.2 Registration

- `lore/modules/__init__.py` defines `ALL_MODULES: list[ModuleSpec]`. The list is explicit and
  ordered: no entry points and no dynamic discovery.
- At startup (`create_app`) `ModuleRegistry.validate()` checks, and reports every problem at
  once: ids match `^[a-z][a-z0-9_]*$`, are unique and not reserved (`core`, `custom`);
  dependencies exist and are acyclic; kind keys are unique (also against core's) and their
  allowed parents exist (or are `misc`); own field keys are unprefixed and contributed ones are
  `<id>.<key>`, unique per kind, of a known field type, and enums have options; contributions
  target existing kinds; field types are unique; link-type keys and rule ids start with `<id>.`,
  are unique, rules' `owner` is the module and link types name existing kinds; module tables are
  prefixed `<id>_`, unique, not core tables and listed in `history_tables` (and no core table
  uses a module prefix; module models may use the core declarative base, whose metadata then
  holds their tables too: a table is a module's when it is one of its models' tables, #97); kind
  extensions name existing kinds, at most one per kind.
- Routers are always mounted, at `/api/v1/vaults/{vault_id}/m/<id>/`, and `create_app` adds the
  FastAPI dependency `require_module("<id>")` (`lore.core.api.deps`) to each, which returns
  `404 {code: "module_disabled"}` when the module is disabled for the vault. Other module-gated
  code can depend on it too.

### 2.3 Boundaries (enforced by import-linter)

- `lore.chronology` imports nothing from `lore`.
- `lore.core` never imports `lore.modules`.
- `lore.modules.<a>` may import `lore.core.*` (public APIs) and `lore.modules.<b>.api` only if
  `<b>` is in `<a>.depends_on`. This rule depends on each module's declared dependencies, so it
  is generated from the registry: `tests/test_architecture.py` parses every file under
  `lore/modules/<a>/` and fails on imports of another module's non-`api` code, of undeclared
  dependencies, or of `lore.modules` itself, and on module packages missing from `ALL_MODULES`.

## 3. Frontend module anatomy

```
frontend/src/modules/<id>/
  index.ts         # export default defineModule({...})
  kinds.tsx        # kind UI config (icons, panels, list columns)
  routes.tsx       # route factories (lazy-loaded components)
  panels/          # entity page panels
  views/           # module views (family tree, lexicon, map…)
  api.ts           # data hooks for module endpoints (via DataSource)
  public.ts        # PUBLIC API for dependent modules
```

```ts
defineModule({
  id: 'characters',
  kinds: { character: { icon, color, panels: [...], listColumns: [...], createDefaults, groupBy, iconBy } },
  routes: (vaultRoute) => [...],                 // attached under /v/$vault
  navSections: [...],                            // sidebar sections
  entityPanels: [{ id, kinds, title, component, placement: 'main' | 'side', order, useShown }],
  dimensionSections: [{ id, title, component, order }], // sections of the dimension overview
  linkTypeRenderers: { 'groups.member_of': MembershipRow },
  fieldTypeRenderers: { 'media': MediaFieldValue },  // a module field type's display
  fieldTypeEditors: { 'media': MediaFieldEditor },   // and its editor (the fields panel)
  fieldRenderers: { 'scripts.font': FontFieldValue }, // one field's display (wins over its type's)
  fieldEditors: { 'scripts.font': FontFieldEditor },  // and its editor
  textRenderers: { language: ScriptText },          // words of a language (core `LanguageText`)
  timelineLayers: [{ id, title, component }],   // overlays on the timeline view; component gets
                                                 // { vault, timeline, dimensionId, v, height }
  graphStyles: { nodes: {...}, edges: {...} },
  editorExtensions: [...],                       // TipTap extensions (e.g. lexicon word reference)
  commands: [...],                               // command-palette actions
  settingsPages: [...],
  searchResultRenderers: { 'languages.lexicon_entry': LexiconHit },
  richTextNodeRenderers: { lexiconRef: LexiconRefNode }, // module nodes in read-only rich text
})
```

- `frontend/src/modules/index.ts` lists all module definitions. After loading the vault registry
  (`GET /registry`), the app activates the enabled ones. Route components are lazy-loaded, so
  disabled modules cost almost nothing.
- Generic UI covers what a module does not customize. A module with only kinds, fields and link
  types needs **no** frontend code beyond `defineModule({id, kinds: {…icons…}})`.
- Boundaries (eslint-plugin-boundaries): `core` never imports `modules`; module `a` imports
  `core` public APIs and `modules/b/public.ts` only for declared dependencies.

Implementation (`core/modules/`, `core/registry/`, #60):

- `defineModule` (`core/modules/types.ts`) types every extension point above plus
  `entityHeaderMedia` (header media per kind, `'*'` for every kind; each module's entry shows,
  in module order) and `dependsOn` (the modules whose `public.ts` it
  imports). The module `id` is the backend module's.
- `app/` passes `@/modules` to `ModuleDefinitionsProvider` (core never imports modules). A module
  is **active** in a vault when it and all of its `dependsOn` are `enabled` in `GET /registry`
  (`activeModules`); `useActiveModules()`, `useExtensionList(point)` and
  `useExtensionRecord(point)` read the active modules' contributions. List points sort by `order`
  (default 0), then module order; in keyed points a later module wins a key.
- Routes: `routes(parent)` returns routes under `/v/$vault/m/<id>`; their parent renders them
  only while the module is active (404 otherwise), and components load lazily
  (`lazyRouteComponent`). Unknown `m/…` paths are 404s.
- The **KindRegistry** (`buildKindRegistry`, hooks `useKindRegistry`, `useKind(kind)`,
  `useLinkType(key)`) merges the server's kinds (label, icon name, color, fields, allowed parents,
  capabilities) and link types with the active modules' kind configs (icon/color overrides, list
  columns, create defaults), entity panels, header media and link-type renderers. Icons come from
  the curated `iconMap` (`core/registry/icons.ts`); unknown names show a circle.
- Enforcement: ESLint `no-restricted-imports` keeps modules to `@/modules/<id>/public` and
  `@/core/<area>` (index) imports, and `frontend/src/test/architecture.test.ts` checks module →
  module imports against `dependsOn`, like `backend/tests/test_architecture.py`.

## 4. Enabling and disabling

- Settings: `vault_meta.settings.modules.<id> = {enabled, settings}`. **Every module's state is
  recorded** (decided 2026-10-03): a new vault stores `enabled = default_enabled` for every
  module when it is created, and a module the vault hasn't seen yet (added by a later release, or
  a vault created before modules existed) is recorded with its default the first time the author
  opens the vault. After that, only `PATCH` changes it, so **changing a module's
  `default_enabled` later never changes existing vaults**. Read-only servers never write; they
  fall back to `default_enabled` for a missing entry. A module is **effectively** enabled only if
  every dependency is too.
- `PATCH /api/v1/vaults/{v}/modules/{id} {enabled}`:
  - enabling a module also enables its dependencies;
  - disabling a module with enabled dependents fails with `409 module_has_dependents`
    (`context.dependents`) unless `cascade: true`, which disables them too;
  - the response is `{enabled, disabled, modules}`: the modules switched on and off by the request
    and every module's resulting state. Hooks run for each switched module, inside the request's
    transaction. Unknown ids return `404 module_not_found`; read-only servers `403 read_only`.
- Effects of disabling (data is **never** deleted):
  - entities of the module's kinds are hidden from lists, search, graph, timeline and navigation,
    and direct reads return `404 module_disabled`;
  - its link types, field contributions, consistency rules, search docs, routes and UI disappear.
    Links touching hidden entities are hidden;
  - `on_disable` may clean caches, but must not delete authored data.
- Re-enabling restores everything as it was.

## 5. Schema ownership and migrations

- There is one global, linear Alembic history (`persistence-and-migrations.md`). A module's
  tables are created by migrations whose filename and docstring name the module
  (`…_maps_create_pins.py`, `"""[module: maps] create pins"""`).
- Module tables exist in every vault, even when the module is disabled (cheap, and keeps the
  migration history linear).
- JSON data owned by a module (its fields in `entities.fields`, its link `data`) is migrated with
  data migrations in the same history.

## 6. Adding a module (checklist)

1. Write `docs/modules/<id>.md` from `docs/modules/_template.md`, and get the design right first.
2. Backend package (§2), registered in `ALL_MODULES`. Migrations for any tables.
3. Frontend module (§3), registered in `modules/index.ts`.
4. Tests: service/API tests, consistency rule tests, visibility leak tests for every new read path,
   frontend component tests, and an e2e smoke test if the module adds a page.
5. Update `docs/architecture/modules.md` §1 (catalog) and `docs/plan/roadmap.md`.

## 7. Removing a module from the codebase

Removal is a data-affecting change and must be deliberate:

1. Release N: set `default_enabled = False` (this only affects vaults created from now on:
   existing vaults keep their recorded state, §4), and add a **conversion** data migration path,
   e.g.
   entities of the module's kinds become `misc` with the category set to the old kind label,
   module link types become `core.related` with the old label kept in `role`, and module fields
   are copied into custom fields where possible.
2. Release N+1: a migration runs the conversion and drops the module's tables (after the automatic
   pre-migration backup). Then remove the code, registry entries and docs.
3. Never drop data without a conversion or an explicit export path documented in the PR.
