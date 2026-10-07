# Testing strategy

> Tests are the executable form of the specs. Time code carries the highest bar: a calendar bug
> silently corrupts the meaning of every date in a world.

## 1. Layers and tools

| Layer | Tools | Scope | Coverage target |
|-------|-------|-------|-----------------|
| Chronology (Python) | pytest, hypothesis | engine units, properties, **conformance vectors** | ≥ 95% lines and branches |
| Chronology (TS) | vitest, fast-check | same vectors + properties, viewport/ticks | ≥ 95% (`numbers.ts`: 100%; `numbers.ts` and `calendar/` enforced by the vitest coverage thresholds) |
| Backend services/API | pytest + FastAPI `TestClient`, temp vault dirs, real SQLite | services, routers, propagation, consistency rules, modules | ≥ 85% core, ≥ 80% modules |
| Migrations | pytest | upgrade from empty, golden fixture vaults, data-migration units | every migration |
| Visibility | pytest | canary leak suite over every GET route (`visibility-and-sharing.md` §5) | all routes |
| Frontend units/components | vitest, Testing Library, MSW | data mappers, hooks, pickers, editors, panels | ≥ 70% (critical components 90%) |
| End-to-end | Playwright against the real app | key user journeys (§3) | journeys listed below |
| Performance | pytest markers `perf`, Playwright traces | budgets (§4) | nightly + on demand |

## 2. Conventions

- Deterministic: no network, no wall-clock assertions. Freeze real-world time where timestamps
  matter. Seed every property test. `PROPERTY_PROFILE=ci` selects more examples for both engines
  (hypothesis profile `ci`, fast-check `numRuns`); the default `dev` is fast. The CI `chronology`
  job sets it.
- Every bug fix adds a regression test. Calendar/recurrence bugs add a **conformance vector**.
- Backend fixtures: `vault_factory` (temp data dir + migrated vault), `client` (TestClient bound to
  a vault), builders (`make_dimension(preset="gregorian")`, `make_event(...)`, `make_character(...)`).
  Builders call services, never raw inserts, so invariants (history, search, dependencies)
  hold.
- Sample world generator: `backend/scripts/make_sample_vault.py --size tiny|small|medium|large
  --out DATA_DIR` (`make sample-vault SIZE=…`) builds the demo world "Aetheria" as a new vault.
  It writes through the services only (one transaction = one changeset, so history, search and
  mentions stay consistent) and is deterministic for a `--seed` (same content; ids and real-world
  timestamps differ). It is used for manual testing, e2e, perf and the golden fixture vaults
  (`--fixture DIR`, `persistence-and-migrations.md` §3.5).
  - **The core** (every size; `tiny` is only the core): a fixed, hand-written set with stable
    names that tests rely on, covering every feature the app has.
  - **The bulk** (`small` and up): seeded random events with mentions, tags, aliases, hierarchy and
    private/spoiler content, and links between them. `small` ≈ 1k events / 3k links, `medium` ≈
    10k / 40k, `large` ≈ 100k events / 500k links (takes about 20 minutes to build).
  - **Every milestone extends it** with the features it adds (target: every calendar feature,
    recurring events, branches, worldlines, correspondences, facts, module kinds, private
    content, media): a new step in the core, bulk volume where it matters, and the facts tests
    should check in `SampleWorld`. The module docstring lists what is planned.
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
| `GET /timelines/{id}/window` (1 tile, 1,500 px): ≤ 20k overlapping events, or any window already computed | < 150 ms |
| `GET /timelines/{id}/window`: cold whole-dimension zoom-out over 100k events (decided 2026-10-07; repeats are served from the window cache) | < 500 ms |
| Entity page API calls (entity + links + backlinks) | < 300 ms total |
| Search (`/search`, `/search/quick`) | < 100 ms |
| Calendar proposal over 10k dependent records (preview, and apply; `tests/time/test_proposals_perf.py`) | < 5 s each |
| Full consistency scan | < 10 s |
| Graph endpoint, 10k nodes | < 1 s |
| Timeline pan/zoom with 1,000 visible items | 60 fps (Playwright trace) |

Perf tests are marked `perf` and run nightly and when a PR has the label `perf`. Regressions
greater than 25% fail the nightly run.

### 4.1 Chronology engine budgets

Both engines, on the conformance calendar `gregorian-seconds` (one-second base units) unless
noted. `make bench` runs the benchmarks (`backend/tests/chronology/test_benchmarks.py` with
pytest-benchmark, `packages/chronology/test/*.bench.ts` with Vitest bench), which assert each
budget on the median; the `perf` tests next to each feature's unit tests check the same budgets
with plain timers. CI runs them nightly.

| Operation | Budget | Set by |
|-----------|--------|--------|
| Compile the Gregorian preset | < 20 ms | #29 |
| Compile a 1,000,000-year top period (and < 300 MB peak in Python) | < 2 s | #10 |
| `to_fields` / `from_fields` (years 0 to ~6 million) | ≥ 50,000/s each (< 20 µs) | #11 |
| `ordinal` + `from_ordinal` (moments up to 10^30; 1,000,000-year periods included) | ≥ 10,000 pairs/s (< 100 µs) | #12 |
| `diff` (years to seconds) + `add` back, moments up to 10^200 | < 10 ms per pair (300 in < 3 s) | #16 |
| `expand` a monthly rule in a window 10^90 years after the series start | < 50 ms | #19 |
| `series_bounds` of a yearly rule with `count` 10^12, calendar freshly compiled | < 100 ms | #21 |
| `ticks` for any viewport (TS) | < 2 ms | #28 |

## 5. CI pipeline (GitHub Actions)

Jobs on every PR (and on `main`):

| Job | Steps |
|-----|-------|
| `backend` | `uv sync --frozen` · `ruff check` · `ruff format --check` · `mypy` · `lint-imports` · `pytest` (units, API, migrations, leak tests) |
| `frontend` | `npm ci` · `eslint` · `tsc -b` · `vitest run` · `vite build` |
| `chronology` | `make check-chronology` (JSON Schema export drift · TS schema type drift) · `make test-chronology` (both engines' chronology tests incl. the conformance runners) · `make test-differential` with 1,000 cases (§6) when `spec/chronology`, `backend/src/lore/chronology`, `backend/tests/chronology` or `packages/chronology` changed (a step-level skip, so the check still reports) |
| `contract` | dump OpenAPI → regenerate `schema.gen.ts` → `git diff --exit-code` · `lore db check` (single head, empty autogenerate diff) |
| `docker` | `make docker` (build the image) · `make docker-smoke` (`scripts/docker-smoke.sh`): start it through `docker-compose.yml` in a temp project dir, wait for the healthcheck, `GET /api/v1/health` · `/api/v1/meta` has a version · `GET /` (and a client route) serves the SPA · the process is not root · a write to `/data` lands in the host's `./data` |
| `e2e` | `make e2e` (`scripts/e2e.sh`): build the SPA, `lore serve` it with `LORE_STATIC_DIR` on a temp `LORE_DATA_DIR`, wait for `/api/v1/health`, run the Playwright journeys available so far with `E2E_BASE_URL`. Runs on every PR while it is a fast smoke test; restrict it to `frontend/`, `packages/` and `backend/` changes (with a job-level skip, so the required check still reports) once journeys make it slow |
| `nightly` (schedule, `.github/workflows/nightly.yml`) | now: `make test-differential` with 10,000 new random cases (§6) · `make bench` (§4.1). Later: full e2e, the other perf budgets, dependency audit (`uv pip audit`/`npm audit --omit=dev` advisory) |

The workflow is `.github/workflows/ci.yml`; each job calls the same `make` target developers run
locally (`check-backend`, `check-frontend`, `check-contract`, `check-chronology`, `test-chronology`, `e2e`, `docker`
+ `docker-smoke`), with
`UV_FROZEN=1`. All jobs except `nightly` are required for merging (D15: the agent self-merges only
on green, see `workflow.md` §7). A new push cancels the superseded run of the same PR. Dependabot
(`.github/dependabot.yml`) opens weekly grouped updates for `uv` (backend), `npm` (root) and
GitHub Actions.
Use caching for uv, npm and Playwright browsers. Keep the PR pipeline under ~12 minutes.

## 6. Differential testing (chronology)

The conformance vectors pin the cases someone thought of. Differential tests look for drift
between the two engines everywhere else (ADR-0004, `chronology-engine.md` §14):
`backend/tests/chronology/differential/` generates random cases with hypothesis, runs each through
the Python engine and through the TypeScript engine (the Node CLI
`packages/chronology/bin/chrono-exec.ts`, one process for the run), and compares the results
exactly, like vectors (`validate` errors as a set).

- **Cases.** Random calendars with bounded sizes (2–4 levels, up to two regimes with absolute or
  `local` starts, uniform and sequence templates with named, run and intercalary children, fixed,
  cycle and rules top patterns, exceptions, eras, an overlay, continuous and reset cycles with
  exclusions, formats and display options), each `validate`d as is and with random corruptions.
  On a valid calendar, ops with moments over the whole dimension and near its special moments:
  conversions (dates read off the calendar, then perturbed), bounds, ordinals, options, cycles,
  eras, overlays, add/diff, formatting and calendar recurrence rules. Then calendar-free ops:
  interval rules, correspondences (`map`, `compose`) and the numeric utilities. Generated
  documents may be invalid on purpose: both engines must report the same errors.
- **Sizes.** `DIFFERENTIAL_CASES` (default 200 locally, 1,000 in PR CI, 10,000 nightly). PR runs
  are derandomized (the same cases every time); the nightly run sets `DIFFERENTIAL_RANDOM=1` to
  explore new ones.
- **Findings.** A discrepancy (or a crash of either engine) fails with the case as a ready-made
  conformance case and its calendar. Add it as a vector with the spec's expected result (note:
  "found by differential testing"), then fix the engine that is wrong. A random nightly failure
  also prints a hypothesis `@reproduce_failure` blob.
- The tests are marked `slow` and excluded from `pytest` by default; `make test-differential`
  runs them (it needs Node). The engine calls are shared with the conformance runners
  (`backend/tests/chronology/ops.py`, `packages/chronology/bin/ops.ts`).
