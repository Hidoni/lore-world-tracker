# ADR-0015: relatives-tree for the family tree layout

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

The characters module's family tree (#93) needs generations top to bottom, spouses side by side
(including remarriages, with each marriage's children under it), half-siblings, and a layout of
300 people in under a second. The specs planned elkjs layered layout with marriage junction
nodes, rendered in React Flow (like the causality, language and species views). The issue asked
for a time-boxed spike comparing that with a dedicated genealogy library (family-chart,
relatives-tree).

## Spike

A synthetic dynasty (couples with 2–3 children, every fifth person remarried, each child
married) was laid out by elkjs 0.11 (layered, `DOWN`, one junction node per couple) and by
relatives-tree 3.2.2, in Node:

| | elkjs + junction nodes | relatives-tree |
|---|---|---|
| ~400 people | 0.6–1.0 s (Brandes-Köpf placement; 2.8–3.4 s with network simplex) | ~10 ms |
| Parent above child | always | always |
| Spouses side by side | 36 of 171 pairs (21 %) | 171 of 171 |
| Remarriage, half-siblings | children under the right couple, spouses scattered | second spouse on the other side, children under each couple |
| Size (min + gzip) | ~470 KB (already a dependency) | ~3.5 KB, no dependencies, MIT |

family-chart (d3 7 as a dependency, ~650 KB unpacked) renders its own SVG/HTML and would replace
React Flow for this one view, so it was not taken further.

relatives-tree's limits, found on edge cases: a person has at most two parents; siblings are
only drawn through shared parents (siblings without recorded parents are not shown); its
`gender` must be `male` or `female` (it puts spouses on either side); it lays out around one root
(ancestors, descendants, siblings and spouses of the tree it walks).

## Decision

Lay out family trees with **relatives-tree**, through an adapter
(`frontend/src/modules/characters/views/genealogy.ts`) and render them in React Flow:

- At most two parents a person, biological ones first. Other parent links show in the list view.
- A sibling without recorded parents joins the other sibling's parents. When neither has any,
  both go under a shared "Unknown parent" placeholder.
- Spouses get opposite "genders" by two-coloring the marriages. The character's own `gender`
  field is not used, so the layout never depends on it.
- relatives-tree's grid (a person is 2 × 2 cells) is scaled to pixels. Its connector lines are
  drawn as one SVG under the boxes.

The other diagrams (causality, language and species descent, org chart) stay on elkjs.

## Consequences

- Family trees read like genealogies (marriages adjacent) and lay out instantly. The layout
  runs synchronously, without ELK's worker or promise.
- A small extra dependency. Its limits are handled in the adapter and covered by component tests
  (generations, spouse adjacency, remarriage, unknown parents, 300 people under 1 s).
- "As a list" lists every person the endpoint returns, also ones the drawing can't place.
