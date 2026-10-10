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
    names that tests rely on, covering every feature the app has. Time (#56): four dimensions
    (Aetheria lasts 10^110 seconds), a calendar from every preset plus the custom "Imperial
    Reckoning" using every calendar feature (two regimes, one starting at an event; named, run and
    intercalary units; cycle and rules year patterns with an exception; a week continued across
    the reform and a reset ten-day count; backward, forward and prefix eras; overlays; formats),
    events typed in every calendar at every precision (era, regime and circa dates included) with
    every end kind, a chain of relative anchors, recurring events of every rule kind (calendar
    level and cycle periods, interval, filters, selectors, limits, exclusions) with referenced,
    modified and cancelled occurrences, a sub-event of an occurrence and an anchor to one.
  - **The bulk** (`small` and up): seeded random events with mentions, tags, aliases, hierarchy and
    private/spoiler content, and links between them. `small` ≈ 1k events / 3k links, `medium` ≈
    10k / 40k, `large` ≈ 100k events / 500k links (takes about 45 minutes to build, §4.0). Their starts are absolute, dates in three calendars at
    random precisions (some circa) or relative to a recent event (base or calendar offsets, start
    or end); their ends are every kind; every 100th event recurs (interval, yearly or monthly
    rules), and some series have a materialized occurrence.
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
| Calendar proposal apply on a large vault (the `large` sample world: 23k dependents, 1.6 GB; it backs the whole vault up first. Decided 2026-10-10; the preview stays < 5 s) | < 30 s |
| Full consistency scan (100k events; `tests/consistency/test_consistency_perf.py`) | < 10 s |
| Graph endpoint, 10k nodes | < 1 s |
| Timeline pan/zoom with 1,000 visible items | 60 fps (Playwright trace) |

Perf tests are marked `perf`; `make perf` runs the backend ones (`make bench` the chronology
ones). They are meant to run nightly and when a PR has the label `perf`, and regressions greater
than 25% should then fail the nightly run. Each feature's perf test checks its budget on synthetic
rows (uniform, fast to insert); `tests/test_sample_world_perf.py` checks the window, proposal and
scan budgets on the `large` sample world, whose data looks like a real vault (calendar dates,
relative chains, series, private content). `tests/sample_world.py` builds that world once and
caches it in `LORE_SAMPLE_CACHE` (default `backend/.pytest_cache/d/sample-worlds`), keyed by the
generator, the app version and the migrations; the tests work on a copy.
`LORE_PERF_SAMPLE_SIZE=small` runs them on a smaller world for a quick try.

### 4.0 Results

Measured 2026-10-10 on `large` (seed default: 100,365 events, 500,010 links, 1.6 GB `lore.db`)
on a Ryzen 7 5800X under WSL2 (16 GB), after #235–#238; "before" is 2026-10-09 (app version
0.1.0 + #56). Window times are the p95 of 20 runs, and vary by 10–20% between runs on this
machine.

| Operation | Before | Measured | Budget | |
|-----------|--------|----------|--------|-|
| Window, cold, 1/10 of the bulk (17,409 events) / 1/100 / 1/10,000 | 756 / 340 / 247 ms | 90 / 63 / 22 ms | < 150 ms | met |
| Window, cold, whole bulk / whole dimension / importance ≥ 4 | 2,288 / 2,326 / 701 ms | 319 / 329 / 108 ms | < 500 ms | met |
| Window, cold, as reader: 1/10 / whole bulk | 3,362 / 5,090 ms | 103 / 336 ms | < 150 / 500 ms | met |
| Window, cached (all of the above) | 6–37 ms | 3–23 ms | < 150 ms | met |
| Window, first since the app started (no series cached): 1/10 / whole bulk | (the cold ones above) | 157 / 974 ms | – | see below |
| Calendar proposal over 22,985 dependents: preview | 9.3 s | 4.7 s (5.1–5.7 s on a busy machine) | < 5 s | met, barely |
| Calendar proposal over 22,985 dependents: apply | 123 s | 22.2 s | < 30 s (was < 5 s) | met |
| Full consistency scan (50,358 findings) | > 15 min (stopped) | 7.9 s (9–10.7 s on a busy machine) | < 10 s | met |
| Enabling `core.event.duplicate_name_same_time` | about 28 min | 0.6–0.9 s | – | |
| Writing an event / a link (the generator, per write) | 18 / 9.6 ms | 14–27 / 1.2 ms | – | |
| Building `large` (`make_sample_vault.py`) | 2 h 05 min (45 min events, 80 min links) | 46 min (35.5 min events, 10.3 min links; the test suite ran beside it) | about 20 min before M3 | missed: the event service (#241) |
| Starting the app on `large`, to its first window | "10 min" | 1.5 s | < 10 s | met (it always was, see below) |

What the numbers rest on, and what is left:

- **Windows** (#236). A cold window's cost was the series (a query with a thousand ids, every
  occurrence computed again), the sub-event markers (every child of every kept event read) and,
  for readers, a visibility query per time point. Series now come through their partial index,
  the occurrences of series with at most the item budget in all are kept (`SERIES`, checked
  against the series' stored columns and compiled calendar on every use, so it survives
  unrelated writes; longer series are counted before they are expanded), markers are one probe
  per event and a reader's window asks once. A "cold" window above still has its series cached:
  the first window after the app starts, or after its series or their calendar changed, expands
  them (the "first" row). For readers, the policy's conditions on an entity's dimension and
  origin timeline are settled against the few shown ones (listed once per statement) before
  the per-row lookup, and are built once per process, not per statement (building them took
  longer than most reader queries run).
- **Garbage collection.** A full collection walked the 250k objects the app is made of, 85 ms
  in about one request out of ten: the p95 of every window. The app freezes them out of the
  collector at startup (`lore.app.lifespan`).
- **Consistency** (#235). The scan's time is now the sub-event rule resolving the extents of the
  50,032 sub-events that lie outside their parent in this world (half of all events: the
  generator puts children in one of the last five eras at random), about 6 s of the 9. A world
  with fewer findings scans in proportion: the uniform world of
  `tests/consistency/test_consistency_perf.py` takes 0.8 s. The findings of the scan are the
  ones the previous engine stored while the world was built (all 50,034 compared field by
  field).
- **Proposals** (#237). The preview is the dry-run propagation (2.6 s), formatting 47,674 dates
  (2.2 s, was 4.5) and storing and returning an 11 MB preview. The apply is the backup (12 s:
  `VACUUM INTO` 3.4 s, deflating 1.6 GB at the fastest level 7 s; was 29 s), the consistency
  check of 23k changed events (4 s, was 115 s) and the propagation (2.5 s). A backup that is a
  whole copy of the vault can't fit a 5 s budget at this size: stored without compression it
  still takes 5–6 s (and 1.6 GB per backup, never pruned); Zstandard would take 2 s for a
  smaller file, but most zip tools can't open such an entry. Decided 2026-10-10 (#237): the
  backup stays a deflated zip any tool opens, and an apply on a vault this large has its own
  budget of 30 s. On small vaults the apply keeps the 5 s of
  `tests/time/test_proposals_perf.py`: what grows is the backup, with the vault's size.
- **Startup** (#238). There was no 10-minute startup: the timestamps that suggested it were
  the maintenance scheduler's first pass (`CHECK_INTERVAL_SECONDS`, ten minutes after the app
  starts), which began a scheduled backup while the window test was still running. Opening
  `large` takes 40 ms, and the first window is served 1.5 s after the process starts (imports
  included). A scheduler pass never holds requests up (`tests/test_backups.py`).
- **Writes.** A link's check was 85% of writing it, an event's is now 7% (1 ms of 14): the rest
  is the event service itself (propagation, dependency edges, displays, search: 50 statements
  per event), and it grows from 14 ms in an empty vault to 27 ms at 100k events while `large`
  is built, 500 events per transaction. Written one per request, an event costs the same next to
  100k events as in an empty vault (`test_writes_cost_the_same_in_a_large_vault`). #241 looks at
  the event service.

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
