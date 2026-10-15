import type { Locator } from '@playwright/test'

import { expect, test } from './fixtures'
import { createGregorianDimension, yearStart } from './time-helpers'

const point = (t: bigint) => ({ anchor: { kind: 'absolute', t: t.toString() }, precision: 'base' })

async function absolute(picker: Locator, t: bigint) {
  await picker.getByRole('tab', { name: 'Absolute' }).click()
  await picker.getByRole('textbox', { name: 'Moment (seconds)' }).fill(t.toString())
}

// E8 (testing.md §3): a time traveler with two segments → the personal timeline lists what they
// lived in their own order, with their age. Vey lives years 10–30, vanishes and turns up in
// year 5 until year 8: the year-6 warning comes after the year-20 meeting in Vey's life.
test('E8: time traveler with two segments → personal timeline order and age', async ({
  page,
  lore,
}) => {
  const aetheria = await createGregorianDimension(page, lore, 'Aetheria')
  const { id: vey } = await lore.createEntity('character', 'Vey', { dimension_id: aetheria })
  const event = async (name: string, year: number) =>
    (
      await lore.createEntity('event', name, {
        dimension_id: aetheria,
        ext: { start: point(yearStart(year)), end: { kind: 'instant' } },
      })
    ).id
  const meeting = await event('The Meeting', 20)
  const warning = await event('The Warning', 6)

  // The worldline panel: a first segment, then the time-travel wizard.
  await page.goto(lore.url(vey))
  await expect(page.getByText(/Lives its lifespan in order/)).toBeVisible()
  await page.getByRole('button', { name: 'Add segment' }).click()
  const add = page.getByRole('dialog', { name: 'New segment' })
  await absolute(add.getByRole('group', { name: 'From' }), yearStart(10))
  await absolute(add.getByRole('group', { name: 'Until' }), yearStart(30))
  await add.getByRole('button', { name: 'Save segment' }).click()
  await expect(add).toBeHidden()
  const segments = page.getByRole('list', { name: 'Worldline segments' })
  await expect(segments.getByRole('listitem')).toHaveCount(1)

  await page.getByRole('button', { name: 'Time travel…' }).click()
  const wizard = page.getByRole('dialog', { name: 'Time travel' })
  await absolute(wizard.getByRole('group', { name: 'Leaves at' }), yearStart(30))
  await wizard.getByLabel('Departure event name').fill('The Vanishing')
  await absolute(wizard.getByRole('group', { name: 'Arrives at' }), yearStart(5))
  await absolute(wizard.getByRole('group', { name: 'Stays until (optional)' }), yearStart(8))
  await wizard.getByRole('button', { name: 'Travel' }).click()
  await expect(wizard).toBeHidden()
  await expect(segments.getByRole('listitem')).toHaveCount(2)

  // Vey takes part in both events; each is covered by one visit.
  await lore.link('core.participant', meeting, vey)
  await lore.link('core.participant', warning, vey)

  // The personal timeline: lived time on the axis, the jump as a break; the list in Vey's order.
  await page.getByRole('link', { name: 'Personal timeline', exact: true }).click()
  await expect(page.getByTestId('subjective-axis')).toBeVisible()
  await expect(page.getByTestId('jump-break')).toHaveCount(1)
  await page.getByRole('button', { name: 'List view' }).click()
  // Rows: the header, the meeting, the departure, the jump, the warning.
  const lived = page.getByRole('table', { name: 'Personal timeline' }).getByRole('row')
  await expect(lived.nth(1)).toContainText('The Meeting')
  await expect(lived.nth(1)).toContainText('10 years')
  await expect(lived.nth(2)).toContainText('The Vanishing')
  await expect(lived.nth(2)).toContainText('20 years')
  await expect(lived.nth(3)).toContainText('Jumps')
  await expect(lived.nth(4)).toContainText('The Warning')
  await expect(lived.nth(4)).toContainText('21 years')
})
