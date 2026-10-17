# ADR-0016: The static export answers reads from recorded API responses

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

The static export (R-SHR-3, D11's later phase, `visibility-and-sharing.md` §8) must serve the
whole reader read surface (§6, about sixty `DataSource` methods) from plain files on a static
host, with no backend. Reimplementing each read in TypeScript over raw tables would duplicate the
server's queries, visibility filtering and response shapes, and every later change to a read
would have to be made twice.

## Decision

- **Record, don't reimplement.** `lore vault export-static` starts the app read-only over a
  published snapshot, in process, and records what readers get from its GET routes: the
  response for `/api/v1/<route>` is written to `data/<route>.json`. The files hold exactly what a
  read-only server answers (same visibility policy, same shapes), so parity is by construction and
  the leak gate's guarantees carry over. Only published snapshots are exported: private data must
  not exist in the source, not merely be filtered on the way out.
- **The static data source is the HTTP data source** over a `fetch` that reads those files
  (`createStaticFetch`): the generated client, `toDomain` and every hook stay as they are.
- **Free parameters are answered in the browser** from a recorded answer: a full list filtered by
  a prefix (tags), the change points of an entity for an as-of cursor. Each such read has a handler keyed by its route; a read the export doesn't hold answers
  `404 not_in_export`, shown like any failed read.
- **Timeline windows and series occurrences are the exception: computed in the browser** (#375).
  A window has a free range and pixel budget: tiles recorded at a few zoom levels can't give the
  server's answer at a deeper zoom or another budget (culling, buckets and series bands depend on
  both). So the window logic (`lore/core/time/window.py`: overlap, LOD culling, density buckets,
  filters, series bands, materialized occurrences) is ported to TypeScript
  (`frontend/src/data/static-windows.ts`) over exported rows: each timeline's events as its view
  resolves them, with the items they show, the filters' inputs, and the series rules and
  calendars, expanded with `@lore/chronology` (occurrences are never stored in bulk). Recurrence
  semantics stay single-sourced in the two conformance-tested engines; the window's own rules
  are pinned by parity tests against the read-only server over many windows, zooms, budgets and
  filters (`e2e/static-parity.spec.ts`), so a change to `window.py` that the port misses fails
  them.
- **Static mode is chosen at runtime**, not by a separate build: the exporter marks `index.html`
  (`<meta name="lore-static" content="data/" data-vault="…">`) and turns its `<base href="/">`
  into `./`. The SPA then uses hash routing and the static data source. Assets are relative (Vite
  `base: './'`), so one build serves both a server and an export from any folder.
- **The format is versioned** (`static.json`: `format`, vault, app version, timestamps).

## Consequences

- One build, one set of response types; a new reader-facing endpoint is exported by adding its
  route to the builder (and a handler if it takes free parameters).
- Reads with unbounded parameters need a handler and a recorded full answer; their cost (export
  size, browser work) is budgeted in #378.
- Search is the second computed read (#377): the server's expression grammar, FTS5 matching,
  snippets and quick switcher ported over the exported documents (not MiniSearch, whose fuzzy
  matching would find other documents). The same documents are found; ranking uses the same
  bm25 formula over the exported documents' statistics, so near ties can be ordered differently.
- The window logic exists twice (Python and TypeScript); the parity tests keep them together.
