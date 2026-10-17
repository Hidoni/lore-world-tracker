import { expect, STATIC_URL, test } from './fixtures'

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
  expect(errors).toEqual([])
})

test('pages a static export does not hold yet say so', async ({ page }) => {
  await page.goto(STATIC_URL)
  await page.getByRole('list', { name: 'Vaults' }).getByRole('link', { name: 'Aetheria' }).click()
  await expect(page.getByRole('heading', { name: 'Aetheria', level: 1 })).toBeVisible()
  await expect(
    page.getByText('This static export does not include this page yet.').first(),
  ).toBeVisible()
})
