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
| `custom_fields_defs` | `id`, `kind_key` (a kind or `*`), `key` (`custom.<slug>`, unique per kind; a `*` key unique everywhere), `label`, `type`, `options` JSON, `multiple`, `required`, `temporal`, `default_visibility`, `section`, `sort_key`, `help`, `searchable`, `archived`, `revision`, timestamps |
| `custom_fields_kinds` | `key` PK (`custom.<slug>`), `label`, `plural`, `icon`, `color`, `description`, `allowed_parents` JSON, `capabilities` JSON (`has_existence`, `can_be_multiversal`, `can_have_worldline`), `default_visibility` (new entities'; null: the vault's), `archived`, `revision`, timestamps |

## Rules for changes

- **Archive, don't delete.** Archived fields keep their values (hidden). Deleting a field with
  values requires an explicit "delete values" confirmation and creates a changeset, so it's
  undoable.
- **Type changes** are allowed only along safe conversions (text ↔ long_text, enum →
  multi_enum, text → enum with a value mapping step, integer → decimal). Others require creating
  a new field and migrating values with a helper (`422 unsafe_type_change`). Values (entities',
  trashed ones too, and facts) migrate in the same changeset: long_text → text joins lines,
  text → enum needs `value_map` covering every stored value (an option key, or `null` to clear
  it), enum → multi_enum wraps the value in a list.
- Options in use can't be removed. `multiple` false → true wraps values in lists; true → false
  is refused while an entity has several values.
- Turning `temporal` on keeps the static value as the default. Turning it off requires choosing
  what happens to facts: `facts: "drop"` (to the trash, through the facts service) or `"keep"`
  (stored, hidden while the field isn't temporal).
- Deleting a field with values without `delete_values=true` is `409 conflict`
  (`context.entities`). With it, values, visibility overrides, `time_point` rows and facts go in
  the field's changeset.
- A field whose type the vault lacks (a `media` field while `media` is disabled) is left out of
  the kind; its values are kept.
- Custom kinds can be archived (the kind and its entities leave the vault's kinds: hidden from
  lists, search, graph and entity reads) or deleted only when no entities of the kind exist, the
  trash included (`409 conflict` otherwise; its custom fields go with it). Converting entities to
  another kind with the **convert kind** action is also usable for built-in kinds → custom kinds
  and vice versa. Kinds that keep data of their own (events, dimensions, timelines, calendars,
  languages: a kind extension) can't be converted. `field_mapping` moves values, visibility
  overrides and facts (to a temporal field only) to the new kind's fields, `null` drops them;
  unmapped values stay stored (hidden unless the new kind has the field), so converting back
  restores them. A conversion is one changeset and never merges with earlier edits.
- `can_be_multiversal` can't be turned off while entities of the kind are multiversal.

## API

- `GET|POST /m/custom_fields/fields?kind=`, `GET|PATCH|DELETE /m/custom_fields/fields/{id}`
  (`?delete_values=`), `POST /m/custom_fields/fields/reorder` (`{kind_key, ids}`). Author-only:
  readers get `404` (they see what they may of the fields through `GET /registry` and entities).
- `GET|POST /m/custom_fields/kinds`, `GET|PATCH|DELETE /m/custom_fields/kinds/{key}` (author-only)
- `POST /m/custom_fields/convert-kind {entity_ids, to_kind, field_mapping}`
- The registry endpoint (`GET /registry`) includes custom kinds and fields when the module is
  enabled (`ModuleSpec.kind_providers` and `field_providers`, `modules.md`); a kind's
  `default_visibility` is new entities' visibility when a create sends none.

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
