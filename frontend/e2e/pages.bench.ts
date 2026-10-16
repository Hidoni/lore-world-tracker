import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// The page benchmarks (testing.md §4, frontend.md §12): the entity page and the timeline on the
// sample world (BENCH_VAULT, made by backend/scripts/make_sample_vault.py; `make bench-pages` sets
// it all up).
//
// Entity page: the time from navigating to it until its heading shows and its reads are done
// (the page is interactive), cold (a full load) and in-app (a client-side navigation, the usual
// case). Timeline: pans and zooms for a few seconds over the bulk of the world while counting
// animation frames, like graph.bench.ts.

const ENTITY_MS = 300
const MEDIAN_FRAME_MS = 1000 / 60 + 1 // 60 fps (a frame at the display's refresh rate)
const P95_FRAME_MS = 34

const vault = process.env.BENCH_VAULT ?? ''
const api = `/api/v1/vaults/${vault}`

test.beforeAll(() => {
  if (vault === '') throw new Error('BENCH_VAULT is not set: run `make bench-pages`')
})

async function entityId(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.get(`${api}/search/quick`, { params: { q: name } })
  const { items } = (await response.json()) as { items: { entity_id: string; name: string }[] }
  const hit = items.find((item) => item.name === name)
  if (hit === undefined) throw new Error(`no entity ${name}`)
  return hit.entity_id
}

function percentile(values: number[], q: number): number {
  const sorted = values.slice().sort((a, b) => a - b)
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))] ?? 0
}

interface Watch {
  expect: string
  start: number
  content: number | null
  drawn: number | null
}

interface Times {
  content: number
  drawn: number
}

/**
 * Watches every animation frame for the page being up, on the page's clock: an `h1` named as
 * expected and no text starting with "Loading" (`content`: outside the panels that draw a
 * visualization, which finish after the page is usable; `drawn`: anywhere). Each is the first frame
 * of the current such stretch, null while not up.
 */
function watchReady() {
  const VISUALIZATIONS = ['Family tree', 'Local graph', 'Map']
  const state: Watch = { expect: '', start: 0, content: null, drawn: null }
  ;(window as unknown as { benchWatch: Watch }).benchWatch = state
  const tick = (now: number) => {
    const headed = [...document.querySelectorAll('h1')].some(
      (h) => h.textContent.trim() === state.expect,
    )
    // What says "Loading…": the elements holding text that starts with it.
    const found = document.evaluate(
      "//body//text()[starts-with(normalize-space(.), 'Loading')]",
      document,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null,
    )
    const loading: Element[] = []
    for (let i = 0; i < found.snapshotLength; i++) {
      const parent = found.snapshotItem(i)?.parentElement
      if (parent) loading.push(parent)
    }
    const drawn = headed && loading.length === 0
    const content =
      headed &&
      loading.every((element) =>
        VISUALIZATIONS.includes(element.closest('section')?.getAttribute('aria-label') ?? ''),
      )
    state.drawn = drawn ? (state.drawn ?? now) : null
    state.content = content ? (state.content ?? now) : null
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

/** The reads of the visualizations (and code, which shows as "Loading…" while it loads). */
const LATE = /\/m\/graph\/graph|\/family-tree|\/m\/maps\/|\/assets\//

/**
 * Navigates (a full load, or in the app through the router) and returns when the page was up, on
 * the page's own clock (not Playwright's polling): its heading shown, nothing "Loading…", and the
 * last read it made finished (Resource Timing). `content` leaves the visualizations out.
 */
async function open(page: Page, path: string, name: string, cold: boolean): Promise<Times> {
  if (cold) {
    await page.goto(path)
  } else {
    await page.evaluate(
      ([to, expected]) => {
        const watch = (window as unknown as { benchWatch: Watch }).benchWatch
        watch.expect = expected
        watch.start = performance.now()
        watch.content = null
        watch.drawn = null
        window.history.pushState(null, '', to)
        window.dispatchEvent(new PopStateEvent('popstate'))
      },
      [path, name] as const,
    )
  }
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByText(/^Loading/)).toHaveCount(0)
  await page.waitForLoadState('networkidle')
  return page.evaluate((late) => {
    const watch = (window as unknown as { benchWatch: Watch }).benchWatch
    const reads = performance
      .getEntriesByType('resource')
      .filter((entry) => entry.startTime >= watch.start) as PerformanceResourceTiming[]
    const end = (entries: PerformanceResourceTiming[]) =>
      Math.max(0, ...entries.map((entry) => entry.responseEnd))
    const pattern = new RegExp(late)
    return {
      content: Math.round(
        Math.max(
          watch.content ?? Infinity,
          end(reads.filter((entry) => !pattern.test(entry.name))),
        ) - watch.start,
      ),
      drawn: Math.round(Math.max(watch.drawn ?? Infinity, end(reads)) - watch.start),
    }
  }, LATE.source)
}

for (const name of ['Ilsa the Tidebound', 'Aetheria']) {
  test(`entity page: ${name}`, async ({ page, request }) => {
    const id = await entityId(request, name)
    const path = `/v/${vault}/e/${id}`
    await page.addInitScript(watchReady)
    await page.addInitScript((expected) => {
      ;(window as unknown as { benchWatch: Watch }).benchWatch.expect = expected
    }, name)
    const cold: Times[] = []
    const warm: Times[] = []
    for (let run = 0; run < 5; run++) {
      cold.push(await open(page, path, name, true))
      await page.goto(`/v/${vault}`)
      await page.waitForLoadState('networkidle')
      warm.push(await open(page, path, name, false))
    }
    const p95 = (times: Times[], key: keyof Times) =>
      percentile(
        times.map((time) => time[key]),
        0.95,
      )
    const pass = p95(warm, 'content') <= ENTITY_MS
    const list = (times: Times[], key: keyof Times) => times.map((time) => time[key]).join(', ')
    console.log(
      `${pass ? 'PASS' : 'FAIL'} entity page ${name}: in the app p95 ${p95(warm, 'content')} ms ` +
        `(${list(warm, 'content')}), with its visualizations drawn ${p95(warm, 'drawn')} ms; ` +
        `full load p95 ${p95(cold, 'content')} ms (${list(cold, 'content')}), drawn ` +
        `${p95(cold, 'drawn')} ms. Pass: in the app ≤ ${ENTITY_MS} ms.`,
    )
    expect(pass, JSON.stringify({ cold, warm })).toBe(true)
  })
}

/** Pans and zooms the timeline for about 4 s; the animation frame intervals meanwhile. */
async function interact(page: Page): Promise<{ frames: number[]; items: number[] }> {
  const box = await page.getByRole('application', { name: 'Timeline' }).boundingBox()
  if (box === null) throw new Error('no timeline')
  await page.evaluate(() => {
    const frames: number[] = []
    ;(window as unknown as { benchFrames: number[] }).benchFrames = frames
    let last = performance.now()
    const tick = (now: number) => {
      frames.push(now - last)
      last = now
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
  const visible = () =>
    page
      .getByTestId('lanes-layer')
      .evaluate((layer) => layer.querySelectorAll('[aria-label]').length)
  const items: number[] = []
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  const until = Date.now() + 4000
  let step = 0
  while (Date.now() < until) {
    await page.mouse.move(x, y)
    await page.mouse.down()
    for (let i = 1; i <= 10; i++) await page.mouse.move(x + (step % 2 === 0 ? i : -i) * 12, y)
    await page.mouse.up()
    await page.keyboard.down('Control')
    await page.mouse.wheel(0, step % 2 === 0 ? -120 : 120)
    await page.keyboard.up('Control')
    items.push(await visible())
    step += 1
  }
  const frames = await page.evaluate(
    () => (window as unknown as { benchFrames: number[] }).benchFrames,
  )
  return { frames: frames.slice(1), items }
}

test('timeline: pan and zoom over the bulk', async ({ page, request }) => {
  const dimension = await entityId(request, 'Aetheria')
  const started = Date.now()
  await page.goto(`/v/${vault}/d/${dimension}/timeline`)
  await expect(page.getByRole('application', { name: 'Timeline' })).toBeVisible()
  await expect(page.getByTestId('timeline-status')).toContainText(/\d+ events?/)
  await page.waitForLoadState('networkidle')
  const loadMs = Date.now() - started
  const { frames, items } = await interact(page)
  const median = Math.round(percentile(frames, 0.5) * 10) / 10
  const p95 = Math.round(percentile(frames, 0.95) * 10) / 10
  const fps = Math.round((frames.length / frames.reduce((a, b) => a + b, 0)) * 10000) / 10
  const pass = median <= MEDIAN_FRAME_MS && p95 <= P95_FRAME_MS
  console.log(
    `${pass ? 'PASS' : 'FAIL'} timeline: ${Math.min(...items)}–${Math.max(...items)} items ` +
      `on screen, drawn in ${loadMs} ms; ${fps} fps, median frame ${median} ms, 95th ` +
      `percentile ${p95} ms (${await page.getByTestId('timeline-status').textContent()}). ` +
      `Pass: median ≤ ${MEDIAN_FRAME_MS.toFixed(1)} ms, 95th percentile ≤ ${P95_FRAME_MS} ms.`,
  )
  expect(pass, JSON.stringify({ median, p95, fps })).toBe(true)
})
