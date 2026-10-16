import type { APIRequestContext } from '@playwright/test'

import { expect, HEADERS, test } from './fixtures'
import { png } from './images'

const paragraph = (text: string) => ({ type: 'paragraph', content: [{ type: 'text', text }] })

interface Summary {
  id: string
}

/** A vault's entities as full records, by id (names, kinds, bodies, fields; no revisions). */
async function contents(request: APIRequestContext, vault: string) {
  const base = `/api/v1/vaults/${vault}`
  const page = (await (
    await request.get(`${base}/entities`, { params: { limit: 500 } })
  ).json()) as {
    items: Summary[]
  }
  const records: Record<string, unknown> = {}
  for (const { id } of page.items) {
    const entity = (await (await request.get(`${base}/entities/${id}`)).json()) as Record<
      string,
      unknown
    >
    const { name, kind, summary, body, fields, visibility, parent_id, dimension_id } = entity
    records[id] = { name, kind, summary, body, fields, visibility, parent_id, dimension_id }
  }
  return records
}

async function mediaHashes(request: APIRequestContext, vault: string): Promise<string[]> {
  const listed = (await (await request.get(`/api/v1/vaults/${vault}/m/media/items`)).json()) as {
    items: { sha256: string }[]
  }
  return listed.items.map((item) => item.sha256).sort()
}

// E13 (testing.md §3): a backup with media from the settings → download it → restore it into a
// new vault → the content is identical (spot checks through the UI and the API).
test('E13: backup with media → restore into a new vault → identical content', async ({
  page,
  lore,
  request,
}) => {
  const uploaded = await request.post(`${lore.base}/m/media/items`, {
    multipart: {
      file: { name: 'clock.png', mimeType: 'image/png', buffer: png(64, 48, [200, 160, 60]) },
    },
    headers: HEADERS,
  })
  expect(uploaded.ok()).toBe(true)
  const image = ((await uploaded.json()) as { item: { id: string } }).item.id
  const dimension = await lore.createDimension('Aetheria', {
    body: {
      type: 'doc',
      content: [
        paragraph('The tides of Aetheria follow the great clock of Varn.'),
        { type: 'image', attrs: { mediaId: image, alt: 'The great clock', caption: null } },
      ],
    },
  })
  const lantern = await lore.createEntity('misc', 'Lantern', {
    dimension_id: dimension.id,
    summary: 'A lamp that never goes out.',
    visibility: 'spoiler',
  })
  await lore.link('core.related', lantern.id, dimension.id)

  // Back up from the settings (media included by default) and download the zip.
  await page.goto(`${lore.url()}/settings/backups`)
  await expect(page.getByLabel('Include media files')).toBeChecked()
  await page.getByRole('button', { name: 'Back up now' }).click()
  const list = page.getByRole('list', { name: 'Backups list' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    list.getByRole('link', { name: 'Download' }).click(),
  ])
  const zip = await download.path()

  // Restore it into a new vault.
  await page.getByLabel('Backup zip').setInputFiles(zip)
  await page.getByRole('button', { name: 'Restore into a new vault' }).click()
  const restoredLink = page.getByRole('link', { name: /\(restored/ })
  await expect(restoredLink).toBeVisible()
  const restored = /\/v\/([^/?#]+)/.exec((await restoredLink.getAttribute('href')) ?? '')?.[1]
  if (restored === undefined) throw new Error('no link to the restored vault')
  expect(restored).not.toBe(lore.vault.id)

  try {
    // The API: the same entities with the same content, the same media files and links.
    expect(await contents(request, restored)).toEqual(await contents(request, lore.vault.id))
    expect(await mediaHashes(request, restored)).toEqual(await mediaHashes(request, lore.vault.id))
    const links = await request.get(`/api/v1/vaults/${restored}/entities/${lantern.id}/links`)
    expect(JSON.stringify(await links.json())).toContain(dimension.id)

    // The UI: the restored dimension shows its text and its image (the file loads).
    await restoredLink.click()
    await page.goto(`/v/${restored}/e/${dimension.id}`)
    await expect(
      page.getByText('The tides of Aetheria follow the great clock of Varn.'),
    ).toBeVisible()
    const picture = page.getByRole('img', { name: 'The great clock' })
    await expect(picture).toBeVisible()
    await expect
      .poll(() => picture.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0)
    await page.goto(`/v/${restored}/e/${lantern.id}`)
    await expect(page.getByText('A lamp that never goes out.')).toBeVisible()
  } finally {
    await request.delete(`/api/v1/vaults/${restored}`, { headers: HEADERS })
  }
})
