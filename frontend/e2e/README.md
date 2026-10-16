# End-to-end journeys

Playwright against the real app (`testing.md` §3). `make e2e` (`scripts/e2e.sh`) builds the SPA,
serves it from `lore serve` on a temp data dir and runs every `*.spec.ts` here with
`E2E_BASE_URL`; without it the specs skip. Extra arguments go to Playwright, e.g.
`scripts/e2e.sh --headed e5` or `SKIP_BUILD=1 scripts/e2e.sh e5` after a first build.

## Writing a journey

Import `test` and `expect` from `./fixtures`, not from `@playwright/test`:

```ts
import { expect, test } from './fixtures'

test('E5: …', async ({ page, lore }) => {
  const a = await lore.createDimension('Aetheria') // fast setup through the API
  await page.goto(lore.url(a.id)) // then drive the UI for what the journey checks
})
```

The `lore` fixture creates a **fresh vault per test** (moved to the data trash afterwards), so
tests never see each other's data. Its helpers:

| Helper                                                              | Does                                                                                     |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `lore.vault`, `lore.base`, `lore.url(id?)`                          | the vault, its API base, the vault or entity page                                        |
| `createEntity(kind, name, extra?)`, `createDimension(name, extra?)` | create (dimensions get a time spec); only dimensions have bodies until modules add kinds |
| `entity(id)`, `updateEntity(id, change)`                            | read; change at the current revision                                                     |
| `link(type, source, target, extra?)`                                | create a link                                                                            |
| `fact(entityId, body)`                                              | add a fact (`core.exists` for a lifespan, a temporal field's value)                      |
| `backlinks(id)`                                                     | the entities linking to or mentioning `id`                                               |
| `findByName(name)`                                                  | the id of the entity with that exact name (quick search)                                 |

Writes send `X-Lore-Client: web` like the SPA.

Prefer roles and labels (`getByRole`, `getByLabel`) to CSS. Wait on what the user sees (`Saved`,
a heading) or on the response (`page.waitForResponse`), never on timeouts.

## Failures

A failed test keeps its **trace** (`trace: 'retain-on-failure'`) in `frontend/test-results/`;
CI uploads that folder as the `playwright-report` artifact. Open one with
`npx playwright show-trace <trace.zip>`. `scripts/e2e.sh` prints the server log when a run fails.

## Journeys

| #     | Spec                         | Covers                                                                                                                                                                       |
| ----- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| smoke | `smoke.spec.ts`              | the shell loads; create and reopen a vault                                                                                                                                   |
| E5    | `e5-linking.spec.ts`         | a `[[` link in the editor, the backlink on the target, rename relabels the link                                                                                              |
| E6    | `e6-relationships.spec.ts`   | a marriage valid from a wedding to a death, the family tree, the time cursor changes who is married and alive                                                                |
| E7    | `e7-branches.spec.ts`        | "What if…" branches at an assassination, the war spanning it ends earlier in the branch, compare mode shows both timelines, the divergence and the shorter war               |
| E8    | `e8-worldlines.spec.ts`      | a first worldline segment and the Time travel… wizard, then the personal timeline lists what the traveler lived in their order (meeting, departure, jump, warning) with ages |
| E9    | `e9-correspondences.spec.ts` | a correspondence with two sync points from the dimension overview, then "Concurrently in" on an event page                                                                   |
| E10   | `e10-maps.spec.ts`           | a map uploaded in "New map", a child location pinned from the tray, drill-down and back, then the time cursor hides the pin of a destroyed city                              |
| graph | `graph.spec.ts`              | the graph page draws with WebGL while the layout runs, pans and zooms, freezes, finds and opens an entity                                                                    |
