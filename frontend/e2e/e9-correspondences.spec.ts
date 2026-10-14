import type { Locator } from '@playwright/test'

import { expect, test } from './fixtures'
import { createGregorianDimension, yearStart } from './time-helpers'

const point = (t: bigint) => ({ anchor: { kind: 'absolute', t: t.toString() }, precision: 'base' })

async function absolute(picker: Locator, t: bigint) {
  await picker.getByRole('tab', { name: 'Absolute' }).click()
  await picker.getByRole('textbox', { name: 'Moment (seconds)' }).fill(t.toString())
}

// E9 (testing.md §3): a correspondence between two dimensions → "concurrently in" on an event
// page. Dream time runs twice as fast: years 100–200 of Aetheria are years 500–700 there.
test('E9: correspondence between two dimensions → concurrently in on an event page', async ({
  page,
  lore,
}) => {
  const dream = await createGregorianDimension(page, lore, 'Dreamrealm')
  const aetheria = await createGregorianDimension(page, lore, 'Aetheria')
  const { id: festival } = await lore.createEntity('event', 'Festival of Mirrors', {
    dimension_id: aetheria,
    ext: { start: point(yearStart(150)), end: { kind: 'instant' } },
  })

  // The dimension overview: a new correspondence with two sync points.
  await page.goto(`${lore.url()}/d/${aetheria}`)
  await page.getByRole('button', { name: 'New correspondence' }).click()
  const editor = page.getByRole('dialog', { name: 'New correspondence' })
  await editor.getByLabel('Name').fill('The Drowned Gate')
  await editor.getByLabel('Corresponds with').selectOption(dream)
  const first = editor.getByRole('group', { name: 'Sync point 1' })
  await absolute(first.getByRole('group', { name: 'In Aetheria' }), yearStart(100))
  await absolute(first.getByRole('group', { name: 'In Dreamrealm' }), yearStart(500))
  await editor.getByRole('button', { name: 'Add sync point' }).click()
  const second = editor.getByRole('group', { name: 'Sync point 2' })
  await absolute(second.getByRole('group', { name: 'In Aetheria' }), yearStart(200))
  await absolute(second.getByRole('group', { name: 'In Dreamrealm' }), yearStart(700))
  await expect(editor.getByTestId('mapping-chart')).toBeVisible()
  await editor.getByRole('button', { name: 'Save correspondence' }).click()
  await expect(editor).toBeHidden()
  const list = page.getByRole('list', { name: 'Correspondences' })
  await expect(list.getByText('The Drowned Gate')).toBeVisible()
  await expect(page.getByTestId('connected-dimensions')).toBeVisible()

  // The event page: the festival starts around year 600 of the Dreamrealm.
  await page.goto(lore.url(festival))
  const concurrently = page.getByTestId('concurrently')
  await expect(concurrently.getByRole('link', { name: 'Dreamrealm' })).toBeVisible()
  await expect(concurrently).toContainText(/AD (599|600)/)
})
