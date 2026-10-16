import { createRequire } from 'node:module'

import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

// Accessibility in a real browser (testing.md §3, frontend.md §11): axe-core on the main pages, in
// the light and the dark theme. The component tests run axe too, but jsdom paints nothing: contrast
// (WCAG AA) and target sizes are only judged here.
const AXE = createRequire(import.meta.url).resolve('axe-core/axe.min.js')

// axe is injected as a script, which the app's Content-Security-Policy would refuse.
test.use({ bypassCSP: true })

interface Violation {
  id: string
  impact: string | null
  help: string
  nodes: { target: string[] }[]
}

async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE })
  const found = await page.evaluate(async () => {
    const run = (window as unknown as { axe: { run: (options: unknown) => Promise<unknown> } }).axe
      .run
    const results = (await run({
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
      resultTypes: ['violations'],
    })) as { violations: Violation[] }
    return results.violations
  })
  return found
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map(
      (violation) =>
        `${violation.id}: ${violation.help} — ${violation.nodes
          .slice(0, 5)
          .map((node) => node.target.join(' '))
          .join(', ')}`,
    )
}

for (const scheme of ['light', 'dark'] as const) {
  test(`axe: no serious violations on the main pages (${scheme} theme)`, async ({ page, lore }) => {
    await page.emulateMedia({ colorScheme: scheme })
    const dimension = await lore.createDimension('Aetheria', {
      summary: 'A world of tides and clocks.',
      body: {
        type: 'doc',
        content: [
          { type: 'paragraph', content: [{ type: 'text', text: 'The tides follow the clock.' }] },
        ],
      },
    })
    const lantern = await lore.createEntity('misc', 'Lantern', {
      dimension_id: dimension.id,
      summary: 'A lamp that never goes out.',
    })
    await lore.link('core.related', lantern.id, dimension.id)

    const pages: [string, string][] = [
      ['vault home', lore.url()],
      ['dimension page', lore.url(dimension.id)],
      ['entity page', lore.url(lantern.id)],
      ['dimension overview', `${lore.url()}/d/${dimension.id}`],
      ['timeline', `${lore.url()}/d/${dimension.id}/timeline`],
      ['event outline', `${lore.url()}/d/${dimension.id}/events`],
      ['kind list', `${lore.url()}/k/misc`],
      ['search', `${lore.url()}/search?q=lamp`],
      ['graph', `${lore.url()}/m/graph`],
      ['settings', `${lore.url()}/settings`],
      ['consistency', `${lore.url()}/consistency`],
    ]
    const report: string[] = []
    for (const [name, url] of pages) {
      await page.goto(url)
      await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
      await page.waitForLoadState('networkidle')
      await expect(page.getByText(/^Loading/)).toHaveCount(0)
      report.push(...(await violations(page)).map((line) => `${name}: ${line}`))
    }
    expect(report, report.join('\n')).toEqual([])
  })
}
