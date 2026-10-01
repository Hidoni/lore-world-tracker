import { expect, test } from '@playwright/test'

test.skip(!process.env.E2E_BASE_URL, 'E2E_BASE_URL is not set')

test('shell loads and shows the server version', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Welcome' })).toBeVisible()
  await expect(page.getByTestId('server-version')).toHaveText(/^\d+\.\d+\.\d+/)
})
