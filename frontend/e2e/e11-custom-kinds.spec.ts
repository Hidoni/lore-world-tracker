import { expect, test } from './fixtures'
import { absolute, createGregorianDimension, moveCursor, yearStart } from './time-helpers'

// E11 (testing.md §3): a custom kind with custom fields, one of them temporal → an entity of it
// → a fact of the temporal field → moving the time cursor changes the value shown.
test('E11: custom kind with custom fields → an entity of it → its temporal value over time', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  const { ext } = (await lore.entity(dimension)) as unknown as {
    ext: { prime_timeline_id: string }
  }

  // Settings → Kinds: the Artifact kind.
  await page.goto(`${lore.url()}/settings/kinds`)
  await page.getByRole('button', { name: 'New kind' }).click()
  const kindDialog = page.getByRole('dialog', { name: 'New kind' })
  await kindDialog.getByLabel('Label').fill('Artifact')
  await expect(kindDialog.getByLabel('Key')).toHaveValue('artifact')
  await kindDialog.getByRole('radio', { name: 'gem' }).click()
  await kindDialog.getByRole('button', { name: 'Create' }).click()
  await expect(
    page.getByRole('list', { name: 'Custom kinds' }).getByText('Artifact', { exact: true }),
  ).toBeVisible()

  // Settings → Fields: a choice field and a temporal one.
  await page
    .getByRole('navigation', { name: 'Settings' })
    .getByRole('link', { name: 'Fields' })
    .click()
  await page.getByLabel('Kind').selectOption({ label: 'Artifact' })
  await page.getByRole('button', { name: 'New field' }).click()
  let fieldDialog = page.getByRole('dialog', { name: 'New field' })
  await fieldDialog.getByLabel('Label').fill('Rarity')
  await fieldDialog.getByLabel('Type').selectOption('enum')
  for (const [index, option] of ['Common', 'Legendary'].entries()) {
    await fieldDialog.getByRole('button', { name: 'Add option' }).click()
    await fieldDialog.getByLabel(`Option ${String(index + 1)} label`).fill(option)
  }
  await fieldDialog.getByRole('button', { name: 'Create' }).click()
  await expect(fieldDialog).toBeHidden()
  await page.getByRole('button', { name: 'New field' }).click()
  fieldDialog = page.getByRole('dialog', { name: 'New field' })
  await fieldDialog.getByLabel('Label').fill('Owner title')
  await fieldDialog.getByLabel('Changes over time (a history of values)').check()
  await fieldDialog.getByRole('button', { name: 'Create' }).click()
  await expect(fieldDialog).toBeHidden()
  const fields = page.getByRole('list', { name: 'General fields' })
  await expect(fields.getByText('Rarity', { exact: true })).toBeVisible()
  await expect(fields.getByText('Owner title', { exact: true })).toBeVisible()

  // An artifact, from the New… menu like any kind.
  await page.getByRole('button', { name: 'New…' }).click()
  await page.getByRole('menuitem', { name: 'Artifact' }).click()
  const create = page.getByRole('dialog', { name: 'New artifact' })
  await create.getByLabel('Name').fill('Sunblade')
  await create.getByLabel('Dimension').selectOption({ label: 'Aetheria' })
  await create.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('heading', { name: 'Sunblade', level: 1 })).toBeVisible()
  const sunblade = /\/e\/([^/?]+)/.exec(page.url())?.[1]
  if (sunblade === undefined) throw new Error(`not on an entity: ${page.url()}`)
  const entityFields = page.getByRole('region', { name: 'Fields' })
  await expect(entityFields.getByText('Rarity')).toBeVisible()

  // Its owner's title changes over time: a squire's blade, then a king's.
  const timeline = ext.prime_timeline_id
  await lore.fact(sunblade, {
    field_key: 'custom.owner_title',
    value: 'Squire’s blade',
    timeline_id: timeline,
    valid_from: absolute(yearStart(1200)),
    valid_to: absolute(yearStart(1300)),
  })
  await lore.fact(sunblade, {
    field_key: 'custom.owner_title',
    value: 'King’s blade',
    timeline_id: timeline,
    valid_from: absolute(yearStart(1300)),
  })
  await page.reload()
  await moveCursor(page, 1250, 'June', 1)
  await expect(entityFields.getByText('Squire’s blade')).toBeVisible()
  await moveCursor(page, 1350, 'June', 1)
  await expect(entityFields.getByText('King’s blade')).toBeVisible()
  await expect(entityFields.getByText('Squire’s blade')).toHaveCount(0)
})
