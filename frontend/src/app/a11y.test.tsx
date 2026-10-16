import { screen } from '@testing-library/react'
import { describe, it } from 'vitest'

import { moduleDefinitions } from '@/modules'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { serveVault } from '@/test/fake-vault'
import { settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

// The dimension overview and the calendar editor are checked in their own tests (their data).
const PAGES: string[] = [
  '/v/v1',
  '/v/v1/e/a1',
  '/v/v1/e/d1',
  '/v/v1/d/d1/timeline',
  '/v/v1/d/d1/events',
  '/v/v1/k/artifact',
  '/v/v1/search?q=crown',
  '/v/v1/settings',
  '/v/v1/settings/backups',
  '/v/v1/trash',
  '/v/v1/changes',
  '/v/v1/consistency',
]

describe('accessibility (axe: no serious or critical violations)', () => {
  it.each(PAGES)(
    '%s, as the author',
    async (path) => {
      serveVault()
      await renderApp(path, moduleDefinitions)
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )

  it.each(PAGES.slice(0, 7))(
    '%s, as a reader',
    async (path) => {
      serveVault()
      await renderApp(path, moduleDefinitions, { readOnly: true })
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )

  it(
    'the vault picker',
    async () => {
      serveVault()
      await renderApp('/', moduleDefinitions)
      await screen.findAllByRole('heading', { level: 1 })
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})
