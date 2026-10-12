import { expect, test } from './fixtures'
import { createGregorianDimension } from './time-helpers'

const DAY = 86_400n

// E2 (testing.md §3): edit a calendar → impact preview → keep the dates of most events, keep the
// moment of one → the moments and displays follow the choices.
test('E2: calendar edit → impact preview → keep dates, pin one → moments', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  const editLink = page
    .getByRole('region', { name: 'Calendars' })
    .getByRole('link', { name: 'Edit' })
  const calendar = /calendars\/([^/]+)\/edit/.exec((await editLink.getAttribute('href')) ?? '')?.[1]
  if (calendar === undefined) throw new Error('no calendar')
  const may10AD1 = (name: string) =>
    lore.createEntity('event', name, {
      dimension_id: dimension,
      ext: {
        start: {
          anchor: {
            kind: 'calendar',
            calendar_id: calendar,
            fields: { year: '1', month: 'may', day: '10' },
          },
          precision: 'day',
        },
      },
    })
  const spring = await may10AD1('Spring Fair')
  const harvest = await may10AD1('Harvest Moot')
  const startOf = async (id: string) =>
    BigInt(((await lore.entity(id)) as unknown as { ext: { start_t: string } }).ext.start_t)
  const before = await startOf(spring.id)
  expect(await startOf(harvest.id)).toBe(before)

  // January loses a day in common years. The shift adds up year after year, so the events are
  // in AD 1, where it is exactly one day: dates move unless their moment is kept.
  await editLink.click()
  const common = page.getByRole('listitem', { name: 'Template year_common' })
  await common.getByLabel('Unit 1 template').selectOption('m30')
  await page.getByRole('button', { name: 'Save' }).click()
  const review = page.getByRole('dialog', { name: 'Review the calendar change' })
  await expect(review.getByRole('row', { name: 'Harvest Moot start' })).toContainText('10 May AD 1')
  for (const slot of ['start', 'end']) {
    await review.getByLabel(`Choice for Harvest Moot ${slot}`).selectOption('Keep the moment')
  }
  // Keeping the moment of 10 May shows the date it becomes.
  await expect(review.getByRole('row', { name: 'Harvest Moot start' })).toContainText('11 May AD 1')
  await review.getByRole('button', { name: 'Apply the change' }).click()
  await expect(review).toBeHidden()

  // The kept date now comes a day earlier; the pinned moment stays, under a new date.
  expect(await startOf(spring.id)).toBe(before - DAY)
  expect(await startOf(harvest.id)).toBe(before)
  await page.goto(lore.url(spring.id))
  await expect(page.getByRole('main')).toContainText('10 May AD 1')
  await page.goto(lore.url(harvest.id))
  await expect(page.getByRole('main')).toContainText('11 May AD 1')
})
