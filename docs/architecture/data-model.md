# Data model

> **Status: normative for core tables.** Module tables are summarized here and specified in
> `docs/modules/<module>.md`. Column lists show intent. Exact SQLAlchemy types follow the
> conventions in §1. Every change to this model ships as an Alembic migration
> (`persistence-and-migrations.md`).

## 1. Conventions

| Topic | Rule |
|-------|------|
| Database | One SQLite file per vault (`lore.db`), WAL mode, `foreign_keys=ON`. |
| Table names | `snake_case`, plural. **Module tables are prefixed with the module id** (`languages_lexicon_entries`, `maps_pins`, `media_items`). Core tables have no prefix. |
| Primary keys | `id TEXT` holding a lowercase **UUIDv7** generated server-side (`uuid.uuid7()`, Python ≥ 3.14). Exceptions: association tables (composite PKs), `changes` and `time_dependencies` (INTEGER autoincrement), search tables (rowid). |
| Real-world timestamps | `created_at`, `updated_at`, `deleted_at` as timezone-aware UTC `DateTime` (ISO-8601 text). Never used for in-world time. |
| In-world moments | `SortableBigInt` (TEXT, `time-model.md` §2.3), columns suffixed `_t`. Specs (time points) in JSON columns suffixed `_spec`. |
| Other big integers | Decimal strings inside JSON (durations, counts, field values of type `integer`). |
| JSON | SQLAlchemy `JSON` (SQLite TEXT + JSON1). Every JSON document type with structure has a `schema_version` or lives in a column whose version is tracked (§10). |
| Enums | TEXT validated by Pydantic/services. CHECK constraints only for `visibility` (stable, tiny). |
| Foreign keys | `ON DELETE RESTRICT` (default) for authored data, so services must delete children explicitly and changesets capture everything. `ON DELETE CASCADE` only for **derived** tables (mentions, dependencies, search docs, findings). |
| Soft delete | Authored rows that users delete get `deleted_at` (trash). Purge is an explicit service operation. Queries exclude trashed rows by default (helper). |
| Optimistic concurrency | Authored rows that the API edits directly carry `revision INTEGER` (incremented on each update; PATCH must send the expected revision → `409` on mismatch). |
| Visibility | `visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','spoiler','private'))` on every user-facing authored row type listed in §8. |
| Implementation | `lore.core.db.base`: `Base` (constraint naming convention), mixins `IdMixin` (UUIDv7 `id`), `TimestampsMixin`, `SoftDeleteMixin`, `RevisionMixin` (ORM `version_id_col`: incremented on every UPDATE, `StaleDataError` on a concurrent change), `VisibilityMixin` (column + named CHECK `ck_<table>_visibility`), and `not_trashed(Model)`. `lore.core.db.types`: `SortableBigInt`, `UTCDateTime` (fixed-width ISO-8601 UTC text; naive datetimes rejected). API models use `lore.core.types.MomentStr` / `BigIntStr`. |

## 2. Vault metadata

`vault_meta(key TEXT PK, value JSON)`. Keys:

| Key | Value |
|-----|-------|
| `vault_id` | UUID (also in `vault.json`) |
| `name` | display name |
| `created_at` | timestamp |
| `settings` | `{modules: {<id>: {enabled: bool, settings: {...}}}, consistency: {<rule_id>: "off"|"warning"|"error"}, display: {...}, defaults: {visibility: "public"}}` |

`vault_id`, `name` and `created_at` are seeded by the first migration from `vault.json`, which stays
authoritative for the name (`vault_meta.name` follows it on rename and on open). Model:
`lore.core.vaults.meta.VaultMeta` (`get_meta`/`set_meta`).

Alembic's `alembic_version` table holds the schema revision. `vault.json` holds the **vault
format version** (folder layout; see persistence doc).

## 3. Entities

### 3.1 `entities`

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUIDv7 |
| `kind` | TEXT NOT NULL | `dimension`, `timeline`, `calendar`, `event`, module kinds (`character`, …), `custom.<slug>` |
| `dimension_id` | TEXT NULL → entities | Home dimension. NULL = multiversal (D10), or the row is itself a dimension. Calendars, timelines and events always have one. |
| `origin_timeline_id` | TEXT NULL → entities | Branch-only entity marker (`time-model.md` §4.6). |
| `parent_id` | TEXT NULL → entities | Organizational/structural parent (§3.4). |
| `name` | TEXT NOT NULL | |
| `sort_name` | TEXT NOT NULL | Name sort key, set with the name (`entity_sort_name`): accents removed, case-folded, each run of ASCII digits replaced by its digit count (3 digits) and the digits without leading zeros, so numbers sort by value. Compared as binary text. |
| `slug` | TEXT NOT NULL | Cosmetic, derived from the name (not unique). URLs use ids. |
| `summary` | TEXT NOT NULL DEFAULT '' | Short plain text (search, cards, tooltips). |
| `body` | JSON NULL | Rich-text document (`frontend.md` §6). |
| `body_schema_version` | INTEGER NULL | Version of the rich-text node schema used by `body`. |
| `fields` | JSON NOT NULL DEFAULT '{}' | Static (timeless) field values keyed by field key (§4). |
| `field_visibility` | JSON NOT NULL DEFAULT '{}' | Per-field visibility overrides. |
| `visibility` | TEXT | |
| `icon`, `color` | TEXT NULL | Per-entity overrides of the kind defaults. |
| `cover_media_id` | TEXT NULL | Soft reference owned by the media module (no FK, since core must not depend on modules). |
| `sort_key` | TEXT NULL | Fractional-index string for manual ordering among siblings. |
| `revision` | INTEGER | |
| `created_at`, `updated_at`, `deleted_at` | | |

Indexes: `(kind)`, `(dimension_id, kind)`, `(parent_id)`, `(origin_timeline_id)`,
`(deleted_at)`, `(kind, sort_name)`, `(parent_id, sort_name)`.

### 3.2 Aliases and tags

- `entity_aliases(id, entity_id → entities, alias, alias_kind ('alias'|'title'|'former_name'|'translation'|'nickname'), visibility, sort_key)`, indexes `(entity_id)`, `(alias)`.
- `tags(id, name, name_key, color)`. Tag names are unique ignoring case: `name_key` is
  `casefold(NFC(name))`, computed in Python whenever `name` is set, with a unique constraint.
  (SQLite's `lower()` only folds ASCII, so "Élan" and "élan" would both pass an index on
  `lower(name)`.) `entity_tags(entity_id, tag_id)`, PK both.

### 3.3 Kinds

Kinds are **registered in code** by core and modules (`modules.md`) and in
`custom_kinds` (custom-fields module). There is no `kinds` table for built-ins. The registry
merges both at runtime. A kind definition has:

```
key, module, label, plural, icon, color, description,
allowed_parents: [kind keys | "misc"],            # see §3.4
fields: [FieldDef],                               # §4
capabilities: { has_body, can_be_multiversal, has_existence, can_have_worldline,
                is_time_bound (events), is_system (dimension/timeline/calendar) }
```

### 3.4 Parent rules

`parent_id` builds **one organizational tree** per dimension (multiversal entities form their own
roots). It drives the navigation sidebar and breadcrumbs. Allowed parents per kind:

| Kind | Allowed parent kinds |
|------|----------------------|
| `event` | `event` (sub-event; incl. materialized occurrences), `misc` |
| `location` | `location` (geographic containment), `misc` |
| `group` | `group` (sub-group), `misc` |
| `species` | `species` (subspecies/variety), `misc` |
| `language` | `language` (dialect), `misc` |
| `writing_system` | `misc` |
| `character` | `misc` |
| `misc` | `misc` |
| custom kinds | configurable (default `misc`) |
| `dimension`, `timeline`, `calendar` | none |

"Misc entries can have children of any type" (brief) is implemented by `misc` being an allowed
parent of every non-system kind. Rules: no cycles. The parent must be in the same dimension, or
be multiversal, or the child must be multiversal. The parent must exist, not be in the trash, and
its kind's module must be enabled.

Home dimension rules (entity service): a dimension has none; other kinds need one unless their
`can_be_multiversal` capability allows NULL; it must reference a dimension that isn't in the
trash. System kinds and events can't change their home dimension. Another entity can only move
to a dimension its parent and children are compatible with (per the rule above).

Trash and purge: trashing leaves children in place (the trash view shows them as orphans of the
trashed parent). Purge works only from the trash and is refused while the entity has children
(trashed or not) or is referenced by records core doesn't delete with it (entities of a
dimension, branch-only entities or links of a timeline). Aliases, tag assignments and links
touching the entity are deleted with it, after the registered purge hooks ran
(`lore.core.entities.extensions`). Time-varying structure (e.g. a department
moving between ministries) is modeled with **temporal links** (e.g. `groups.part_of`), not by
`parent_id`.

## 4. Fields

### 4.1 Field definitions

```
FieldDef = { key, label, type, options?, multiple: bool, required: bool, temporal: bool,
             default_visibility, section, sort, help, searchable: bool, archived: bool }
```

Field keys match `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$`:

- fields of the kind's own module: unprefixed (`title`, `eye_color`),
- fields contributed by another module: `<module>.<key>`,
- custom fields: `custom.<key>`.

### 4.2 Field types and JSON value encoding

| Type | JSON value | Notes |
|------|------------|-------|
| `text` | string | single line |
| `long_text` | string | multi-line plain |
| `rich_text` | rich-text doc | same schema as `body` |
| `integer` | decimal string | arbitrary precision |
| `decimal` | decimal string | exact decimal, e.g. `"1.75"` |
| `boolean` | bool | |
| `enum` | option key string | `options: [{key, label, color?}]` |
| `multi_enum` | list of option keys | |
| `url` | string | http(s) only |
| `color` | `#rrggbb` | |
| `duration` | Duration JSON | `time-model.md` §5.1 |
| `time_point` | TimePoint JSON | stored in `entity_time_fields` so it participates in propagation (§5.6) |
| `media` | media id | provided by the media module |
| `measurement` | `{value: decimal string, unit: string}` | free unit |

Relations between entities are **never fields**. They are links (§6). The custom-fields UI
presents "relation fields", which create custom link types.

### 4.3 Static vs temporal values

`entities.fields[key]` is the timeless/default value. If the field is `temporal: true`, values that
hold only for a period live in `entity_facts` (§6.3). Validation of `fields` against the kind's
field definitions happens in the entity service: `lore.core.fields.KindFields` is built per kind
from its field definitions (own fields plus enabled contributions) and the vault's field types.
Each type has a validator returning the normalized value (`lore.core.fields.values` for core
types; a module type brings `FieldTypeDef.validate`, and without one any JSON value is
accepted). Unknown keys are rejected, except keys of archived fields, disabled-module fields and
fields whose type is unavailable, which are preserved but hidden. `multiple: true` fields hold a
list of values (`multi_enum` is a list already). `required` fields must have a non-empty value
(not `null`, `""` or `[]`) after every save. Until M3/M7, `duration` and `time_point` values are
validated structurally (`lore.chronology.schema`) and stored in `fields`.

## 5. Time tables (core)

### 5.1 `dimensions` (extension of `entities`, kind `dimension`)

`entity_id PK → entities`, `base_unit JSON {singular, plural, abbr}`, `duration SortableBigInt`,
`default_calendar_id NULL → entities`, `present_spec JSON NULL`, `present_t NULL`,
`time_status TEXT NULL`.

### 5.2 `timelines` (extension, kind `timeline`)

`entity_id PK`, `dimension_id → entities`, `parent_timeline_id NULL → entities`, `is_prime BOOL`,
`branch_point_spec JSON NULL`, `branch_t NULL`, `time_status`. Unique partial index:
`(dimension_id) WHERE is_prime`.

### 5.3 `calendars` (extension, kind `calendar`)

`entity_id PK`, `dimension_id`, `definition JSON` (with `schema_version`),
`definition_revision INTEGER`, `resolved_anchors JSON` (JSON pointer → moment string),
`compile_status ('ok'|'error')`, `compile_errors JSON`.

### 5.4 `events`

One **home row** per event entity, plus **override rows** in branches (`time-model.md` §4.4).

| Column | Notes |
|--------|-------|
| `id` PK | row id (≠ entity id) |
| `entity_id` → entities | the event entity |
| `timeline_id` → entities | |
| `overrides_id` NULL → events | root row id |
| `start_spec`, `start_t` | |
| `end_spec`, `end_t` | |
| `time_status` | `time-model.md` §6 |
| `importance` INTEGER | 1–5, default 3; copied to override rows |
| `category` TEXT NULL | copied to override rows |
| `recurrence` JSON NULL | rule (`recurrence.md` §2) |
| `series_start_t`, `series_end_t` NULL | cached series bounds |
| `series_entity_id` NULL → entities | for materialized occurrences |
| `occurrence_key` TEXT NULL | |
| `occurrence_state` TEXT NULL | `referenced` / `modified` / `cancelled` |
| `original_start_t` NULL | |
| `revision`, `created_at`, `updated_at` | (trash state follows the entity) |

Indexes: `(timeline_id, start_t)`, `(timeline_id, end_t)`,
`(timeline_id, series_start_t) WHERE recurrence IS NOT NULL`, unique
`(series_entity_id, occurrence_key, timeline_id) WHERE series_entity_id IS NOT NULL`,
`(entity_id)`, `(overrides_id)`.

### 5.5 `time_dependencies`

As in `time-model.md` §7.1. `id INTEGER PK`, dependent `(type, id, slot)`, `target_kind`, target
`(type, id, slot)` or `target_calendar_id`. Indexes on the dependent triple, the target pair and
`target_calendar_id`. This table is derived but kept transactional with its owners.

### 5.6 `entity_time_fields`

Time-point **field** values that must participate in propagation:
`(entity_id, field_key) PK`, `spec JSON`, `t SortableBigInt`, `time_status`. Record type
`entity_field`, slot = field key. Facts of `time_point` fields store their value here too, keyed by
`fact:<fact_id>`.

### 5.7 Worldlines and correspondences

- `worldline_segments` per `time-model.md` §11.1 (+ `revision`, timestamps, `deleted_at`). Indexes
  `(entity_id, seq)`, `(timeline_id, start_t)`.
- `correspondences(id, dimension_a_id, dimension_b_id, name, extrapolation, rate_before JSON NULL,
  rate_after JSON NULL, note, visibility, revision, timestamps, deleted_at)`.
- `correspondence_points(id, correspondence_id, a_spec, a_t, b_spec, b_t, time_status, note)`.

### 5.8 `entity_timeline_notes`

`(entity_id, timeline_id) PK`, `body JSON`, `body_schema_version`, `visibility`, `revision`,
timestamps.

### 5.9 `proposals`

Short-lived impact previews (`time-model.md` §7.4, `recurrence.md` §8):
`id, kind ('calendar'|'recurrence'), target_id, payload JSON, impact JSON, base_revision,
created_at, expires_at`. Purged on startup and hourly.

## 6. Links, facts and mentions

### 6.1 `links`

| Column | Notes |
|--------|-------|
| `id` PK | |
| `link_type` TEXT | registry key, e.g. `core.participant`, `characters.parent_of`, `custom.sworn_enemy` |
| `source_id`, `target_id` → entities | |
| `role` TEXT NULL | free label ("commander") |
| `data` JSON | type-specific attributes (e.g. `{rank: "Captain"}`, `{segment_id}`) |
| `visibility` | |
| `timeline_id` NULL | NULL = timeless link |
| `overrides_id` NULL → links | |
| `valid_from_spec`, `valid_from_t`, `valid_to_spec`, `valid_to_t`, `time_status` | NULL bounds = unbounded |
| `sort_key`, `revision`, timestamps, `deleted_at` | |

Indexes: `(source_id, link_type)`, `(target_id, link_type)`, `(link_type)`,
`(timeline_id, valid_from_t)`.

**Symmetric** link types (`sibling_of`, `allied_with`) are stored once, with
`source_id < target_id` (string order), and read in both directions. Uniqueness policies
(`unique: none | per_pair | per_pair_per_period`) are enforced by the link service per link type.

### 6.2 Link types

Registered in code (core/modules) and in `link_type_defs` for user-defined types:

```
key, label, inverse_label, description, source_kinds: [..] | "*", target_kinds: [..] | "*",
symmetric: bool, temporal: "never" | "optional" | "required", unique policy,
max_targets_per_source?, max_sources_per_target?, data_schema? (JSON Schema for `data`),
graph: {color, dashed, weight}, archived
```

`link_type_defs(key PK 'custom.<slug>', label, inverse_label, description, source_kinds,
target_kinds, symmetric, temporal, unique_policy, max_targets_per_source, max_sources_per_target,
data_schema, graph, archived, revision, created_at, updated_at)` (`unique` is stored as
`unique_policy`). These are **core**: every vault
can define link types (managed in settings). The custom-fields module only adds "relation field"
sugar on top.

Core link types: `core.participant` (event → any, role, temporal `never`), `core.causes`
(event → event, optional description) and `core.related` (any ↔ any, symmetric, temporal
`optional`). Spatial, social and linguistic link types belong to their modules (e.g.
`locations.event_site`, `groups.member_of`), so they disappear cleanly when a module is disabled.

### 6.3 `entity_facts`

`id, entity_id → entities, field_key, value JSON, timeline_id NOT NULL, overrides_id NULL,
valid_from_spec/_t, valid_to_spec/_t, time_status, visibility, source_event_id NULL → entities,
note, sort_key, revision, timestamps, deleted_at`. Indexes `(entity_id, field_key)`,
`(timeline_id, valid_from_t)`. Special keys: `core.exists` (existence), `core.name` (names over
time).

### 6.4 `mentions` (derived)

`(source_entity_id, target_entity_id) PK, count_public, count_spoiler, count_private` (counts by
the visibility of the containing block). Rebuilt from the rich-text body on every body save.
`ON DELETE CASCADE`.

## 7. History: changesets

- `changesets(id PK, created_at, origin ('ui'|'api'|'cli'|'import'|'migration'|'system'|'undo'),
  summary, request_id, reverts_changeset_id NULL, reverted_by_changeset_id NULL)`.
- `changes(id INTEGER PK, changeset_id → changesets, table_name, row_id, op ('insert'|'update'|'delete'),
  before JSON NULL, after JSON NULL)`.
- `change_entities(change_id → changes, entity_id)`: the entities a change belongs to, used for
  per-entity history. A link change belongs to both endpoints. A fact change belongs to its entity.

Capture: a SQLAlchemy `before_flush`/`after_flush` hook snapshots full rows of **registered
authored tables** (every table except derived ones: mentions, search, dependencies, findings,
proposals). Code that writes with bulk Core statements must call
`history.record_bulk(table, rows_before, rows_after)`. Undo (`POST /changes/{id}/revert`) inverts
the changes in reverse order **only if** every affected row still equals its `after` snapshot.
Otherwise it returns `409` with the conflicting rows. Undo is itself a changeset. Derived data is
recomputed by the normal service hooks after an undo.

Retention: keep everything by default. A maintenance command can compact history older than
N days into per-entity snapshots (post-MVP).

## 8. Visibility (data side)

Visibility columns exist on: `entities`, `entity_aliases`, `links`, `entity_facts`,
`worldline_segments`, `correspondences`, `entity_timeline_notes`, module rows (map pins, lexicon
entries, gallery items), plus `entities.field_visibility` and rich-text block attributes.
**Effective visibility** rules (enforced in `visibility-and-sharing.md`):

- A link, fact, alias or note is visible to readers only if its own visibility allows it **and**
  every entity it references is visible.
- An event is invisible if its timeline entity is invisible.
- Media is visible only if referenced by at least one visible context (`media_refs`).
- `spoiler` content is delivered with a flag and folded by the UI. `private` content is never
  delivered in reader mode.

## 9. Search tables (derived)

- `search_docs(rowid INTEGER PK, doc_type ('entity' | '<module>.<type>'), doc_id, entity_id,
  dimension_id, kind, visibility, deleted)`.
- `search_fts` (FTS5, `contentless_delete=1`, rowid = `search_docs.rowid`), columns: `name`,
  `aliases_public`, `aliases_restricted`, `summary`, `body_public`, `body_restricted`,
  `fields_public`, `fields_restricted`, `extra_public`, `extra_restricted`. Tokenizer
  `unicode61 remove_diacritics 2`, prefix indexes `2 3 4`.
- `search_trigram` (FTS5 trigram) on `name` + public aliases for substring matching (quick
  switcher).
- "Public" columns hold content visible to readers (public and spoiler). "Restricted" columns hold
  private content. Reader-mode queries are restricted to public columns with FTS5 column
  filters. Author mode searches all columns.

Maintained by the search service in the same transaction as the write. A
`lore vault reindex` CLI rebuilds everything. Alembic autogenerate must ignore these virtual
tables (`include_object` hook).

## 10. Versioned JSON documents

| Document | Version field | Upgrader location |
|----------|---------------|-------------------|
| Calendar definition | `definition.schema_version` | `lore.chronology.schema.upgrade` (+ Alembic data migration rewriting stored rows) |
| Recurrence rule | `recurrence.schema_version` (implicit 1 if absent) | same |
| Time point / duration | none (v1). Additions must be backward compatible; a breaking change requires a data migration rewriting all `_spec` columns | `lore.core.time.specs` |
| Rich-text body | `entities.body_schema_version` | `lore.core.richtext.upgrade` (Python) — the frontend only renders the current version |
| Field values | field type registry version per type | data migrations |
| Vault backup / export formats | `format_version` in the archive manifest | `lore.core.backup` |

## 11. Module tables (summary)

| Module | Tables |
|--------|--------|
| media | `media_items(id, sha256 UNIQUE, filename, mime, size, width, height, alt, caption, created_at, deleted_at)`, `media_refs(media_id, entity_id, context, PK all)`, `media_gallery(id, entity_id, media_id, caption, sort_key, visibility)` |
| maps | `maps_maps(id, location_id → entities, media_id, name, width, height, sort_key, visibility, …)`, `maps_pins(id, map_id, target_entity_id NULL, label, x, y, icon, color, visibility, timeline_id NULL, overrides_id, valid_from/to spec+t, time_status, child_map_id NULL)` |
| languages | `languages_lexicon_entries(id, language_id → entities, headword, romanization, pronunciation, part_of_speech, definitions JSON, etymology JSON, notes JSON, tags JSON, visibility, timeline_id NULL, valid_from/to spec+t, time_status, sort_key, revision, timestamps, deleted_at)` |
| custom_fields | `custom_field_defs(id, kind_key, key, label, type, options JSON, multiple, required, temporal, default_visibility, section, sort_key, help, archived, timestamps)`, `custom_kinds(key PK, label, plural, icon, color, description, allowed_parents JSON, capabilities JSON, archived, timestamps)` |
| characters, locations, species, groups, misc | none: kinds, fields and links only (their docs list field and link-type definitions) |
| graph | none (layouts cached client-side) |

Modules never alter core tables. If a module needs per-entity data, it adds its own table keyed by
`entity_id`.
