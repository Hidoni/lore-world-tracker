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

Implementation (#109, `backend/src/lore/modules/graph/`):

- **Nodes:** live entities the request sees, of the enabled modules' kinds. `kind`, `tag` (tag
  ids, any of them) and `dimension` (with multiversal entities) filter them. With `at` (the time
  cursor; `timeline` defaults to the prime of `dimension`, or of the center's dimension),
  entities whose existence doesn't cover the moment are left out, and `existence` is `exists`,
  `possible` or `unknown`. It is `null` without `at`.
- **Edges** join two nodes:
  - `link`: links the request sees, of `link_type`. With `at`, only timeless links and those valid
    then on the timeline (possibly valid counts). Source and target are as stored, so a symmetric
    link's ends are in its canonical order. `label` is the link's role.
  - `mention`: the source's text mentions the target. `weight` is the number of mentions. For
    readers, only mentions outside private blocks count.
  - `parent`: the source is the target's parent.
  - An edge from a node to itself is dropped.
- **Global:** the candidate nodes, then every edge between them in one statement per edge kind.
  The edge tables are scanned and checked against the candidates rather than looked up per node.
- **Local** (`center`, `depth` 1–4): breadth-first from the center, one set of edge queries per
  level. A node that doesn't exist at `at` stops the search there. Then the edges among
  everything reached are added. The center is always included; it is `404` when the request
  doesn't see it.
- **Truncation:** over `limit` nodes (default 5,000, at most 20,000), the highest-degree ones are
  kept (ties by name) with the edges between them, and `truncated` is true. Nodes come by
  degree.
- The body is built as plain data and serialized directly. Validating tens of thousands of edges
  against the model would use most of the budget. `Graph` stays the documented response model.
- Budget test `tests/modules/test_graph_perf.py` (`perf`): 10k nodes and 50k links, the graph and
  its JSON in under a second for the author and for readers. The page's budget at that size is
  `make bench-graph`, in a browser on a GPU (`testing.md` §4).

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

Implementation of the global graph (#110, `frontend/src/modules/graph/`):

- **Route** `/v/$vault/m/graph` (the module's index route, and the command "Open the graph").
  The page and its renderer load lazily, so sigma, graphology and ForceAtlas2 stay out of the shell bundle.
- **Request:** `graphQuery(filters, dimension, asOf)` turns the filters into the request.
  - The scope is the time context's dimension (with multiversal entities) or the whole vault.
  - `kind`, `link_type`, `tag`, and `include_mentions`/`include_hierarchy` (only when off) follow
    the filters. `center` and `depth` are set in local mode.
  - With the time cursor at a moment, the request also gets its `timeline` and `at`.
  - Orphans (nodes without edges) are hidden on the client.
- **Drawing:** a graphology multi-graph drawn by sigma.js 3 (WebGL).
  - Node color is the kind's color. A module's `graphStyles.nodes[kind]` overrides it, and its
    `size` is the base size. Node size grows with the square root of the degree.
  - Edge color is the module's `graphStyles.edges[link type]`, else the link type's registry
    `graph.color`, else its category's color. The categories are family, social, spatial,
    causal, mention, hierarchy and other, shown in a legend. Edge size grows with the mention
    count. Dashes aren't drawn yet.
  - Hovering a node highlights its neighbors and their edges. A click selects (a preview panel
    with "Open …" and "Show its neighborhood"), a double click opens the entity.
  - "Find" dims what doesn't match. One match, or the selection, is centered.
- **Layout:** ForceAtlas2 runs in a web worker (`graphology-layout-forceatlas2/worker`, with
  inferred settings). It starts by itself when some node has no known position and stops after
  2 to 15 s, depending on size. "Layout" and "Stop" run it again or stop it. "Freeze" stops it
  and keeps the positions. Over 2,000 edges, edges are hidden while the camera moves (sigma's
  `hideEdgesOnMove`): drawing them is most of a frame's cost.
  - New nodes start on a golden-angle spiral.
  - Positions are cached in `localStorage` per vault and filter set (`lore.graph.layout.*`),
    up to 20,000 nodes.
- **Saved views:** named filter sets in `localStorage` (`lore.graph.views.<vault>`), applied
  from a select.
- **Notices:** a `truncated` response gets a notice (the best-connected entities are shown) with
  "Show up to 20,000", which asks again with `limit` 20,000 until the filters change.
  With the time cursor at a moment, the page says it shows what existed then.
- **Fallbacks:** "As a list" lists the entities by connections (the first 1,000), for keyboard
  and screen-reader use. Without WebGL the drawing says so and points there.

Local graph and visual linking (#111):

- **Local graph panel** (side panel "Local graph" on every entity page): the entity's
  neighborhood, 1 or 2 steps (`center`, `depth`), at the time cursor, drawn by the same
  renderer at 256 px.
  - The entity is highlighted, and a double click opens a neighbor.
  - "Open in the graph" goes to `/v/$vault/m/graph/focus/<entity>`, the graph page starting on
    that neighborhood.
  - It says when there are no connections yet.
- **Visual linking:** `Alt`+drag from a node to another, in either view, opens the add-link
  dialog from the first entity with the second as target (`LinkDialog` takes a preselected
  `target`). The link types that fit both kinds are offered.
  - While dragging, the camera holds still and the source is highlighted. Releasing elsewhere
    cancels.
  - `LinkDrag` is the gesture on its own, unit-tested without WebGL.
  - Readers (no mutations) get no `Alt`+drag.
- **Timeline drops** (`frontend.md` §9.4): an entity dropped on a timeline event opens a dialog.
  - An event asks for the direction ("A causes B" or "B causes A") and creates `core.causes`.
  - Anything else asks for an optional role and creates `core.participant`.
  - A computed occurrence is materialized first.
  - Sources: any link to an entity page in the vault, through the URL the browser drags (sidebar
    rows, search results, Recent), or data set with `setEntityDrag` (`application/x-lore-entity`).
  - Read-only timelines take no drops.

## Visibility

Reader mode gets visibility-filtered nodes and edges. Mentions from private blocks don't produce
edges (`mentions.count_public + count_spoiler > 0` required).

## Disabling / removal notes

Disabling removes the graph page, the local graph panel and the endpoint. No data is affected.

## Future ideas

Graph "stories" (animate the graph through time with the cursor); clustering by community
detection; 3D mode; export to GraphML.
