import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { defaultRows, row, serveVault } from '@/test/fake-vault'
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

  it('folds spoilers for readers: pages, field values and links', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        row('s1', 'artifact', 'Mirror', {
          visibility: 'spoiler',
          summary: 'It shows the traitor.',
        }),
        row('a4', 'artifact', 'Scroll', {
          fields: { era: 'Written by the queen', origin: 'Varn' },
          field_visibility: { era: 'spoiler' },
        }),
      ],
      links: [
        {
          id: 'l1',
          link_type: 'core.related',
          source_id: 'a4',
          target_id: 'a2',
          visibility: 'spoiler',
        },
      ],
    })
    await renderApp('/v/v1/e/s1', undefined, { readOnly: true })
    const warning = await screen.findByRole('region', { name: 'Spoiler warning' })
    expect(screen.queryByText('It shows the traitor.')).not.toBeInTheDocument()
    await userEvent.click(within(warning).getByRole('button', { name: 'Show spoilers' }))
    expect(await screen.findByText('It shows the traitor.')).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('link', { name: 'Scroll' })[0]!)
    expect(await screen.findByText('Varn')).toBeInTheDocument()
    expect(screen.queryByText('Written by the queen')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show spoiler: Era' }))
    expect(screen.getByText('Written by the queen')).toBeInTheDocument()
    const relations = await screen.findByRole('region', { name: 'Relations' })
    const reveal = await within(relations).findByRole('button', { name: /^Show spoiler/ })
    expect(within(relations).queryByRole('link', { name: 'Treasury' })).not.toBeInTheDocument()
    await userEvent.click(reveal)
    expect(within(relations).getByRole('link', { name: 'Treasury' })).toBeInTheDocument()
  })

  it('shows spoilers to the author unfolded', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        row('s1', 'artifact', 'Mirror', {
          visibility: 'spoiler',
          summary: 'It shows the traitor.',
        }),
      ],
    })
    await renderApp('/v/v1/e/s1')
    expect(await screen.findByText('It shows the traitor.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Spoiler warning' })).not.toBeInTheDocument()
  })

  it('lands readers on an overview of the vault', async () => {
    serveVault()
    await renderApp('/v/v1', undefined, { readOnly: true })
    const dimensions = await screen.findByRole('region', { name: 'Dimensions' })
    expect(within(dimensions).getByRole('link', { name: 'Aetheria' })).toHaveAttribute(
      'href',
      '/v/v1/d/d1',
    )
    expect(within(dimensions).getByRole('link', { name: 'Timeline of Aetheria' })).toHaveAttribute(
      'href',
      '/v/v1/d/d1/timeline',
    )
    const browse = screen.getByRole('region', { name: 'Browse' })
    expect(within(browse).getByRole('link', { name: 'Artifacts' })).toHaveAttribute(
      'href',
      '/v/v1/k/artifact',
    )
    const latest = await screen.findByRole('region', { name: 'Recently updated' })
    expect(within(latest).getByRole('link', { name: /Crown/ })).toBeInTheDocument()
    expect(within(latest).queryByRole('link', { name: /Aetheria/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create dimension' })).not.toBeInTheDocument()
  })
})
