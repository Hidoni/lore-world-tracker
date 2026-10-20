import type { Page } from '@playwright/test'

import { expect, test, revealPanels } from './fixtures'
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
  await revealPanels(page)
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
  await panel.getByRole('button', { name: 'Edit map' }).click()
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

// Regions (#154): drawn by clicking corners in a real Leaflet map, then selected by a click.
test('E10: drawing a region on a map', async ({ page, lore, request }) => {
  const dimension = await lore.createDimension('Aetheria')
  const varn = await lore.createEntity('location', 'Varn', { dimension_id: dimension.id })
  const uploaded = await request.post(`${lore.base}/m/media/items`, {
    multipart: {
      file: { name: 'varn.png', mimeType: 'image/png', buffer: png(400, 300, [90, 140, 90]) },
    },
    headers: HEADERS,
  })
  expect(uploaded.ok()).toBe(true)
  const image = (await uploaded.json()) as { item: { id: string } }
  const created = await request.post(`${lore.base}/m/maps/maps`, {
    data: { location_id: varn.id, media_id: image.item.id, name: 'Varn' },
    headers: HEADERS,
  })
  expect(created.ok()).toBe(true)
  const { map } = (await created.json()) as { map: { id: string } }

  await page.goto(`${lore.url()}/m/maps/maps/${map.id}`)
  const canvas = page.locator('.leaflet-container')
  await expect(page.locator('.leaflet-image-layer')).toBeVisible()
  await page.getByRole('button', { name: 'Edit map' }).click()
  await page.getByRole('button', { name: 'Draw region' }).click()
  const box = await canvas.boundingBox()
  if (box === null) throw new Error('no map')
  const cx = box.width / 2
  const cy = box.height / 2
  for (const [dx, dy] of [
    [-40, -30],
    [40, -30],
    [0, 40],
  ] as const)
    await canvas.click({ position: { x: cx + dx, y: cy + dy } })
  await expect(page.getByText(/3 so far/)).toBeVisible()
  await page.getByRole('button', { name: 'Finish region' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a region' })
  await dialog.getByRole('searchbox', { name: 'Find an entity' }).fill('Marsh')
  await dialog.getByRole('button', { name: 'Add the label “Marsh”' }).click()
  await expect(page.getByRole('dialog', { name: 'Edit Marsh' })).toBeVisible()
  await expect(page.locator('path.lore-region')).toHaveCount(1)
  // The new region is selected: its corners are handles.
  await expect(page.locator('.leaflet-marker-icon[title^="Corner"]')).toHaveCount(3)
  await page.getByRole('button', { name: 'Done editing' }).click()

  await canvas.click({ position: { x: cx, y: cy - 10 } })
  await expect(page.getByRole('dialog', { name: 'Marsh' })).toBeVisible()
})
