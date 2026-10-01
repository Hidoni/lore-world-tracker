# ADR-0012: Frontend stack and DataSource abstraction

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The UI needs a WYSIWYG editor with custom nodes, an Obsidian-like graph at 10k nodes, structured
diagrams, image maps, a BigInt timeline, heavy forms and a reader mode that may later run with no
backend. D13/D14: React and shadcn/ui + Tailwind.

## Decision

React 19 + TypeScript strict + Vite; TanStack Router (code-based tree so modules can contribute
routes) and TanStack Query; Zustand for UI state; shadcn/ui (Radix) + Tailwind v4; TipTap v3;
sigma.js v3 + graphology (ForceAtlas2 worker); React Flow + elkjs; Leaflet (CRS.Simple); a custom
SVG timeline on `@lore/chronology` viewport math. All reads go through a **DataSource**
interface (HTTP now, static snapshot later). Writes go through a separate `Mutations` interface
that is absent in reader mode.

## Consequences

- Mature libraries for every hard UI part. Agents know this stack well.
- Bundle size needs discipline (lazy loading per route/module).
- The custom timeline component is a significant work item, which is accepted because no library
  handles BigInt time.

## Alternatives considered

Svelte/Vue/Solid (smaller ecosystems for the needed components); vis-timeline (uses `Date`, can't
represent cosmic times); Cytoscape.js (fine, but sigma is faster for large graphs); Lexical or
BlockNote (TipTap is more flexible for custom marks/nodes with JSON storage).
