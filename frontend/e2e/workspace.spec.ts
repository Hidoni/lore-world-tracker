import { expect, test } from './fixtures'

// Tabs and panes (frontend.md §3, #160): pages side by side, each pane with its own router, and the
// layout remembered across reloads.

test('opens pages in tabs and side by side', async ({ page, lore }) => {
  const aetheria = await lore.createDimension('Aetheria')
  const brume = await lore.createDimension('Brume')
  await page.goto(lore.url(aetheria.id))
  const main = page.getByRole('region', { name: 'Main pane' })
  await expect(main.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()

  // Open it to the right, then go elsewhere in the main pane: the other pane stays.
  await main.getByRole('button', { name: 'Open to the right' }).click()
  const right = page.getByRole('region', { name: 'Pane 2' })
  await expect(right.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await page.getByRole('navigation', { name: 'Vault' }).getByRole('link', { name: 'Brume' }).click()
  await expect(main.getByRole('heading', { name: 'Brume', level: 1 })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/e/${brume.id}`))
  await expect(right.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()

  // A new tab in the other pane: its links open there.
  await right.getByRole('button', { name: 'New tab' }).click()
  await right.getByRole('link', { name: 'Aetheria' }).first().click()
  await expect(right.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await expect(
    right.getByRole('list', { name: 'Tabs of pane 2' }).getByRole('listitem'),
  ).toHaveCount(2)
  await expect(page).toHaveURL(new RegExp(`/e/${brume.id}`))

  // Alt-click opens a link in a new tab of the main pane.
  await page
    .getByRole('navigation', { name: 'Vault' })
    .getByRole('link', { name: 'Search' })
    .click({ modifiers: ['Alt'] })
  await expect(page).toHaveURL(/\/search/)
  await expect(main.getByRole('list', { name: 'Tabs' }).getByRole('listitem')).toHaveCount(2)

  // The workspace survives a reload.
  await page.reload()
  await expect(main.getByRole('list', { name: 'Tabs' }).getByRole('listitem')).toHaveCount(2)
  await expect(
    right.getByRole('list', { name: 'Tabs of pane 2' }).getByRole('listitem'),
  ).toHaveCount(2)
  await expect(right.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
})
