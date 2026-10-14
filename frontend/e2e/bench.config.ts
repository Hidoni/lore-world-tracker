import { defineConfig, devices } from '@playwright/test'

// The browser benchmarks (`make bench-graph`, scripts/graph-bench.sh): headed by default, so the
// browser draws with the machine's GPU (headless Chromium may fall back to software WebGL).
// BENCH_HEADLESS=1 runs headless. Not part of `make e2e` or CI.
const baseURL = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.bench.ts',
  workers: 1, // one browser at a time, in order: measurements don't compete
  timeout: 300_000,
  reporter: 'list',
  outputDir: '../test-results',
  use: {
    ...(baseURL ? { baseURL } : {}),
    headless: process.env.BENCH_HEADLESS === '1',
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
})
