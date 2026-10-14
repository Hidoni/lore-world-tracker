import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { defaultRows, graphQueries, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

// jsdom has no WebGL: the drawing is replaced by the names of its nodes.
vi.mock('@/modules/graph/views/graph-canvas', () => ({
  default: ({ nodes }: { nodes: { id: string; label: string }[] }) => (
    <ul aria-label="Drawn">
      {nodes.map((node) => (
        <li key={node.id}>{node.label}</li>
      ))}
    </ul>
  ),
}))

const WAIT = { timeout: 5000 }

beforeEach(() => {
  localStorage.clear()
})

function world(options: { graphLimit?: number } = {}) {
  return serveVault({
    modules: ['graph'],
    rows: defaultRows(),
    links: [{ id: 'l1', link_type: 'core.related', source_id: 'a1', target_id: 'a2' }],
    ...options,
  })
}

const lastQuery = () => graphQueries.at(-1) ?? {}

describe('graph page', () => {
  it('draws the graph and turns filters into the request', async () => {
    world()
    await renderApp('/v/v1/m/graph')
    const drawn = await screen.findByRole('list', { name: 'Drawn' }, WAIT)
    expect(await within(drawn).findByText('Crown')).toBeInTheDocument()
    const filters = screen.getByRole('complementary', { name: 'Graph filters' })

    await userEvent.click(within(filters).getByRole('checkbox', { name: 'Mentions' }))
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ include_mentions: 'false' })
    })
    await userEvent.click(within(filters).getByRole('checkbox', { name: 'Hierarchy' }))
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ include_hierarchy: 'false' })
    })
    await userEvent.click(within(filters).getByRole('checkbox', { name: 'Artifacts' }))
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ kind: 'artifact' })
    })
    await userEvent.click(within(filters).getByRole('checkbox', { name: 'related to' }))
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ link_type: 'core.related' })
    })
    await userEvent.selectOptions(within(filters).getByLabelText('Entities of'), 'all')
    await waitFor(() => {
      expect(lastQuery()).not.toHaveProperty('dimension')
    })
    // Orphans are hidden client-side: the dimension has no edges.
    await userEvent.click(within(filters).getByRole('checkbox', { name: 'Orphans' }))
    await waitFor(() => {
      expect(within(screen.getByRole('list', { name: 'Drawn' })).queryByText('Aetheria')).toBeNull()
    })
    expect(
      within(screen.getByRole('list', { name: 'Drawn' })).getByText('Crown'),
    ).toBeInTheDocument()
  })

  it('selects, finds and centers on an entity, as a list', async () => {
    world()
    await renderApp('/v/v1/m/graph')
    await screen.findByRole('list', { name: 'Drawn' }, WAIT)
    await userEvent.type(screen.getByRole('textbox', { name: 'Find in the graph' }), 'cro')
    expect(screen.getByText('1 found')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    const list = screen.getByRole('list', { name: 'Entities by connections' })
    await userEvent.click(within(list).getByRole('button', { name: 'Crown' }))
    const preview = screen.getByRole('complementary', { name: 'Selected entity' })
    expect(preview).toHaveTextContent('Crown')
    expect(within(preview).getByRole('link', { name: 'Open Crown' })).toHaveAttribute(
      'href',
      '/v/v1/e/a1',
    )
    await userEvent.click(within(preview).getByRole('button', { name: 'Show its neighborhood' }))
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ center: 'a1', depth: '2' })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Show the whole graph' }))
    await waitFor(() => {
      expect(lastQuery()).not.toHaveProperty('center')
    })
  })

  it('saves views and says when the graph is truncated', async () => {
    world({ graphLimit: 2 })
    await renderApp('/v/v1/m/graph')
    expect(await screen.findByText(/Too many entities/, {}, WAIT)).toBeInTheDocument()
    const filters = screen.getByRole('complementary', { name: 'Graph filters' })
    await userEvent.click(within(filters).getByRole('checkbox', { name: 'Mentions' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'View name' }), 'Plain')
    await userEvent.click(screen.getByRole('button', { name: 'Save view' }))
    await userEvent.click(within(filters).getByRole('button', { name: 'Reset filters' }))
    await waitFor(() => {
      expect(lastQuery()).not.toHaveProperty('include_mentions')
    })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Saved view' }), 'Plain')
    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ include_mentions: 'false' })
    })
  })
})
