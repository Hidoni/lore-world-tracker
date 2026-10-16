import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

function trackReads(): string[] {
  const reads: string[] = []
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET')
      reads.push(new URL(request.url).pathname + new URL(request.url).search)
  })
  return reads
}

function readOnlyServer() {
  server.use(
    http.get('*/api/v1/meta', () =>
      HttpResponse.json({
        app_version: '1.2.3',
        api_version: 'v1',
        read_only: true,
        exposed_vaults: [],
        features: [],
      }),
    ),
  )
}

describe('reader mode', () => {
  it('lets the author preview the vault as a reader, and stop', async () => {
    serveVault()
    const reads = trackReads()
    await renderApp('/v/v1/e/a1')
    expect(await screen.findByRole('heading', { name: 'Crown' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Settings' })).toHaveLength(2) // top bar, sidebar
    expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Preview as reader' }))
    expect(await screen.findByText('Previewing as reader')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Crown' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
    // Every read made while previewing asks for the reader's view.
    const start = reads.length
    await userEvent.click(screen.getAllByRole('link', { name: 'Treasury' })[0]!)
    expect(await screen.findByRole('heading', { name: 'Treasury' })).toBeInTheDocument()
    expect(reads.length).toBeGreaterThan(start)
    expect(reads.slice(start).filter((read) => !read.includes('as_reader=true'))).toEqual([])
    expect(sessionStorage.getItem('lore.previewAsReader')).toBe('1')

    await userEvent.click(screen.getByRole('button', { name: 'Stop previewing as reader' }))
    expect(await screen.findByRole('button', { name: 'Rename' })).toBeInTheDocument()
    expect(screen.queryByText('Previewing as reader')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('lore.previewAsReader')).toBeNull()
  })

  it('is the only mode of a read-only server', async () => {
    serveVault()
    readOnlyServer()
    await renderApp('/v/v1/e/a1')
    expect(await screen.findByRole('heading', { name: 'Crown' })).toBeInTheDocument()
    expect(screen.getByText('Read-only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Preview as reader' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
  })
})
