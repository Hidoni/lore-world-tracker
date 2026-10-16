import { devices, type Page } from '@playwright/test'

import { expect, test } from './fixtures'

// Reader mode on a phone (frontend.md §13, the mobile check of #141). The author previews the
// vault as a reader; on a phone-sized touch screen every page checked keeps to the screen width,
// its controls are big enough to tap (WCAG 2.5.8: 24 × 24 px), bodies read at 16 px, and nothing
// offers editing.
test.use({ ...devices['Pixel 7'] })

/**
 * What a page measures (the "Lighthouse-style" check, frontend.md §13): how far it is wider than
 * the screen, the tap targets failing WCAG 2.5.8 (24 × 24 px, or a 24 px circle around a smaller
 * target touching no other target; links in running text are exempt) and the body text size.
 */
async function measure(page: Page) {
  return page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth - window.innerWidth
    const targets = [...document.querySelectorAll<HTMLElement>('button, [role="button"], a')]
      .map((element) => ({ element, box: element.getBoundingClientRect() }))
      // Hidden, or visually hidden until focused (the skip link).
      .filter(({ element, box }) => box.width > 1 && box.height > 1 && !element.matches('.sr-only'))
    const undersized = targets.filter(
      ({ element, box }) =>
        (box.width < 24 || box.height < 24) &&
        !(element.tagName === 'A' && element.closest('p, .rich-text') !== null),
    )
    const center = (box: DOMRect) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 })
    const touches = (c: { x: number; y: number }, box: DOMRect) => {
      const dx = Math.max(box.left - c.x, 0, c.x - box.right)
      const dy = Math.max(box.top - c.y, 0, c.y - box.bottom)
      return dx * dx + dy * dy < 12 * 12
    }
    const small = undersized
      .filter(({ element, box }) => {
        const c = center(box)
        return targets.some((other) => {
          if (other.element === element || other.element.contains(element)) return false
          if (element.contains(other.element)) return false
          if (undersized.some((u) => u.element === other.element)) {
            const o = center(other.box)
            return Math.hypot(o.x - c.x, o.y - c.y) < 24
          }
          return touches(c, other.box)
        })
      })
      .map(({ element }) => element.getAttribute('aria-label') ?? element.textContent.trim())
    const body = document.querySelector('.rich-text p')
    const bodyFont = body === null ? null : parseFloat(getComputedStyle(body).fontSize)
    return { overflow, small, bodyFont }
  })
}

const EDITING = /^(new|add|create|edit|rename|delete|move to trash|upload|save)\b/i

test('reader mode on a phone: no editing, fits the screen, tappable, readable', async ({
  page,
  lore,
}) => {
  const paragraph = (text: string) => ({ type: 'paragraph', content: [{ type: 'text', text }] })
  const dimension = await lore.createDimension('Aetheria', {
    summary: 'A world of tides and clocks.',
    body: {
      type: 'doc',
      content: [
        paragraph('The tides of Aetheria follow the great clock of Varn.'),
        {
          type: 'visibilityBlock',
          attrs: { level: 'spoiler' },
          content: [paragraph('The clock is running down.')],
        },
      ],
    },
  })
  const secret = await lore.createEntity('misc', 'The traitor', {
    dimension_id: dimension.id,
    visibility: 'spoiler',
    summary: 'Someone close to the queen.',
  })

  await page.goto(lore.url())
  await page.getByRole('button', { name: 'Preview as reader' }).click()
  await expect(page.getByRole('region', { name: 'Recently updated' })).toBeVisible()

  const pages: [string, string][] = [
    ['home', lore.url()],
    ['dimension', `/v/${lore.vault.id}/d/${dimension.id}`],
    ['entity', lore.url(dimension.id)],
    ['spoiler entity', lore.url(secret.id)],
    ['timeline', `/v/${lore.vault.id}/d/${dimension.id}/timeline`],
  ]
  const results: Record<string, Awaited<ReturnType<typeof measure>>> = {}
  for (const [name, url] of pages) {
    await page.goto(url)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    results[name] = await measure(page)
    const editing = await page.getByRole('button').evaluateAll((buttons, pattern) => {
      const re = new RegExp(pattern, 'i')
      return buttons
        .map((b) => b.getAttribute('aria-label') ?? b.textContent.trim())
        .filter((label) => re.test(label))
    }, EDITING.source)
    expect(editing, `${name}: editing controls`).toEqual([])
  }
  console.log(JSON.stringify(results, null, 2))
  for (const [name, found] of Object.entries(results)) {
    expect(found.overflow, `${name}: wider than the screen`).toBeLessThanOrEqual(0)
    expect(found.small, `${name}: targets under 24 px`).toEqual([])
  }
  expect(results.entity?.bodyFont).toBeGreaterThanOrEqual(16)

  // Spoilers fold: the spoiler page asks first, the spoiler block opens on a tap.
  await page.goto(lore.url(secret.id))
  await expect(page.getByText('Someone close to the queen.')).toBeHidden()
  await page.getByRole('button', { name: 'Show spoilers' }).tap()
  await expect(page.getByText('Someone close to the queen.')).toBeVisible()
  await page.goto(lore.url(dimension.id))
  await expect(page.getByText('The clock is running down.')).toBeHidden()
  await page.getByText('Spoiler', { exact: true }).tap()
  await expect(page.getByText('The clock is running down.')).toBeVisible()

  // The navigation is a drawer.
  await page.getByRole('button', { name: 'Open navigation' }).tap()
  await expect(page.getByRole('dialog', { name: 'Navigation' })).toBeVisible()
})
