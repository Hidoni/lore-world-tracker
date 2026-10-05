# CLAUDE.md — Lore World Tracker

A locally hosted, single-user **living wiki for fictional worlds** in which **time is tracked
strictly and exactly**, from a dimension's inception to its heat death. Python backend (uv,
FastAPI, SQLAlchemy, one SQLite DB per vault), React + TypeScript frontend (npm workspaces),
shipped as a Docker image.

## Project status

Planning finished on 2026-10-01. Implementation happens through **GitHub issues** grouped in
milestones **M0–M13** in `Hidoni/lore-world-tracker` (see `docs/plan/roadmap.md`). M0–M2
are done and released as v0.1.0 (`CHANGELOG.md`). If reality and this file diverge, fix this
file in your PR.

## Read before you work

1. This file, then `docs/plan/workflow.md` (how to pick, claim, implement, verify and merge an
   issue).
2. Your issue (`gh issue view <n>`) and **every spec section it links**.
3. Anything touching time: `docs/architecture/time-model.md` in full, plus
   `chronology-engine.md` / `recurrence.md` as relevant.
4. Use the vocabulary in `docs/product/glossary.md` in code, UI and docs. Full doc index:
   `docs/README.md`.

## Non-negotiable rules

1. **In-world time is arbitrary-precision integers.** A moment is an integer count of base units
   since the dimension's inception. Python `int`; TypeScript `bigint`; JSON/API decimal
   **strings**; SQLite `SortableBigInt` TEXT columns (`*_t`). **Never** use `float`, JS `number`,
   `Date` or `datetime` for in-world time (real-world audit timestamps excepted). The only
   float conversion allowed is pixel projection in `@lore/chronology/viewport`.
2. **Absolute time is canonical; calendars are lenses.** Typed dates are preserved in anchors.
   Calendar edits go through proposals with impact previews (D1).
3. **One semantics, two engines.** Calendar/recurrence/correspondence behavior is defined by
   `docs/architecture/chronology-engine.md`, `recurrence.md` and the vectors in
   `spec/chronology/conformance/`. Any behavior change updates the spec, the vectors **and both**
   `backend/src/lore/chronology` and `packages/chronology` in the **same PR**. Chronology bugs
   get a conformance vector.
4. **Never store recurring-event occurrences in bulk.** Only materialized occurrences
   (modified/cancelled/referenced) are stored.
5. **Time-bound reads go through `TimelineView`. All reads go through the `VisibilityPolicy`.**
   Never hand-roll lineage or visibility SQL.
6. **Writes go through services:** one request = one transaction = one changeset. Time
   propagation, search indexing, mentions and consistency findings update in that transaction.
   Bulk SQL must call `history.record_bulk`.
7. **Schema change ⇒ Alembic migration in the same PR.** There is a single linear head. Never
   edit a merged migration. Migrations don't import ORM models. JSON documents carry versions
   with upgraders (`persistence-and-migrations.md`).
8. **Module boundaries:** `lore.chronology` imports nothing from `lore`; core never imports
   modules; a module imports only core public APIs and the `api.py`/`public.ts` of modules it
   declares in `depends_on`. Enforced by import-linter, `backend/tests/test_architecture.py`
   (module → module imports, from the registry) and eslint-boundaries.
9. **New read endpoint ⇒ `PolicyDep` + leak-test recipe** (`backend/tests/visibility/recipes.py`),
   and if reader-facing, an entry in `docs/architecture/visibility-and-sharing.md` §6.
10. **API contract:** after backend API changes run `make gen` and commit the regenerated files.
    Never edit `*.gen.ts` or exported schemas by hand.
11. **Product decisions D1–D16** (`docs/plan/planning-log.md`) are fixed. To change one, or to
    resolve a product ambiguity, label the issue `status:needs-decision`, explain the options, and
    move on to another issue.
12. **GitHub scope:** only `Hidoni/lore-world-tracker`. Never create other repositories or GitHub
    Projects boards. Issues, labels, milestones and PRs in this repo are fine.

## Repository map

```
backend/          uv project; package `lore` in src/lore/
  src/lore/chronology/   pure Python time engine (calendars, recurrence, correspondences)
  src/lore/core/         kernel: db, vaults, modules framework, entities, links, fields, facts,
                         richtext, search, history, visibility, consistency, api, security
  src/lore/core/time/    dimensions, timelines, calendars, time points, propagation, events, …
  src/lore/modules/<id>/ one package per module (see docs/architecture/modules.md)
  src/lore/migrations/   Alembic (single linear history)
  scripts/               make_sample_vault.py: the sample world generator (testing.md §2)
  tests/                 fixtures/vaults/v*/: golden fixture vaults (one per release)
packages/chronology/  @lore/chronology: TS time engine + viewport/tick math
frontend/         @lore/web: React SPA (src/app, api, data, core, editor, components/ui, modules), e2e/
spec/chronology/  JSON Schemas (exported), presets, conformance vectors: shared by both engines
docs/             product/, architecture/, modules/, adr/, plan/
scripts/          e2e.sh (`make e2e`), docker-smoke.sh (`make docker-smoke`); CI: .github/workflows/ci.yml
                  (PR gate) and nightly.yml (differential fuzzing, benchmarks)
Dockerfile, docker-compose.yml   the image and the suggested deployment (deployment.md §2–§3)
tools/backlog.py  issue helper: `uv run tools/backlog.py ready|show|claim|unclaim|stats`
.claude/skills/next-issue/  project skill: take the next ready issue through the whole workflow
```

## Commands

| Command | Purpose |
|---------|---------|
| `make help` | list the targets (the default goal) |
| `make setup` | install backend (uv) + frontend (npm workspaces) deps, Playwright's Chromium |
| `make dev` | backend on :8000 (reload) + Vite on :5173 (proxies `/api`), data in `./data`; Ctrl-C stops both |
| `make check` | **run before every PR**: `check-backend` (ruff check, ruff format --check, mypy, import-linter, `lore db check`, pytest) + `check-frontend` (eslint, prettier --check, tsc, vitest, build) + `check-contract` (OpenAPI types drift) + `check-chronology` (chronology JSON Schema and TS type drift) |
| `make check-backend` / `make check-frontend` / `make check-contract` / `make check-chronology` | one part of `make check` |
| `make test` | `test-backend` + `test-frontend` + `test-chronology` |
| `make test-backend` / `make test-frontend` / `make test-chronology` | focused test runs (`test-chronology`: `backend/tests/chronology` + `@lore/chronology` vitest, incl. both conformance runners) |
| `make test-differential` | random calendars and ops through both chronology engines, results compared (`DIFFERENTIAL_CASES`, default 200; testing.md §6) |
| `make bench` | chronology benchmarks and perf budgets, both engines (testing.md §4.1) |
| `make e2e` | build the SPA, serve it from `lore serve` on a temp data dir, run Playwright (`scripts/e2e.sh`; args go to Playwright) |
| `make gen` | regenerate OpenAPI TS types (`frontend/src/api/schema.gen.ts`), chronology JSON Schemas (`spec/chronology/schema/`, from `lore.chronology.schema`) and their TS types (`packages/chronology/src/schema.gen.ts`) plus the calendar JSON Schema the TS engine validates with (`calendar-schema.gen.ts`) |
| `make fmt` | ruff format + prettier |
| `make docker` | build the image `lore-world-tracker:local` (the tag `docker-compose.yml` uses) |
| `make docker-smoke` | start the built image via docker compose (host port 8080) and smoke-test it (`scripts/docker-smoke.sh`, CI `docker` job) |
| `make sample-vault SIZE=small` | generate the demo world "Aetheria" as a new vault in `./data` (`SIZE=tiny\|small\|medium\|large`, `SEED=…`; `backend/scripts/make_sample_vault.py`) |
| `uv run lore …` (in `backend/`) | CLI: `serve`, `vault list\|create\|status\|migrate\|check\|reindex\|optimize\|backup\|restore`, `db revision -m … [--autogenerate]`, `db check`, `openapi`, `chronology export-schemas [--check]` |

Node version: see `.nvmrc`. Python version: see `backend/.python-version` (3.14).

## Conventions

**Python:** ruff (lint + format), mypy `--strict`, SQLAlchemy 2.0 typed ORM (`Mapped[...]`),
Pydantic v2, sync FastAPI path operations, services own transactions, routers stay thin. IDs are
`uuid.uuid7()` strings. Errors are raised as typed exceptions and mapped to problem+json in one
place. Tests use builders that call services (never raw inserts).

**TypeScript:** strict mode (+ `noUncheckedIndexedAccess`). Components use data hooks backed by
the `DataSource` (never `fetch`). Moments are `bigint` after the data layer. Use
`floorDiv`/`floorMod` from `@lore/chronology` (bigint `%` truncates). `JSON.stringify` can't
serialize `bigint`, so use the data-layer serializers. shadcn components live in `components/ui`.
Don't edit generated code.

**Naming:** glossary terms everywhere. Module tables are prefixed `<module>_`. Link-type and
consistency-rule ids are prefixed by their owner (`core.`, `characters.`). Field keys:
unprefixed for the kind's own module, `<module>.<key>` for contributions, `custom.<key>` for
custom fields.

**Commits/PRs:** Conventional Commits (`feat(chronology): …`). One issue per PR, `Closes #N`,
squash-merge after green CI (details in `docs/plan/workflow.md`).

**Docs:** specs change in the same PR as the code. Significant decisions get a new ADR in
`docs/adr/`. Module behavior lives in `docs/modules/<id>.md`.

## Gotchas

- SQLite + Alembic: `render_as_batch=True`; FTS5 tables are created with `op.execute` and excluded
  from autogenerate; `PRAGMA foreign_keys=ON` is per connection (set in the connect hook).
- Run uvicorn with **one worker** (per-vault engines and caches are in-process).
- Transactions that may write must start with `BEGIN IMMEDIATE` (`SessionDep` does it for non-GET
  requests; elsewhere use `OpenVault.write_sessions` / `lore.core.db.for_writing`). A deferred
  read-then-write fails instantly with "database is locked" if another write committed meanwhile.
- Sortable keys compare as text: never `CAST` them to numbers in SQL, and never apply a non-binary
  collation to them.
- Calendar field values in anchors are **strings** (numbers or slot ids). Store named units by
  slot id so "keep typed dates" survives calendar edits.
- Recurrence windows must jump with ordinal arithmetic. A loop from the series start is a bug
  even if tests pass.
- Visibility leaks hide in derived data: search snippets, counts, graph edges, mentions, media.
