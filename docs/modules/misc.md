# Module: `misc` — Miscellaneous

> Anything that doesn't fit an established component (brief example: "time travel" as a
> scientific concept). Misc entries can be the **parent of entities of any kind** and can take
> part in events. Covers R-MSC-1.

## Summary

| | |
|---|---|
| Module id | `misc` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M6 |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `misc` | Misc entry / Misc entries | `shapes` | `misc` | body, existence, multiversal |

Every non-system kind lists `misc` among its allowed parents (`data-model.md` §3.4), so a misc
entry acts like a folder/topic page that can hold characters, events, locations, other misc
entries, custom-kind entities, and so on.

### Fields (`misc`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `category` | `text` | no | public | Free text with autocomplete from existing values ("Concept", "Technology", "Artifact", "Magic"). Drives grouping in the sidebar. |

## Link types

None. Misc entries use `core.related` and `core.participant`.

## Tables

None.

## API

None beyond the generic entity API (`GET /entities?kind=misc&…`). Category suggestions come from
`GET /entities/field-values?kind=misc&field=category` (a generic endpoint for text-field
autocomplete, implemented in core with this module as the first user).

## UI

- Sidebar section "Misc entries" grouped by `category`, then by tree (`parent_id`): the kind's UI
  config sets `groupBy: 'category'`, so the top level comes from `/tree?group_by=category` and is
  listed by category (case variants merged), entries without one last under "No category".
- Misc entity page: an extra **Children** panel (`misc.children`) listing children of every kind
  and dimension (`/entities/{id}/children`), grouped by kind in registry order, with an "Add
  child" menu of every kind that may be placed under a misc entry (it opens the create dialog
  with the entry as parent).
- `category` autocompletes from `GET /entities/field-values`: every single text field editor
  offers the values other entities of its kind use (a `datalist`, most used first).

Implementation (#89): `backend/src/lore/modules/misc/` (`MODULE`, kind in `kinds.py`) and
`frontend/src/modules/misc/`. Every non-system kind lists `misc` among its allowed parents, which
`backend/tests/modules/test_misc.py` checks for core and every registered module. The sample world
has "Time Travel" (Concept, multiversal) holding two misc entries and an event,
and "Tide Magic" (Magic).

## Consistency rules

None.

## Disabling / removal notes

Disabling hides misc entries. Children of hidden misc entries are shown as roots in their own
kind sections. Removal would convert misc entries to a custom kind `custom.misc`.

## Future ideas

Per-category templates (a "Technology" category pre-fills custom fields).
