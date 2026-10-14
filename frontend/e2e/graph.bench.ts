import { expect, test, type Page } from '@playwright/test'

// The graph benchmark (docs/modules/graph.md, M8 exit criterion "graph of 10k nodes interactive").
// Runs against a vault of 10k entities and 50k links (BENCH_VAULT, made by
// backend/scripts/make_graph_bench_vault.py); `make bench-graph` sets it all up.
//
// For each case it loads the graph page, then pans and zooms for a few seconds while counting
// animation frames. The frame intervals tell how smooth that was: an interval is one frame the
// browser drew, so a long one is a stall the user sees. A case passes when the median interval is
// at most MEDIAN_MS and the 95th percentile at most P95_MS, and the page drew within LOAD_MS.

const MEDIAN_MS = 34 // ~30 fps
const P95_MS = 100
const LOAD_MS = 8000

interface Result {
  case: string
  nodes: number
  edges: number
  loadMs: number
  frames: number
  fps: number
  medianMs: number
  p95Ms: number
  worstMs: number
  pass: boolean
}

const vault = process.env.BENCH_VAULT ?? ''

interface Body {
  nodes: unknown[]
  edges: unknown[]
  truncated: boolean
}

async function graphPage(page: Page, showMore: boolean) {
  const started = Date.now()
  const first = page.waitForResponse((r) => r.url().includes('/m/graph/graph'))
  await page.goto(`/v/${vault}/m/graph`)
  let body = (await (await first).json()) as Body
  if (showMore && body.truncated) {
    const more = page.waitForResponse((r) => r.url().includes('limit=20000'))
    await page.getByRole('button', { name: /^Show up to/ }).click()
    body = (await (await more).json()) as Body
  }
  const canvas = page.getByTestId('graph-canvas')
  await expect(canvas.locator('canvas').first()).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0) // WebGL works
  // A frame drawn after the data: the page is up.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)))
  return { loadMs: Date.now() - started, nodes: body.nodes.length, edges: body.edges.length }
}

/** Pans and zooms for about 4 s; the animation frame intervals meanwhile. */
async function interact(page: Page): Promise<number[]> {
  const box = await page.getByTestId('graph-canvas').boundingBox()
  if (box === null) throw new Error('no canvas')
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
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  const until = Date.now() + 4000
  let step = 0
  while (Date.now() < until) {
    await page.mouse.move(x, y)
    await page.mouse.down()
    for (let i = 1; i <= 10; i++) await page.mouse.move(x + i * 12, y + i * 6)
    await page.mouse.up()
    await page.mouse.wheel(0, step % 2 === 0 ? -240 : 240)
    step += 1
  }
  return page.evaluate(() => (window as unknown as { benchFrames: number[] }).benchFrames)
}

function record(
  name: string,
  loaded: { loadMs: number; nodes: number; edges: number },
  frames: number[],
) {
  const sorted = frames.slice(1).sort((a, b) => a - b)
  const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))] ?? 0
  const total = sorted.reduce((sum, value) => sum + value, 0)
  const result: Result = {
    case: name,
    ...loaded,
    frames: sorted.length,
    fps: Math.round((sorted.length / total) * 1000 * 10) / 10,
    medianMs: Math.round(at(0.5) * 10) / 10,
    p95Ms: Math.round(at(0.95) * 10) / 10,
    worstMs: Math.round(sorted.at(-1) ?? 0),
    pass: false,
  }
  result.pass = result.medianMs <= MEDIAN_MS && result.p95Ms <= P95_MS && result.loadMs <= LOAD_MS
  return result
}

test.beforeAll(() => {
  if (vault === '') throw new Error('BENCH_VAULT is not set: run `make bench-graph`')
})

/** The WebGL renderer the page draws with: a GPU, or a software fallback (SwiftShader, llvmpipe). */
async function renderer(page: Page): Promise<string> {
  return page.evaluate(() => {
    const gl = document.createElement('canvas').getContext('webgl')
    const info = gl?.getExtension('WEBGL_debug_renderer_info')
    return gl && info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : 'unknown'
  })
}

function report(result: Result, gpu: string) {
  console.log(
    `${result.pass ? 'PASS' : 'FAIL'} ${result.case}: ${result.nodes} nodes, ${result.edges} edges, ` +
      `drawn in ${result.loadMs} ms; ${result.fps} fps, median frame ${result.medianMs} ms, ` +
      `95th percentile ${result.p95Ms} ms, worst ${result.worstMs} ms (${gpu}). Pass: median ≤ ` +
      `${MEDIAN_MS} ms, 95th percentile ≤ ${P95_MS} ms, drawn within ${LOAD_MS} ms.`,
  )
  expect(result.pass, JSON.stringify(result)).toBe(true)
}

for (const [name, showMore] of [
  ['default limit (5,000 nodes)', false],
  ['show more (up to 20,000 nodes)', true],
] as const) {
  test(`${name}, layout frozen`, async ({ page }) => {
    const loaded = await graphPage(page, showMore)
    await page.getByRole('button', { name: 'Freeze' }).click()
    const frames = await interact(page)
    // Still the graph: panning and zooming must not open an entity.
    expect(new URL(page.url()).pathname).toMatch(/\/m\/graph$/)
    report(record(`${name}, frozen`, loaded, frames), await renderer(page))
  })

  test(`${name}, layout running`, async ({ page }) => {
    const loaded = await graphPage(page, showMore)
    await expect(page.getByRole('button', { name: 'Stop the layout' })).toBeVisible()
    const frames = await interact(page)
    // Still the graph: panning and zooming must not open an entity.
    expect(new URL(page.url()).pathname).toMatch(/\/m\/graph$/)
    report(record(`${name}, layout running`, loaded, frames), await renderer(page))
  })
}
