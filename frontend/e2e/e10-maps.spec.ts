import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { png } from './images'

const HEADERS = { 'X-Lore-Client': 'web' }

const point = (t: number) => ({ anchor: { kind: 'absolute', t: String(t) }, precision: 'base' })
const marker = (page: Page, name: string) => page.locator(`.leaflet-marker-icon[title="${name}"]`)

// E10 (testing.md §3): upload a map → pin locations → drill down → the time cursor hides the pin
// of a destroyed city. Ashgard stands from the beginning until 500.
test('E10: map with pins, drill-down and the time cursor', async ({ page, lore, request }) => {
  const dimension = await lore.createDimension('Aetheria')
  const home = { dimension_id: dimension.id }
  const varn = await lore.createEntity('location', 'Varn', home)
  const ashgard = await lore.createEntity('location', 'Ashgard', { ...home, parent_id: varn.id })
  const { ext } = (await lore.entity(dimension.id)) as unknown as {
    ext: { prime_timeline_id: string }
  }
  await lore.fact(ashgard.id, {
    field_key: 'core.exists',
    timeline_id: ext.prime_timeline_id,
    valid_to: point(500),
  })
  // Ashgard's own map, through the API (the journey drills into it).
  const uploaded = await request.post(`${lore.base}/m/media/items`, {
    multipart: {
      file: { name: 'ashgard.png', mimeType: 'image/png', buffer: png(200, 150, [150, 120, 90]) },
    },
    headers: HEADERS,
  })
  expect(uploaded.ok()).toBe(true)
  const image = (await uploaded.json()) as { item: { id: string } }
  const city = await request.post(`${lore.base}/m/maps/maps`, {
    data: { location_id: ashgard.id, media_id: image.item.id, name: 'Ashgard' },
    headers: HEADERS,
  })
  expect(city.ok()).toBe(true)

  // Varn's map: uploaded in the "New map" dialog.
  await page.goto(lore.url(varn.id))
  const panel = page.getByRole('region', { name: 'Map' })
  await panel.getByRole('button', { name: 'New map' }).click()
  const dialog = page.getByRole('dialog', { name: 'New map' })
  await dialog.getByRole('button', { name: 'Choose the image' }).click()
  const picker = page.getByRole('dialog', { name: "The map's image" })
  await picker.getByLabel('Upload').setInputFiles({
    name: 'varn.png',
    mimeType: 'image/png',
    buffer: png(400, 300, [90, 140, 90]),
  })
  await page.getByRole('button', { name: 'Create the map' }).click()
  await expect(panel.locator('.leaflet-image-layer')).toBeVisible()

  // Pin Ashgard from the tray of unplaced child locations.
  await panel.getByRole('button', { name: 'Edit pins' }).click()
  const tray = panel.getByRole('region', { name: 'Unplaced child locations' })
  await tray.getByRole('button', { name: 'Place Ashgard on the map' }).click()
  await expect(tray.getByText('Every child location is on this map.')).toBeVisible()
  await panel.getByRole('button', { name: 'Done editing' }).click()

  // Drill down into Ashgard's map, and back out.
  await marker(page, 'Ashgard').click()
  await page
    .getByRole('dialog', { name: 'Ashgard' })
    .getByRole('button', { name: 'Drill into map' })
    .click()
  const crumbs = page.getByRole('navigation', { name: 'Map breadcrumbs' })
  await expect(crumbs.getByText('Ashgard')).toHaveAttribute('aria-current', 'page')
  await crumbs.getByRole('button', { name: 'Varn' }).click()
  await expect(crumbs.getByText('Varn')).toHaveAttribute('aria-current', 'page')

  // The time cursor: Ashgard stands at 100, not at 600.
  const map = page.url()
  await page.goto(`${map}?at=100`)
  await expect(marker(page, 'Ashgard')).toBeVisible()
  await page.goto(`${map}?at=600`)
  await expect(page.locator('.leaflet-image-layer')).toBeVisible()
  await expect(marker(page, 'Ashgard')).toHaveCount(0)
})
