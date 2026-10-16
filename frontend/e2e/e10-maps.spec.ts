import { deflateSync } from 'node:zlib'

import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

const HEADERS = { 'X-Lore-Client': 'web' }

/** A CRC-32 of `bytes` (PNG chunks). */
function crc32(bytes: Uint8Array): number {
  let crc = ~0
  for (const byte of bytes) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  return ~crc >>> 0
}

/** A plain RGB PNG of `width` × `height` in one color (a map image to upload). */
function png(width: number, height: number, rgb: [number, number, number]): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const length = Buffer.alloc(4)
    length.writeUInt32BE(data.length)
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(body))
    return Buffer.concat([length, body, crc])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header.set([8, 2, 0, 0, 0], 8) // 8-bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, Buffer.from(rgb))])
  const pixels = Buffer.concat(Array.from({ length: height }, () => row))
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(pixels)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

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
