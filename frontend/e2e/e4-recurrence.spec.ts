import { expect, test } from './fixtures'
import { createGregorianDimension, typeDay, yearStart } from './time-helpers'

// E4 (testing.md §3): a recurring event → materialize its 3rd occurrence → add a sub-event to it
// → the timeline marks that occurrence as having sub-events.
test('E4: recurring event → 3rd occurrence → sub-event → marker on the timeline', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')

  // Every year on 20 September from AD 1000.
  await page.getByRole('main').getByRole('link', { name: 'Event outline' }).click()
  await page.getByRole('button', { name: 'New event' }).click()
  const dialog = page.getByRole('dialog', { name: 'New event' })
  await dialog.getByLabel('Name').fill('Harvest Festival')
  await typeDay(dialog, 1000, 'September', 20)
  await dialog.getByRole('checkbox', { name: 'Repeats' }).check()
  const recurrence = dialog.getByRole('region', { name: 'Recurrence' })
  await expect(recurrence.getByLabel('Pattern')).toHaveValue(/.+/)
  await expect(recurrence.getByRole('region', { name: 'Next occurrences' })).toContainText(
    '20 September AD 1002',
  )
  await dialog.getByRole('button', { name: 'Create event' }).click()
  await page.getByRole('row', { name: 'Harvest Festival' }).getByRole('link').click()

  // Its 3rd occurrence, opened: materialized as an event of its own.
  const occurrences = page.getByRole('list', { name: 'Occurrences' })
  const third = occurrences.getByRole('listitem', { name: '3rd' })
  await expect(third).toContainText('20 September AD 1002')
  await third.getByRole('button', { name: 'Open' }).click()
  await expect(
    page.getByRole('heading', { name: 'Harvest Festival (20 September AD 1002)', level: 1 }),
  ).toBeVisible()
  await expect(page.getByRole('note')).toContainText('Occurrence #3 of Harvest Festival')
  const occurrence = /\/e\/([^/?]+)/.exec(page.url())?.[1]
  if (occurrence === undefined) throw new Error('not on the occurrence')

  // A sub-event of that occurrence.
  await page.getByRole('button', { name: 'Create sub-event' }).click()
  const sub = page.getByRole('dialog', { name: 'New event' })
  await sub.getByLabel('Name').fill('Grape Stomping')
  await typeDay(sub, 1002, 'September', 21)
  await sub.getByRole('button', { name: 'Create event' }).click()
  await expect(
    page.getByRole('list', { name: 'Sub-events' }).getByRole('link', { name: 'Grape Stomping' }),
  ).toBeVisible()

  // The timeline marks the 3rd occurrence (and only it) as having sub-events.
  await page.goto(
    `${lore.url()}/d/${dimension}/timeline?from=${yearStart(999)}&to=${yearStart(1005)}`,
  )
  const marked = page.locator('[data-item][data-sub-events]')
  await expect(marked).toHaveCount(1)
  await expect(marked).toHaveAttribute('data-occurrence', '2')
  await expect(marked).toHaveAttribute('title', /has sub-events/)
  await expect(page.locator('[data-item][data-occurrence]')).not.toHaveCount(0)
  expect(occurrence).not.toBe('')
})
