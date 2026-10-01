# Module: `graph` — Graph view

> An Obsidian-style explorable graph of everything and how it links together, globally and around
> the current entity, filterable and time-aware. Covers R-UI-4 and part of R-LNK-4.

## Summary

| | |
|---|---|
| Module id | `graph` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M8 |

## API

`GET /m/graph/graph` with parameters:

| Param | Meaning |
|-------|---------|
| `dimension` | restrict to a dimension (plus multiversal entities); omit for the whole vault |
| `center`, `depth` (1–4) | BFS neighborhood around an entity (local graph) |
| `kinds`, `link_types`, `tags` | filters |
| `include_mentions` (default true) | include rich-text mentions as edges |
| `include_hierarchy` (default true) | include `parent_id` edges |
| `timeline`, `at` | as-of filtering: only entities existing at `at` (or unknown existence) and links valid at `at` |
| `limit` (default 5,000 nodes) | when exceeded, keep the highest-degree nodes and report `truncated` |

Response: `{nodes: [{id, kind, name, dimension_id, degree, existence: 'exists'|'unknown'|'possible'}],
edges: [{source, target, kind: 'link'|'mention'|'parent', link_type?, label?, weight}],
truncated}`. The response is visibility-filtered and computed with set-based SQL (budget: < 1 s
for 10k nodes).

## UI

- **Global graph page** (`/m/graph`): sigma.js v3 (WebGL) + graphology. ForceAtlas2 runs in a web
  worker, with start/stop and "freeze". Node color = kind color, size = degree. Edge style by
  category (family, social, spatial, causal, mention, hierarchy). Hovering highlights neighbors.
  Click shows a preview in the right panel, double-click opens the page. Search highlights and
  centers. The filter panel has kinds, link types, tags, mentions/hierarchy toggles, dimension,
  orphans toggle, and depth for local mode. The time cursor applies when `at` is set. Saved views
  (filters + camera) go in `localStorage`.
- **Local graph panel** (right panel on every entity page): depth 1–2 around the current entity,
  with the same rendering in a small canvas.
- **Visual linking:** in either view, `Alt`+drag from a node to another opens the add-link dialog
  preselected with both endpoints (link type filtered by kinds).
- Layout positions are cached per vault+view in `localStorage` to avoid re-layout on each visit
  (best effort).

## Visibility

Reader mode gets visibility-filtered nodes and edges. Mentions from private blocks don't produce
edges (`mentions.count_public + count_spoiler > 0` required).

## Disabling / removal notes

Disabling removes the graph page, the local graph panel and the endpoint. No data is affected.

## Future ideas

Graph "stories" (animate the graph through time with the cursor); clustering by community
detection; 3D mode; export to GraphML.
