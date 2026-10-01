# Architecture overview

Read this first. It explains the moving parts, how they fit together, and the cross-cutting rules
every change must respect. Detailed specs live in the sibling documents (see the map at the end).

## 1. System context

```
            ┌──────────────────────────────── one Docker container (or dev processes) ─────────┐
 Author ───►│  Browser SPA (React)  ──HTTP/JSON──►  FastAPI backend (Python)  ──►  Vaults on disk  │
 (localhost)│   @lore/web                           lore (uv project)              /data/<vault>/  │
            │   @lore/chronology (TS engine)        lore.chronology (Py engine)      vault.json    │
            │                                                                        lore.db (SQLite)
            │                                                                        media/        │
            │                                                                        backups/      │
            └──────────────────────────────────────────────────────────────────────────────────┘

 Readers ──► same image, LORE_READ_ONLY=true, serving a published snapshot (no private data)
 (web)       [post-MVP: static export = SPA + JSON snapshot on any static host]
```

- **Single user, local first.** No accounts and no auth. The author instance binds to localhost.
  A public deployment is only allowed in read-only mode.
- **One process serves everything.** In production the FastAPI app serves the built SPA as static
  files and the JSON API under `/api/v1`. In development, Vite serves the SPA and proxies `/api`
  to uvicorn.
- **Vault = folder.** Each vault has its own SQLite database. The backend keeps one SQLAlchemy
  engine per opened vault.

## 2. Technology stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Backend language | Python 3.14 | managed with **uv** (`uv sync`, `uv run`). |
| Web framework | FastAPI + Pydantic v2 | sync path operations (threadpool); OpenAPI is the API contract. |
| ORM / DB | SQLAlchemy 2.0 (typed ORM) + SQLite (WAL, FTS5, JSON1) | one DB file per vault; see `persistence-and-migrations.md`. |
| Migrations | Alembic, single linear history, batch mode | auto-upgrade on vault open with pre-migration backup. |
| CLI | Typer (`lore …`) | serve, vault admin, migrations, backups, publish, OpenAPI dump. |
| Backend quality | ruff (lint+format), mypy `--strict`, pytest, hypothesis, import-linter | |
| Frontend | React 19 + TypeScript (strict) + Vite | npm workspaces. |
| UI kit | shadcn/ui (Radix) + Tailwind CSS v4, lucide icons | components are copied into the repo and owned. |
| Routing / server state | TanStack Router (code-based route tree) + TanStack Query | modules contribute routes. |
| Client state | Zustand (UI prefs, time context) + URL search params | |
| Forms | react-hook-form + zod (schemas generated from field definitions) | |
| Rich text | TipTap v3 (ProseMirror) | JSON documents stored server-side. |
| Graph view | sigma.js v3 + graphology (+ ForceAtlas2 in a web worker) | |
| Structured diagrams | React Flow (@xyflow/react) + elkjs layouts | causality DAG, family tree, org chart. |
| Maps | Leaflet (CRS.Simple image maps) + react-leaflet | |
| Timeline view | custom React/SVG component on top of `@lore/chronology` viewport math | no off-the-shelf lib supports BigInt time. |
| API client | openapi-typescript (types) + openapi-fetch | generated from the backend's OpenAPI; CI checks drift. |
| Frontend quality | ESLint (flat, typescript-eslint, boundaries), Prettier, Vitest, Testing Library, Playwright | |
| Time engine | `lore.chronology` (Python) and `@lore/chronology` (TS) | pure, dependency-free, conformance-tested; see ADR-0004. |
| Packaging | Multi-stage Dockerfile, docker compose | see `deployment.md`. |
| CI | GitHub Actions | see `testing.md`. |

Versions: use the latest stable release of each tool when scaffolding, and commit the lockfiles
(`uv.lock`, `package-lock.json`). Don't pin exact versions in docs.

## 3. Repository layout

```
/
├── CLAUDE.md                     # agent operating manual (always read)
├── README.md
├── Makefile                      # one entry point for dev/check/test/gen tasks
├── Dockerfile
├── docker-compose.yml
├── package.json                  # npm workspaces root: ["frontend", "packages/*"]
├── .github/                      # CI workflows, issue & PR templates
├── docs/                         # product, architecture, modules, ADRs, plan
├── spec/
│   └── chronology/
│       ├── schema/               # JSON Schemas exported from the Python models (committed, drift-checked)
│       ├── presets/              # preset calendar definitions (JSON), shared by both engines
│       └── conformance/          # shared test vectors both engines must pass
├── backend/
│   ├── pyproject.toml / uv.lock / .python-version
│   ├── src/lore/
│   │   ├── cli.py, config.py, app.py
│   │   ├── chronology/           # PURE time engine (imports nothing else from lore)
│   │   ├── core/                 # kernel: db, vaults, modules framework, entities, links, fields,
│   │   │   │                     #   facts, richtext, search, history, visibility, consistency, api, security
│   │   │   └── time/             # dimensions, timelines, calendars, time points, resolution &
│   │   │                         #   propagation, events, recurrence persistence, correspondences, worldlines
│   │   ├── modules/              # one package per module (locations, characters, …)
│   │   └── migrations/           # Alembic env + versions (single linear history)
│   └── tests/
├── packages/
│   └── chronology/               # @lore/chronology (TS engine, viewport & tick math)
└── frontend/                     # @lore/web (React SPA)
    ├── src/
    │   ├── app/                  # shell, providers, route tree assembly
    │   ├── api/                  # generated OpenAPI types + client
    │   ├── data/                 # DataSource interface + HttpDataSource (+ StaticDataSource later)
    │   ├── core/                 # module framework, entity pages, fields, links, time UI, timeline view, …
    │   ├── editor/               # TipTap configuration & custom extensions
    │   ├── components/ui/        # shadcn components
    │   └── modules/              # module frontends, mirroring backend module ids
    └── e2e/                      # Playwright tests
```

## 4. Backend layering

```
HTTP ─► middleware (security, read-only guard, request id, errors)
     ─► routers (lore.core.*.router, lore.modules.*.router)      thin: parse, call service, map errors
     ─► services (application logic, transactions, validation)   the only place that writes
     ─► queries/repositories (SQLAlchemy; TimelineView; VisibilityPolicy)
     ─► models (SQLAlchemy ORM)  +  lore.chronology (pure computations)
```

Rules:

- **`lore.chronology` is pure.** It takes plain data (Pydantic models, ints, strings) and returns
  plain data. It does no I/O, no DB, no FastAPI, and no imports from `lore.core`/`lore.modules`.
  Enforced by import-linter.
- **Core never imports modules.** Modules plug in through the registry
  (`lore.core.modules`). A module may import core's public API and the public API (`api.py`) of
  the modules it declares as dependencies, and nothing else. Enforced by import-linter.
- **Services own transactions.** One request = one transaction = one changeset (see
  `data-model.md` §History). Derived data is updated in the same transaction: search index,
  mentions, resolved times, consistency findings for affected records.
- **Every read path goes through the visibility policy** and, for time-bound data, through
  the timeline-lineage helper (`TimelineView`). Never hand-write a query that bypasses them.

## 5. Frontend layering

```
routes/pages (app shell, core pages, module pages)
   └─► core framework (entity page, field renderers, link UI, time pickers, timeline view, …)
         └─► data hooks (TanStack Query) ─► DataSource interface ─► HttpDataSource ─► generated API client
                                                              └─► StaticDataSource (post-MVP)
   └─► @lore/chronology (conversions, formatting, recurrence expansion, viewport/ticks)
```

Rules:

- Components never call `fetch` or the generated client directly. They use data hooks backed by
  the **DataSource**. Mutations go through a separate `Mutations` interface that is absent in
  read-only/static contexts.
- **In-world time is `bigint`.** API strings are converted to `bigint` at the data layer edge and
  back. `number` may only hold time values *after* viewport projection to pixels.
- Core UI never imports module code. Modules register through `defineModule()` (see
  `modules.md`). Enforced by eslint boundaries.

## 6. Cross-cutting invariants (the "golden rules")

1. **Absolute time is canonical.** A moment is an integer count of base units since the
   dimension's inception. Calendars are lenses (D1 says what happens to typed dates when they change).
2. **Arbitrary precision everywhere.** Python `int`, TS `bigint`, JSON decimal strings, SQLite
   sortable TEXT keys (`SortableBigInt`). `float`, `Number`, `Date` and `datetime` are banned
   for in-world time. (`datetime` is fine for real-world audit timestamps like `created_at`.)
3. **One calendar/recurrence semantics, two engines.** Behavior is defined by the spec and the
   conformance vectors. Any behavior change updates spec, vectors and both engines in the same PR.
4. **Recurrences are never expanded into storage.** Only materialized occurrences (modified,
   cancelled, referenced) are stored.
5. **Time-bound records are timeline-aware** (`timeline_id`) and are read through `TimelineView`.
6. **Visibility is enforced on every read path**, including derived data (search snippets,
   graph edges, backlinks, rich-text blocks, media).
7. **Every schema change is an Alembic migration.** Every JSON payload has a schema version and an
   upgrade path.
8. **Writes are recorded in changesets** (history and undo). Bulk SQL that bypasses the ORM must
   record its changes explicitly.
9. **Modules are removable.** Nothing outside a module may depend on it unless it declares the
   dependency.

## 7. Key flows (sketches)

**Create an event from a calendar date.** The UI time-point picker produces
`{anchor: {kind: "calendar", calendar_id, fields}, precision, approximate}`.
`POST /api/v1/vaults/{v}/entities` with kind `event` reaches the event service, which validates
the anchor, resolves it with `lore.chronology`, checks structural rules (inside `[0, D]`,
end ≥ start), writes the entity, event row, dependency edges, search index and changeset, then
evaluates consistency rules for the affected records.

**Edit a calendar (D1).** `POST …/calendars/{id}/proposals` with the new definition. The server
compiles it, collects every time slot depending on the calendar (directly or transitively),
re-resolves them and returns old/new moments. The UI shows the preview, and the user can pin
records. `POST …/proposals/{pid}/apply` with the pins converts pinned anchors to `absolute`, saves
the definition and propagates, all in one transaction and one changeset (undoable).

**Timeline window.** The client asks for `[from, to)` on timeline `T` with a pixel budget. The
server queries `TimelineView(T)` for overlapping non-recurring events and overlapping series,
expands occurrences in the window with `lore.chronology`, merges materialized occurrences, applies
the importance-based level of detail, and returns items plus density buckets for culled regions.
The client draws ticks with `@lore/chronology` in the display calendar.

## 8. Document map

| Document | Contents |
|----------|----------|
| `docs/architecture/time-model.md` | Moments, dimensions, timelines/branches, time points & anchors, resolution & propagation, events, recurrence data model, facts/existence/as-of, worldlines, correspondences. |
| `docs/architecture/chronology-engine.md` | Calendar definition schema and algorithms, formatting, arithmetic, viewport/ticks, conformance suite, dual-engine policy. |
| `docs/architecture/recurrence.md` | Recurrence rule schema, occurrence identity, expansion and counting algorithms, exceptions. |
| `docs/architecture/data-model.md` | Tables, columns, indexes, IDs, sortable keys, fields, links, facts, history, search. |
| `docs/architecture/modules.md` | Module system (backend & frontend), extension points, module catalog. |
| `docs/architecture/persistence-and-migrations.md` | Vault format, SQLite config, migration policy, JSON versioning, backups. |
| `docs/architecture/api.md` | API conventions and endpoint catalog. |
| `docs/architecture/frontend.md` | SPA architecture, data layer, editor, timeline view, graph, maps, design system. |
| `docs/architecture/consistency.md` | Rule engine, severities, precision-aware evaluation, rule catalog. |
| `docs/architecture/visibility-and-sharing.md` | Visibility model, read-only mode, published snapshots, leak tests, static export. |
| `docs/architecture/security.md` | Threat model and mitigations. |
| `docs/architecture/testing.md` | Test strategy, CI, performance budgets. |
| `docs/architecture/deployment.md` | Docker, compose, configuration, dev environment. |
| `docs/modules/*.md` | One document per module. |
| `docs/adr/*.md` | Architecture decision records. |
| `docs/plan/roadmap.md`, `docs/plan/workflow.md` | Milestones, issue index, agent workflow. |
