# @lore/chronology

The TypeScript time engine. Its behavior is specified in `docs/architecture/chronology-engine.md`
and `recurrence.md`, and checked against the shared vectors in `spec/chronology/conformance/`
(the Python twin lives in `backend/src/lore/chronology`).

## Consumed from source

`package.json` `exports` points at `src/index.ts`, not at compiled output. Inside the npm
workspace, Vite, Vitest and `tsc` (with `moduleResolution: "bundler"`) all compile the package's
TypeScript directly, so there is no build step to run or forget before starting the frontend, and
editor go-to-definition lands in the real source. The package is `private` and never published.
`npm run build` therefore only type-checks it. If the package ever needs to be published, add a
`dist` build and conditional exports at that point.

## Generated files

`npm run gen:schema` (part of `make gen`) generates two files from
`spec/chronology/schema/bundle.json`, which is exported from the Python Pydantic models. Never edit
them by hand; `make check-chronology` fails on drift.

- `src/schema.gen.ts`: the chronology document types (calendar definitions, time points,
  recurrence rules, …). Engine code uses these and never declares its own copies.
- `src/calendar-schema.gen.ts`: the JSON Schema definitions of calendar definitions and compile
  contexts (annotations stripped). `validateCalendar` checks raw documents against them
  (`src/calendar/schema-check.ts`), so both engines report the same structural errors
  (chronology-engine.md §11).

## Modules

| Module | Contents |
|--------|----------|
| `numbers.ts` | exact numeric utilities (§2) |
| `calendar/` | `validateCalendar`/`compileCalendar` (§4, §11), `toFields`/`fromFields`/`normalizeFields`/`options` (§5.3–§5.7, §6), `unitBounds`/`ordinal`/`fromOrdinal` (§5.8), `cycleValue`/`eraOf`/`overlayPhase`/`nextPhaseAt` (§8), `add`/`diff`/`durationUpperBound` (§9), `formatDate`/`formatSpan`/`formatAbsolute` (§10) |
| `recurrence/` | `validateRule`, `expand`, `occurrence`, `occurrenceAt`, `nextOccurrences`, `occurrenceNumber`, `countInWindow`, `seriesBounds` (`recurrence.md` §2–§5, §9) |
| `presets.ts` | `instantiatePreset`, `absoluteMoments` (§13) |
| `viewport/` | the separate entry point `@lore/chronology/viewport`: `toPx`/`fromPx`/`zoomAt`/`panBy`/`fit`/`clamp`, `ticks`, `tileFor`/`tileBounds` (§12, `frontend.md` §9.2) |
| `preset-library.ts` | the separate entry point `@lore/chronology/presets` (below) |

## Presets

The preset calendars live in `spec/chronology/presets/*.json`, the same files the server reads at
runtime (`LORE_SPEC_DIR`). `@lore/chronology/presets` (`src/preset-library.ts`, mapped in
`package.json` `exports`) imports them statically as JSON modules and exports `PRESETS` (by id)
plus `instantiatePreset`. The app bundles them at build time: Vite inlines the JSON into the chunk
that imports the entry point, so only the code that creates calendars (the dimension wizard) pays
for them, and a lazy `import('@lore/chronology/presets')` keeps them out of the initial load. The
Docker image's frontend stage copies `spec/` for this reason. Adding a preset means adding its JSON
file and one import line in `preset-library.ts`; the TS tests check that the bundled set equals
the required presets.

## Bundle size

Target: under 40 kB gzip for the whole package at the end of M1. Measure the minified ESM bundle
of the package entry point with the workspace's bundler (rolldown, which Vite uses):

```bash
npx rolldown packages/chronology/src/index.ts --minify --format esm | gzip -9 | wc -c
```

| After | Whole package (min + gzip) |
|-------|----------------------------|
| #9 numeric utilities | 1.4 kB |
| #23 compilation and conversions (incl. ≈2.9 kB of generated schema) | 12.2 kB |
| #24–#25 navigation, cycles, eras, overlays, arithmetic, formatting | 20.4 kB |
| #26 recurrence | 28.1 kB |
| `@lore/chronology/presets` entry point (8 presets + instantiation) | 7.9 kB |
| `@lore/chronology/viewport` entry point, standalone (#28; most of it is calendar code shared with the main entry) | 7.6 kB |

## Tests

`npm run test` runs the unit tests in `src/` and the conformance runner `test/conformance.test.ts`
(every vector in `spec/chronology/conformance/`; pending ops are listed there with the issue that
implements them).

## Rules

Rules for code in this package:

- Use relative, extensionless imports and no path aliases (consumers compile this source with
  their own resolver).
- No DOM or Node APIs: the engine runs in the browser, in Vitest and, later, in workers. ESLint
  rejects `node:*` imports in `src/` (tests, `test/` and `scripts/` may use Node).
- In-world time is `bigint`. Never `number`, `Date` or float math, except for pixel projection in
  `viewport`.

## Benchmarks

`npm run bench -w @lore/chronology` runs `test/**/*.bench.ts` with Vitest's benchmark runner
(`ticks.bench.ts` asserts the < 2 ms tick target). Benchmarks are kept out of `npm test` and
`make check`: timings are noisy, and coverage instrumentation skews them.
