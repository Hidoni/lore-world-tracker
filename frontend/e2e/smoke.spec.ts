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
