# Testing strategy

> Tests are the executable form of the specs. Time code carries the highest bar: a calendar bug
> silently corrupts the meaning of every date in a world.

## 1. Layers and tools

| Layer | Tools | Scope | Coverage target |
|-------|-------|-------|-----------------|
| Chronology (Python) | pytest, hypothesis | engine units, properties, **conformance vectors** | ≥ 95% lines and branches |
| Chronology (TS) | vitest, fast-check | same vectors + properties, viewport/ticks | ≥ 95% |
| Backend services/API | pytest + FastAPI `TestClient`, temp vault dirs, real SQLite | services, routers, propagation, consistency rules, modules | ≥ 85% core, ≥ 80% modules |
| Migrations | pytest | upgrade from empty, golden fixture vaults, data-migration units | every migration |
| Visibility | pytest | canary leak suite over every GET route (`visibility-and-sharing.md` §5) | all routes |
| Frontend units/components | vitest, Testing Library, MSW | data mappers, hooks, pickers, editors, panels | ≥ 70% (critical components 90%) |
| End-to-end | Playwright against the real app | key user journeys (§3) | journeys listed below |
| Performance | pytest markers `perf`, Playwright traces | budgets (§4) | nightly + on demand |

## 2. Conventions

- Deterministic: no network, no wall-clock assertions. Freeze real-world time where timestamps
  matter. Seed every property test (hypothesis profiles: `ci` with more examples, `dev` fast).
- Every bug fix adds a regression test. Calendar/recurrence bugs add a **conformance vector**.
- Backend fixtures: `vault_factory` (temp data dir + migrated vault), `client` (TestClient bound to
  a vault), builders (`make_dimension(preset="gregorian")`, `make_event(...)`, `make_character(...)`).
  Builders call services, never raw inserts, so invariants (history, search, dependencies)
  hold.
- Sample world generator: `backend/scripts/make_sample_vault.py --size tiny|small|medium|large` builds
  the demo world "Aetheria" (every calendar feature, recurring events, branches, worldlines,
  correspondences, private content, media). It is used for manual testing, e2e, perf and fixture
  vaults. `large` ≈ 100k entities / 100k events / 500k links.
- Frontend: test behavior through the DOM (Testing Library). MSW handlers are built from the
  generated API types. Never test against implementation details of TipTap/sigma internals.

## 3. End-to-end journeys (Playwright)

The app is built and served by the backend with a temp data dir. Tests create their data through
the UI or the API (fast setup helper).

| # | Journey | Milestone |
|---|---------|-----------|
| E1 | Create vault → dimension wizard (Gregorian preset) → create an event with a calendar date → see it on the timeline and the event page | M5 |
| E2 | Edit a calendar → impact preview → keep dates for most, pin one → verify moments | M5 |
| E3 | Relative anchor: move the anchor event, the dependent moves; a cycle attempt is rejected with a clear message | M5 |
| E4 | Recurring event → materialize the 3rd occurrence → add a sub-event to it → the timeline shows the marker | M5 |
| E5 | `[[` link in the editor → backlink appears on the target; rename the target, the link label updates | M4 |
| E6 | Characters: parent/child + spouse with validity → family tree → move the time cursor → as-of state changes | M7 |
| E7 | Branch from an event → override a spanning war → compare lanes show divergence | M9 |
| E8 | Worldline: time traveler with two segments → personal timeline order and age | M9 |
| E9 | Correspondence between two dimensions → "concurrently in" display on an event page | M9 |
| E10 | Upload a map → pin locations → drill down → time cursor hides a pin of a destroyed city | M10 |
| E11 | Custom kind with custom fields (incl. a temporal one) → create an entity of it | M11 |
| E12 | Publish snapshot → run reader mode → no edit UI, private canaries absent, spoilers folded | M12 |
| E13 | Backup → restore into a new vault → content identical | M12 |

## 4. Performance budgets

Measured on the `large` sample vault on a typical dev laptop:

| Operation | Budget (p95) |
|-----------|--------------|
| `GET /timelines/{id}/window` (any zoom, 1 tile, 1,500 px) | < 150 ms |
| Entity page API calls (entity + links + backlinks) | < 300 ms total |
| Search (`/search`, `/search/quick`) | < 100 ms |
| Calendar proposal over 10k dependent records | < 5 s |
| Full consistency scan | < 10 s |
| Graph endpoint, 10k nodes | < 1 s |
| Timeline pan/zoom with 1,000 visible items | 60 fps (Playwright trace) |

Perf tests are marked `perf` and run nightly and when a PR has the label `perf`. Regressions
greater than 25% fail the nightly run.

## 5. CI pipeline (GitHub Actions)

Jobs on every PR (and on `main`):

| Job | Steps |
|-----|-------|
| `backend` | `uv sync --frozen` · `ruff check` · `ruff format --check` · `mypy` · `lint-imports` · `pytest` (units, API, migrations, leak tests) |
| `frontend` | `npm ci` · `eslint` · `tsc -b` · `vitest run` · `vite build` |
| `chronology` | Python and TS conformance runners · JSON Schema export drift check · TS schema type drift check |
| `contract` | dump OpenAPI → regenerate `schema.gen.ts` → `git diff --exit-code` · `lore db check` (single head, empty autogenerate diff) |
| `docker` | build the image · run it · `GET /api/v1/health` · `GET /` serves the SPA |
| `e2e` | Playwright journeys available so far. Runs when `frontend/`, `packages/` or `backend/` change |
| `nightly` (schedule) | full e2e, perf, dependency audit (`uv pip audit`/`npm audit --omit=dev` advisory) |

All jobs except `nightly` are required for merging (D15: the agent self-merges only on green).
Use caching for uv, npm and Playwright browsers. Keep the PR pipeline under ~12 minutes.
