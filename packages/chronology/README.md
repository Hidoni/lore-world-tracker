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

Rules for code in this package:

- Use relative, extensionless imports and no path aliases (consumers compile this source with
  their own resolver).
- No DOM or Node APIs: the engine runs in the browser, in Vitest and, later, in workers.
- In-world time is `bigint`. Never `number`, `Date` or float math, except for pixel projection in
  `viewport`.
