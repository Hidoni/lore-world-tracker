import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { yearStart } from './time-helpers'

// The keyboard-only walkthrough (testing.md §3, R-NFR-3): the main journeys without a mouse. Every
// control is reached with Tab (`tabTo` fails when it can't be), and operated with keys.

/** Presses Tab (Shift+Tab with `back`) until `target` has the focus; fails past `max` presses. */
async function tabTo(page: Page, target: Locator, { back = false, max = 80 } = {}) {
  for (let presses = 0; presses < max; presses++) {
    if (await target.evaluate((element) => element === document.activeElement).catch(() => false))
      return
    await page.keyboard.press(back ? 'Shift+Tab' : 'Tab')
  }
  throw new Error(`not reachable with Tab in ${String(max)} presses: ${target.toString()}`)
}

/**
 * Runs a palette command or opens an entity: types into the command palette, then moves with ↓ to
 * the option whose name starts with `choice` (not the "Search for …" one) and presses Enter.
 */
async function palette(page: Page, text: string, choice: string) {
  await page.keyboard.press('ControlOrMeta+k')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox')).toBeFocused()
  await page.keyboard.type(text)
  const escaped = choice.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const target = dialog.getByRole('option', { name: new RegExp(`^${escaped}`) }).first()
  await expect(target).toBeVisible()
  for (let step = 0; step < 20; step++) {
    if ((await target.getAttribute('aria-selected')) === 'true') break
    await page.keyboard.press('ArrowDown')
  }
  await expect(target).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
}

const point = (t: bigint) => ({ anchor: { kind: 'absolute', t: t.toString() }, precision: 'base' })

test('keyboard only: create a dimension, find and rename an entity, timeline, outline, shortcuts', async ({
  page,
  lore,
}) => {
  // 1. The vault home: skip to the content, then the dimension wizard.
  await page.goto(lore.url())
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await tabTo(page, page.getByRole('button', { name: 'Create dimension' }))
  await page.keyboard.press('Enter')
  const wizard = page.getByRole('dialog', { name: 'New dimension' })
  await tabTo(page, wizard.getByLabel('Name'))
  await page.keyboard.type('Aetheria')
  const next = async () => {
    await tabTo(page, wizard.getByRole('button', { name: 'Next' }))
    await page.keyboard.press('Enter')
  }
  await next()
  await next() // seconds
  await tabTo(page, wizard.getByRole('button', { name: '10,000 years' }))
  await page.keyboard.press('Enter')
  await next()
  const preset = wizard.getByLabel('Preset', { exact: true })
  await tabTo(page, preset)
  await preset.press('G') // a native select picks the option starting with the letter
  await expect(wizard.getByRole('region', { name: 'Preview' })).toContainText('1 January AD 1')
  await next()
  await tabTo(page, wizard.getByRole('button', { name: 'Create dimension' }))
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  const dimension = /\/d\/([^/?]+)/.exec(page.url())?.[1] ?? ''

  // Content to walk through.
  const lantern = await lore.createEntity('misc', 'Lantern', { dimension_id: dimension })
  const event = async (name: string, year: number) =>
    lore.createEntity('event', name, {
      dimension_id: dimension,
      ext: { start: point(yearStart(year)), end: { kind: 'instant' } },
    })
  await event('The Founding', 10)
  await event('The Flood', 20)

  // 2. The palette finds the entity; rename it with the keyboard.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await palette(page, 'Lantern', 'Lantern')
  await expect(page.getByRole('heading', { name: 'Lantern', level: 1 })).toBeVisible()
  await tabTo(page, page.getByRole('button', { name: 'Rename' }))
  await page.keyboard.press('Enter')
  await page.keyboard.press('ControlOrMeta+a')
  await page.keyboard.type('The Eternal Lantern')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'The Eternal Lantern', level: 1 })).toBeVisible()
  expect((await lore.entity(lantern.id)).name).toBe('The Eternal Lantern')

  // 3. The shortcut sheet opens with ?, closes with Esc, and gives the focus back.
  const before = await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 80))
  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(sheet).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  expect(await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 80))).toBe(before)

  // 4. The timeline: reach it with Tab, select the next item with ↓, open it with Enter.
  await palette(page, 'timeline', 'Open the timeline of Aetheria')
  const timeline = page.getByRole('application', { name: 'Timeline' })
  await expect(timeline).toBeVisible()
  await tabTo(page, timeline)
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowDown')
  await expect(page.getByTestId('timeline-status')).toContainText('selected: The Founding')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'The Founding', level: 1 })).toBeVisible()

  // 5. The event outline: rows with the arrows, Enter opens.
  await palette(page, 'outline', 'Open the event outline of Aetheria')
  const outline = page.getByRole('treegrid')
  await expect(outline).toBeVisible()
  await tabTo(page, outline.getByRole('row').nth(1))
  await page.keyboard.press('ArrowDown')
  await expect(outline.getByRole('row').nth(2)).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'The Flood', level: 1 })).toBeVisible()
})
