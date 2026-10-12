import { expect, test } from './fixtures'
import { createGregorianDimension, typeDay, yearStart } from './time-helpers'

// E1 (testing.md §3): dimension wizard (Gregorian preset) → an event with a calendar date → it
// is on the timeline and its page shows the date.
test('E1: wizard → event with a calendar date → timeline and event page', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  await expect(page.getByRole('region', { name: 'Calendars' })).toContainText('Gregorian')

  // An event on 10 March AD 1023, from the event outline.
  await page.getByRole('main').getByRole('link', { name: 'Event outline' }).click()
  await page.getByRole('button', { name: 'New event' }).click()
  const dialog = page.getByRole('dialog', { name: 'New event' })
  await dialog.getByLabel('Name').fill('Coronation of Ada')
  await typeDay(dialog, 1023, 'March', 10)
  await expect(dialog.getByRole('group', { name: 'Start' })).toContainText('10 March AD 1023')
  await dialog.getByRole('button', { name: 'Create event' }).click()
  const row = page.getByRole('row', { name: 'Coronation of Ada' })
  await expect(row).toContainText('10 March AD 1023')

  // On the timeline, around that year.
  const from = yearStart(1022)
  const to = yearStart(1025)
  await page.goto(`${lore.url()}/d/${dimension}/timeline?from=${from}&to=${to}`)
  const item = page.getByRole('button', { name: 'Coronation of Ada' })
  await expect(item).toBeVisible()
  await item.click()
  const preview = page.getByRole('complementary', { name: 'Selected event' })
  await expect(preview).toContainText('10 March AD 1023')

  // Its page.
  await item.dblclick()
  await expect(page.getByRole('heading', { name: 'Coronation of Ada', level: 1 })).toBeVisible()
  await expect(page.getByRole('main')).toContainText('10 March AD 1023')
})
