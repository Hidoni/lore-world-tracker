import { expect, test } from './fixtures'
import { createGregorianDimension } from './time-helpers'

const DAY = 86_400n
const SIEGE = 400n * DAY

// E3 (testing.md §3): an event relative to another → dragging the anchor event on the timeline
// moves the dependent too; making the anchor relative to its dependent is refused with a clear
// message.
test('E3: relative anchor → drag the anchor event → the dependent moves; a cycle is refused', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  const siege = await lore.createEntity('event', 'Siege of Varn', {
    dimension_id: dimension,
    ext: {
      start: { anchor: { kind: 'absolute', t: SIEGE.toString() }, precision: 'base' },
      end: { kind: 'duration', duration: { kind: 'base', units: (30n * DAY).toString() } },
    },
  })
  const startOf = async (id: string) =>
    BigInt(((await lore.entity(id)) as unknown as { ext: { start_t: string } }).ext.start_t)

  // Relief: 10 days after the siege ends, typed in the event dialog.
  await page.goto(`${lore.url()}/d/${dimension}/events`)
  await page.getByRole('button', { name: 'New event' }).click()
  const dialog = page.getByRole('dialog', { name: 'New event' })
  await dialog.getByLabel('Name').fill('Relief of Varn')
  const start = dialog.getByRole('group', { name: 'Start' })
  await start.getByRole('tab', { name: 'Relative' }).click()
  await start.getByLabel('Relative to').selectOption('Event')
  await start.getByLabel('Find the target').fill('Siege')
  await start
    .getByRole('list', { name: 'Targets' })
    .getByRole('button', { name: /Siege of Varn/ })
    .click()
  await start.getByLabel('Edge').selectOption({ label: 'End' })
  await start.getByLabel('Offset in seconds').fill((10n * DAY).toString())
  await dialog.getByRole('button', { name: 'Create event' }).click()
  await expect(page.getByRole('row', { name: 'Relief of Varn' })).toBeVisible()
  const relief = await lore.findByName('Relief of Varn')
  expect(await startOf(relief)).toBe(SIEGE + 40n * DAY)

  // Drag the siege later on the timeline: the relief follows.
  const from = SIEGE - 50n * DAY
  const to = SIEGE + 150n * DAY
  await page.goto(`${lore.url()}/d/${dimension}/timeline?from=${from}&to=${to}`)
  const bar = page.getByRole('button', { name: 'Siege of Varn' })
  const box = await bar.boundingBox()
  if (box === null) throw new Error('the siege is not drawn')
  const saved = page.waitForResponse(
    (response) => response.request().method() === 'PATCH' && response.ok(),
  )
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 8 })
  await page.mouse.up()
  await saved
  await expect(page.getByText('Moved Siege of Varn')).toBeVisible()
  const moved = (await startOf(siege.id)) - SIEGE
  expect(moved > 0n).toBe(true)
  expect(await startOf(relief)).toBe(SIEGE + moved + 40n * DAY)
  // The relief is relative: it shows a lock rather than dragging.
  await page.getByRole('button', { name: 'Relief of Varn' }).click()
  await expect(
    page.getByRole('complementary', { name: 'Selected event' }).getByRole('button', {
      name: 'Edit offset',
    }),
  ).toBeVisible()

  // A cycle: the siege made relative to its own relief is refused.
  await page.goto(lore.url(siege.id))
  await page.getByRole('button', { name: 'Edit time' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit Siege of Varn' })
  const siegeStart = edit.getByRole('group', { name: 'Start' })
  await siegeStart.getByRole('tab', { name: 'Relative' }).click()
  await siegeStart.getByLabel('Relative to').selectOption('Event')
  await siegeStart.getByLabel('Find the target').fill('Relief')
  await siegeStart
    .getByRole('list', { name: 'Targets' })
    .getByRole('button', { name: /Relief of Varn/ })
    .click()
  await edit.getByRole('button', { name: 'Save' }).click()
  await expect(edit.getByText(/cycle/i).first()).toBeVisible()
  expect(await startOf(siege.id)).toBe(SIEGE + moved)
})
