import { expect, test } from './fixtures'

// E5 (testing.md §3): a `[[` link written in the editor shows up as a backlink on the target, and
// renaming the target relabels the link (decided 2026-10-11, #70).
test('E5: [[ link → backlink → rename relabels the link', async ({ page, lore }) => {
  const writer = await lore.createDimension('Aetheria')
  const target = await lore.createDimension('Borealis')

  // Write a link with [[ in the body editor; it autosaves.
  await page.goto(lore.url(writer.id))
  const body = page.getByRole('textbox', { name: 'Body' })
  await body.click()
  await page.keyboard.type('The gate to [[Bore')
  await expect(page.getByRole('option', { name: /^Borealis/ })).toBeVisible()
  const saved = page.waitForResponse(
    (response) => response.request().method() === 'PATCH' && response.ok(),
  )
  await page.keyboard.press('Enter')
  await page.keyboard.type('opens at dawn.')
  await expect(body.locator('.entity-link')).toHaveText('Borealis')
  await saved
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()

  // The target lists it as a backlink (context panel).
  await page.goto(lore.url(target.id))
  await page.getByRole('button', { name: 'Show context panel' }).click()
  const backlinks = page.getByRole('region', { name: 'Backlinks' })
  await expect(backlinks.getByRole('link', { name: 'Aetheria' })).toBeVisible()
  await expect(backlinks).toContainText('mentioned once')

  // Rename the target: the link in the writer's body follows.
  await page.getByRole('button', { name: 'Rename' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill('Borealis Prime')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Borealis Prime' })).toBeVisible()

  await page.goto(lore.url(writer.id))
  await expect(page.getByRole('textbox', { name: 'Body' }).locator('.entity-link')).toHaveText(
    'Borealis Prime',
  )
  await expect(page.getByRole('textbox', { name: 'Body' })).toContainText(
    'The gate to Borealis Prime opens at dawn.',
  )
  expect((await lore.backlinks(target.id)).map((item) => item.entity.name)).toEqual(['Aetheria'])
})
