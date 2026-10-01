# Module: `custom_fields` — Custom fields and custom kinds

> Let authors add their own structured fields to any kind and define their own kinds ("Artifact",
> "Spell", "Ship") rendered by the generic UI. Covers R-CST-1, R-CST-2.

## Summary

| | |
|---|---|
| Module id | `custom_fields` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M11 |

## Concepts

- **Custom field:** a `FieldDef` stored in the DB for a kind (built-in or custom) or for all kinds
  (`kind_key = "*"`). Keys are `custom.<slug>`. Supports every field type in the registry
  (`data-model.md` §4.2), incl. `temporal: true` (facts), `time_point` (propagated) and `media`
  (when `media` is enabled).
- **Custom kind:** a kind stored in the DB (`custom.<slug>`) with label/plural/icon/color,
  allowed parents, capabilities and its custom fields.
- **Relation field:** UI sugar. Defining "Wielder (→ Character)" on kind Artifact creates a
  custom link type (core `link_type_defs`) restricted to those kinds, and the entity page shows
  it like a field.

## Tables

| Table | Columns |
|-------|---------|
| `custom_field_defs` | `id`, `kind_key`, `key` (unique per kind), `label`, `type`, `options` JSON, `multiple`, `required`, `temporal`, `default_visibility`, `section`, `sort_key`, `help`, `archived`, `revision`, timestamps |
| `custom_kinds` | `key` PK, `label`, `plural`, `icon`, `color`, `description`, `allowed_parents` JSON, `capabilities` JSON, `default_visibility`, `archived`, `revision`, timestamps |

## Rules for changes

- **Archive, don't delete.** Archived fields keep their values (hidden). Deleting a field with
  values requires an explicit "delete values" confirmation and creates a changeset, so it's
  undoable.
- **Type changes** are allowed only along safe conversions (text ↔ long_text, enum →
  multi_enum, text → enum with a value mapping step, integer → decimal). Others require creating
  a new field and migrating values with a helper.
- Turning `temporal` on keeps the static value as the default. Turning it off requires choosing
  what happens to facts (drop or keep archived).
- Custom kinds can be archived (entities hidden) or deleted only when no entities of the kind
  exist (or after converting them to another kind with the **convert kind** action, which is also
  usable for built-in kinds → custom kinds and vice versa when field mapping is possible).

## API

- `GET|POST /m/custom_fields/fields?kind=`, `PATCH|DELETE /m/custom_fields/fields/{id}`,
  `POST /m/custom_fields/fields/reorder`
- `GET|POST /m/custom_fields/kinds`, `PATCH|DELETE /m/custom_fields/kinds/{key}`
- `POST /m/custom_fields/convert-kind {entity_ids, to_kind, field_mapping}`
- The registry endpoint (`GET /registry`) includes custom kinds and fields when the module is
  enabled (registry contributor).

## UI

- Settings → **Kinds**: list of built-in (read-only info) and custom kinds. Create/edit with an
  icon picker (curated lucide set), color, allowed parents, capabilities.
- Settings → **Fields**: pick a kind, then a sortable list of fields grouped by section, with
  add/edit/archive dialogs per type (options editor for enums, temporal toggle, default
  visibility).
- Entity pages render custom fields through the same generic field renderers. Custom kinds get
  sidebar sections, create menus, graph colors and search facets automatically.

## Consistency rules

None of its own. Temporal custom fields participate in `core.fact.overlap` and
`core.fact.outside_existence`.

## Disabling / removal notes

Disabling hides custom kinds (and their entities), custom fields and relation-field sugar. Values
stay in `entities.fields`, and custom link types (core) stay visible as normal links. Removal
would convert custom kinds to `misc` with category = kind label, and keep custom field values
readable in an "Extra data" section.

## Future ideas

Field templates per misc category; computed fields (age from existence); per-kind page layouts.
