import { expect, READER_URL, test } from './fixtures'

const paragraph = (text: string) => ({ type: 'paragraph', content: [{ type: 'text', text }] })
const block = (level: 'spoiler' | 'private', text: string) => ({
  type: 'visibilityBlock',
  attrs: { level },
  content: [paragraph(text)],
})

// Canaries: private content that must never reach the reader instance.
const SECRET_BLOCK = 'CANARY-E12 the clock stops at midnight'
const SECRET_ENTITY = 'CANARY-E12 Hidden Cabal'
const EDITING = /^(new|create|edit|rename|delete|move to trash|upload|save|publish|back up)\b/i

// E12 (testing.md §3): content with private and spoiler parts → publish a snapshot from the
// settings → the reader instance (read-only, serving the publish directory) shows no editing UI,
// no private canary, and folds the spoilers.
test('E12: publish a snapshot → the reader instance: no edit UI, no private data, spoilers folded', async ({
  page,
  lore,
  request,
}) => {
  test.skip(READER_URL === '', 'E2E_READER_URL is not set')
  const dimension = await lore.createDimension('Aetheria', {
    summary: 'A world of tides and clocks.',
    body: {
      type: 'doc',
      content: [
        paragraph('The tides of Aetheria follow the great clock of Varn.'),
        block('spoiler', 'The clock is running down.'),
        block('private', SECRET_BLOCK),
      ],
    },
  })
  const secret = await lore.createEntity('misc', SECRET_ENTITY, {
    dimension_id: dimension.id,
    visibility: 'private',
  })
  const traitor = await lore.createEntity('misc', 'The traitor', {
    dimension_id: dimension.id,
    visibility: 'spoiler',
    summary: 'Someone close to the queen.',
  })

  // The author sees the private block (so its absence below means it was removed).
  await page.goto(lore.url(dimension.id))
  await expect(page.getByText(SECRET_BLOCK)).toBeVisible()

  // Publish from the settings.
  await page.goto(`${lore.url()}/settings/publishing`)
  await expect(page.getByText('Not published yet.')).toBeVisible()
  await page.getByRole('button', { name: 'Publish snapshot' }).click()
  await expect(page.getByText(/Last published/)).toBeVisible()

  // The reader instance: read-only, the vault's landing page.
  const reader = (path: string) => `${READER_URL}/v/${lore.vault.id}${path}`
  await page.goto(reader(''))
  await expect(page.getByText('Read-only')).toBeVisible()
  await expect(page.getByRole('main').getByRole('region', { name: 'Dimensions' })).toContainText(
    'Aetheria',
  )
  const seen: string[] = []
  const check = async (where: string) => {
    await page.waitForLoadState('networkidle')
    const editing = await page
      .getByRole('button')
      .evaluateAll(
        (buttons, pattern) =>
          buttons
            .map((b) => b.getAttribute('aria-label') ?? b.textContent.trim())
            .filter((label) => new RegExp(pattern, 'i').test(label)),
        EDITING.source,
      )
    expect(editing, `${where}: editing controls`).toEqual([])
    seen.push(await page.content())
  }
  await check('home')

  // The dimension's page: the public text, the spoiler folded, the private block gone.
  await page.goto(reader(`/e/${dimension.id}`))
  await expect(
    page.getByText('The tides of Aetheria follow the great clock of Varn.'),
  ).toBeVisible()
  await expect(page.getByText('The clock is running down.')).toBeHidden()
  await check('dimension')
  await page.getByText('Spoiler', { exact: true }).click()
  await expect(page.getByText('The clock is running down.')).toBeVisible()

  // A spoiler entity asks first.
  await page.goto(reader(`/e/${traitor.id}`))
  await expect(page.getByRole('heading', { name: 'The traitor', level: 1 })).toBeVisible()
  await expect(page.getByText('Someone close to the queen.')).toBeHidden()
  await check('spoiler entity')
  await page.getByRole('button', { name: 'Show spoilers' }).click()
  await expect(page.getByText('Someone close to the queen.')).toBeVisible()

  // The kind's list and the timeline.
  await page.goto(reader('/k/misc'))
  await expect(page.getByText('The traitor')).toBeVisible()
  await check('list')
  await page.goto(reader(`/d/${dimension.id}/timeline`))
  await expect(page.getByRole('application', { name: 'Timeline' })).toBeVisible()
  await check('timeline')

  // The private canaries are nowhere: not on any page, not in search, not by id.
  for (const html of seen) {
    expect(html).not.toContain('CANARY-E12')
  }
  const api = `${READER_URL}/api/v1/vaults/${lore.vault.id}`
  const search = await request.get(`${api}/search`, { params: { q: 'CANARY' } })
  expect(search.ok()).toBe(true)
  expect(await search.text()).not.toContain('CANARY-E12')
  expect((await request.get(`${api}/entities/${secret.id}`)).status()).toBe(404)
  // And the reader can't be written to.
  const write = await request.post(`${api}/entities`, {
    data: { kind: 'misc', name: 'Graffiti' },
    headers: { 'X-Lore-Client': 'web' },
  })
  expect(write.status()).toBe(403)
})
