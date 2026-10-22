import { expect, test } from '@playwright/test'

test.skip(!process.env.E2E_BASE_URL, 'E2E_BASE_URL is not set')

test('shell loads and shows the server version', async ({ page }) => {
  await page.goto('/?pick=true')
  await expect(page.getByRole('heading', { name: 'Vaults' })).toBeVisible()
  await expect(page.getByTestId('server-version')).toHaveText(/^\d+\.\d+\.\d+/)
})

test('creates a vault, opens it and comes back to it', async ({ page }) => {
  const name = `Smoke ${Date.now()}`
  await page.goto('/?pick=true')
  await page.getByLabel('New vault').fill(name)
  await page.getByRole('button', { name: 'Create vault' }).click()
  await page.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByRole('banner').getByRole('link', { name })).toBeVisible()

  // The picker reopens the last vault.
  await page.goto('/')
  await expect(page).toHaveURL(/\/v\/[0-9a-f-]+$/)
})

// #397: uvicorn closed idle connections after 5 s, so a request that reused one just then failed
// with "socket hang up". `lore serve` keeps them open for LORE_KEEP_ALIVE (75 s).
test('a request after a 5 s idle reuses the connection', async ({ request }) => {
  expect((await request.get('/api/v1/health')).ok()).toBe(true)
  await new Promise((resolve) => setTimeout(resolve, 5_500))
  const name = `Idle ${Date.now()}`
  const created = await request.post('/api/v1/vaults', {
    data: { name },
    headers: { 'X-Lore-Client': 'web' },
  })
  expect(created.ok()).toBe(true)
  const vault = (await created.json()) as { id: string }
  await request.delete(`/api/v1/vaults/${vault.id}`, { headers: { 'X-Lore-Client': 'web' } })
})
