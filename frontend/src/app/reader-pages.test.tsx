import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { moduleDefinitions } from '@/modules'
import { serveVault } from '@/test/fake-vault'
import { editingControls } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const PAGES: [string, string][] = [
  ['/v/v1', 'Dimensions'],
  ['/v/v1/e/a1', 'Crown'],
  ['/v/v1/e/d1', 'Aetheria'],
  ['/v/v1/k/artifact', 'Artifacts'],
  ['/v/v1/search?q=crown', 'Search'],
]

describe('reader mode pages', () => {
  it.each(PAGES)('%s offers no editing', async (path, heading) => {
    serveVault()
    await renderApp(path, moduleDefinitions, { readOnly: true })
    await screen.findByRole('heading', { name: heading })
    expect(editingControls()).toEqual([])
  })

  it.each([
    '/v/v1/settings',
    '/v/v1/settings/backups',
    '/v/v1/trash',
    '/v/v1/changes',
    '/v/v1/consistency',
    '/v/v1/calendars/c1/edit',
    '/v/v1/calendars/new?dimension=d1',
  ])('%s is for authors only', async (path) => {
    serveVault()
    await renderApp(path, moduleDefinitions, { readOnly: true })
    expect(await screen.findByRole('heading', { name: 'For authors' })).toBeInTheDocument()
    expect(editingControls()).toEqual([])
  })

  it('finds the editing controls an author gets (the positive control)', async () => {
    serveVault()
    await renderApp('/v/v1/e/a1', moduleDefinitions)
    await screen.findByRole('heading', { name: 'Crown' })
    await screen.findAllByRole('link', { name: 'Treasury' })
    expect(editingControls()).toEqual(expect.arrayContaining(['button "Rename"']))
    expect(editingControls().some((found) => found.startsWith('drag handle'))).toBe(true)
  })
})
