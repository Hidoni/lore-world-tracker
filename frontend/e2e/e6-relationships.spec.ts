import { expect, test } from './fixtures'
import {
  absolute,
  atStartOf,
  createGregorianDimension,
  moveCursor,
  yearStart,
} from './time-helpers'

// E6 (testing.md §3, D4): characters with parent/child links and a marriage valid from their
// wedding until his death → the family tree → moving the time cursor changes what is shown
// (married or not, alive or dead).
test('E6: relationships with validity → family tree → the time cursor changes the state', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  const { ext } = (await lore.entity(dimension)) as unknown as {
    ext: { prime_timeline_id: string }
  }
  const make = (kind: string, name: string, extra: Record<string, unknown> = {}) =>
    lore.createEntity(kind, name, { dimension_id: dimension, ...extra })
  const event = (name: string, year: number) =>
    make('event', name, { ext: { start: absolute(yearStart(year)) } })

  const aria = await make('character', 'Aria')
  const bram = await make('character', 'Bram')
  const cora = await make('character', 'Cora')
  const wedding = await event('Wedding of Aria and Bram', 1200)
  const death = await event('Death of Bram', 1250)
  // Bram lives from 1170 until his death; Aria and Bram are married from the wedding until then.
  await lore.fact(bram.id, {
    field_key: 'core.exists',
    timeline_id: ext.prime_timeline_id,
    valid_from: absolute(yearStart(1170)),
    valid_to: atStartOf(death.id),
  })
  await lore.link('characters.spouse_of', aria.id, bram.id, {
    valid_from: atStartOf(wedding.id),
    valid_to: atStartOf(death.id),
  })
  await lore.link('characters.parent_of', aria.id, cora.id)
  await lore.link('characters.parent_of', bram.id, cora.id)

  // The family tree, as a list.
  await page.goto(lore.url(aria.id))
  await expect(page.getByRole('heading', { name: 'Aria', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Open the family tree view' }).click()
  await page.getByRole('checkbox', { name: 'As a list' }).check()
  const people = page.getByTestId('family-list-person')
  await expect(
    people.filter({ has: page.getByRole('link', { name: 'Aria', exact: true }) }),
  ).toContainText('spouse of Bram')
  await expect(
    people.filter({ has: page.getByRole('link', { name: 'Cora', exact: true }) }),
  ).toContainText(/child of (Aria and Bram|Bram and Aria)/)

  // Before the wedding: Aria's daughter, no husband.
  await page.goto(lore.url(aria.id))
  const family = page.getByRole('region', { name: 'Relationships' }).getByRole('list', {
    name: 'Family',
  })
  await expect(family.getByRole('link', { name: 'Cora' })).toBeVisible()
  await expect(family.getByRole('link', { name: 'Bram' })).toBeVisible() // all time
  await moveCursor(page, 1190, 'June', 1)
  await expect(family.getByRole('link', { name: 'Bram' })).toHaveCount(0)
  await expect(family.getByRole('link', { name: 'Cora' })).toBeVisible()

  // Married after the wedding.
  await moveCursor(page, 1220, 'June', 1)
  await expect(family.getByRole('link', { name: 'Bram' })).toBeVisible()

  // After his death: no longer married, and he died.
  await moveCursor(page, 1260, 'June', 1)
  await expect(family.getByRole('link', { name: 'Bram' })).toHaveCount(0)
  await page.goto(`${lore.url(bram.id)}?${new URL(page.url()).searchParams.toString()}`)
  await expect(page.getByRole('heading', { name: 'Bram', level: 1 })).toBeVisible()
  await expect(page.getByRole('status', { name: 'As of the time cursor' })).toContainText('Died')
})
