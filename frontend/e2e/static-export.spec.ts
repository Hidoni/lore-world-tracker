import { expect, revealPanels, STATIC_URL, test } from './fixtures'

// The static export (visibility-and-sharing.md §8, ADR 0016): `scripts/e2e.sh` exports the tiny
// sample world with `lore vault export-static` and serves it from a subfolder with
// `python -m http.server`, no Lore server involved. Each part of the export (#373–#378) checks
// the pages it adds here.
test.skip(STATIC_URL === '', 'E2E_STATIC_URL is not set')

test('a static export opens from any folder of a plain web server', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(String(error)))
  const requests: string[] = []
  page.on('request', (request) => requests.push(request.url()))
  let data = 0
  page.on('response', (response) => {
    if (response.url().includes('/site/data/'))
      void response.body().then((body) => (data += body.length))
  })

  await page.goto(STATIC_URL)
  // The vault list, for readers: no editing.
  const vaults = page.getByRole('list', { name: 'Vaults' })
  await expect(vaults.getByRole('link', { name: 'Aetheria' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create vault' })).toHaveCount(0)
  await expect(vaults.getByRole('button')).toHaveCount(0)

  // Into the vault: the reader landing page, routed by the hash.
  await vaults.getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  expect(new URL(page.url()).hash).toMatch(/^#\/v\//)
  // A deep link reloads: the host only ever serves index.html and files.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()

  // Everything came from the export's folder: assets relative to it, reads from its data files,
  // nothing from an API.
  const site = new URL(STATIC_URL)
  const outside = requests.filter((url) => {
    const { origin, pathname } = new URL(url)
    return origin === site.origin && !pathname.startsWith(site.pathname)
  })
  expect(outside).toEqual([])
  expect(requests.some((url) => url.includes('/site/data/vaults/'))).toBe(true)
  // The landing page loads only what it shows (testing.md §4: 2 MB on the small world).
  await page.waitForLoadState('networkidle')
  expect(data).toBeGreaterThan(0)
  expect(data).toBeLessThan(2_000_000)
  expect(errors).toEqual([])
})

test('an entity page of a static export', async ({ page }) => {
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Characters', exact: true }).first().click()
  await page.getByRole('link', { name: 'Ilsa the Tidebound' }).first().click()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Fields' })).toContainText('Ilsa Maren-Varn')
  await expect(page.getByRole('region', { name: 'Relations' }).first()).toBeVisible()
  // A deep link to an entity reloads from the export's files.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
})

test('family trees of a static export at any depth', async ({ page }) => {
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await page.getByRole('link', { name: 'Characters', exact: true }).first().click()
  await page.getByRole('link', { name: 'Ilsa the Tidebound' }).first().click()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
  await revealPanels(page)
  // Computed in the browser (#386): any number of generations, with or without spouses.
  await page.getByLabel('Generations up').first().selectOption('5')
  await page.getByLabel('Generations down').first().selectOption('0')
  await expect(page.getByText('This static export does not include this page yet.')).toHaveCount(0)
  await expect(page.getByText('Ilsa the Tidebound').first()).toBeVisible()
})

test('search in a static export: the search page and the quick switcher', async ({ page }) => {
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Search', exact: true }).first().click()
  await page.getByRole('searchbox').first().fill('Tidebound')
  await page.getByRole('searchbox').first().press('Enter')
  await expect(page.getByText('This static export does not include this page yet.')).toHaveCount(0)
  await page
    .getByRole('main')
    .getByRole('link', { name: /Ilsa the Tidebound/ })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
  // The quick switcher.
  await page.keyboard.press('Control+k')
  await page.keyboard.type('Ilsa')
  await expect(page.getByRole('option', { name: /Ilsa the Tidebound/ }).first()).toBeVisible()
})

test('the timeline of a static export, zoomed out and in', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  const vault = /^#\/v\/([^/?]+)/.exec(new URL(page.url()).hash)?.[1] ?? ''
  // The dimension and Wren's Warning's start, read through the export's own fetch.
  const found = await page.evaluate(async (base) => {
    const fetch = (window as unknown as { loreStaticFetch: (r: Request) => Promise<Response> })
      .loreStaticFetch
    const get = async (route: string) =>
      (await (
        await fetch(new Request(`http://static.invalid/api/v1/${base}/${route}`))
      ).json()) as {
        items: { id: string; name: string; start_t?: string; end_t?: string }[]
      }
    const dimension = (await get('entities?kind=dimension')).items[0]?.id ?? ''
    const timelines = (await (
      await fetch(
        new Request(`http://static.invalid/api/v1/${base}/dimensions/${dimension}/timelines`),
      )
    ).json()) as { items: { id: string; parent_timeline_id: string | null }[] }
    const timeline = timelines.items.find((t) => t.parent_timeline_id === null)?.id ?? ''
    const ext = (await (
      await fetch(new Request(`http://static.invalid/api/v1/${base}/entities/${dimension}`))
    ).json()) as { ext: { duration: string } }
    const answer = await get(
      `timelines/${timeline}/window?from=0&to=${BigInt(ext.ext.duration) + 1n}&px=2000`,
    )
    const warning = answer.items.find((item) => item.name === "Wren's Warning")
    return { dimension, start: warning?.start_t ?? '0', end: warning?.end_t ?? '1' }
  }, `vaults/${vault}`)

  await page.goto(`${STATIC_URL}#/v/${vault}/d/${found.dimension}/timeline`)
  const timeline = page.getByRole('application', { name: 'Timeline' })
  await expect(timeline).toBeVisible()
  await expect(timeline.getByRole('button', { name: "Wren's Warning" })).toBeVisible()
  // Zoomed in far past any recorded level: the window is computed for this range and width.
  const from = BigInt(found.start) - 1n
  const to = BigInt(found.end) + 1n
  await page.goto(`${STATIC_URL}#/v/${vault}/d/${found.dimension}/timeline?from=${from}&to=${to}`)
  await expect(timeline.getByRole('button', { name: "Wren's Warning" })).toBeVisible()
  await expect(page.getByText('This static export does not include this page yet.')).toHaveCount(0)
  await timeline.getByRole('button', { name: "Wren's Warning" }).click()
  expect(errors).toEqual([])
})

test('module pages, a map and its image in a static export', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  const vault = /^#\/v\/([^/?]+)/.exec(new URL(page.url()).hash)?.[1] ?? ''

  // A character's module panels: relationships come from the export's recorded reads.
  await page.getByRole('link', { name: 'Characters', exact: true }).first().click()
  await page.getByRole('link', { name: 'Ilsa the Tidebound' }).first().click()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
  await revealPanels(page)
  await expect(page.getByRole('region', { name: 'Relationships' }).first()).toBeVisible()
  await expect(page.getByText('This static export does not include this page yet.')).toHaveCount(0)

  // The location of a map: its image is the export's copy, and it loads.
  const location = await page.evaluate(async (base) => {
    const fetch = (window as unknown as { loreStaticFetch: (r: Request) => Promise<Response> })
      .loreStaticFetch
    const response = await fetch(new Request(`http://static.invalid/api/v1/${base}/m/maps/maps`))
    const { items } = (await response.json()) as { items: { location_id: string }[] }
    return items[0]?.location_id ?? ''
  }, `vaults/${vault}`)
  await page.goto(`${STATIC_URL}#/v/${vault}/e/${location}`)
  await revealPanels(page)
  const image = page.getByRole('region', { name: 'Map' }).locator('img.leaflet-image-layer')
  await expect(image).toBeVisible()
  await expect(image).toHaveAttribute('src', /\/site\/data\/vaults\/.+\/static\/files\//)
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  expect(errors).toEqual([])
})

test('the graph of a static export', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  const vault = /^#\/v\/([^/?]+)/.exec(new URL(page.url()).hash)?.[1] ?? ''
  await page.goto(`${STATIC_URL}#/v/${vault}/m/graph`)
  await expect(page.getByRole('heading', { name: 'Graph', level: 1 })).toBeVisible()
  await expect(page.getByTestId('graph-canvas')).toBeVisible()
  await expect(page.getByText('This static export does not include this page yet.')).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Find in the graph' }).fill('Ilsa the Tidebound')
  await expect(page.getByText('1 found')).toBeVisible()
  await page.getByRole('textbox', { name: 'Find in the graph' }).press('Enter')
  const preview = page.getByRole('complementary', { name: 'Selected entity' })
  await preview.getByRole('link', { name: 'Open Ilsa the Tidebound' }).click()
  await expect(page.getByRole('heading', { name: 'Ilsa the Tidebound', level: 1 })).toBeVisible()
  expect(errors).toEqual([])
})
