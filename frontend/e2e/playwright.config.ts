import { defineConfig, devices } from '@playwright/test'

// Runs against an already running app at E2E_BASE_URL. The harness that builds and starts the
// app arrives in #6 (M0-06); journeys arrive in M4.
const baseURL = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  outputDir: '../test-results',
  use: {
    ...(baseURL ? { baseURL } : {}),
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
