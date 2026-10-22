import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { defaultRows, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

/** GET requests the app sent (path + query), to see what loaded when. */
function trackReads(): string[] {
  const reads: string[] = []
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET') {
      const url = new URL(request.url)
      reads.push(url.pathname.replace('/api/v1/vaults/v1', '') + url.search)
    }
  })
  return reads
}

const sidebar = () => screen.getByRole('navigation', { name: 'Vault' })
const section = (name: string) => within(sidebar()).getByRole('region', { name })

describe('sidebar', () => {
  it('has a lazily loaded tree per kind', async () => {
    serveVault()
    const reads = trackReads()
    await renderApp('/v/v1')
    const artifacts = await within(sidebar()).findByRole('region', { name: 'Artifacts' })
    await within(artifacts).findByRole('link', { name: 'Treasury' })
    expect(
      within(section('Dimensions')).getByRole('link', { name: 'Aetheria' }),
    ).toBeInTheDocument()
    // Children load when their parent opens, a level at a time.
    expect(within(artifacts).queryByRole('link', { name: 'Crown' })).not.toBeInTheDocument()
    expect(reads.filter((read) => read.includes('parent='))).toEqual([])
    await userEvent.click(within(artifacts).getByRole('button', { name: 'Expand Treasury' }))
    await within(artifacts).findByRole('link', { name: 'Crown' })
    expect(within(artifacts).queryByRole('link', { name: 'Gem' })).not.toBeInTheDocument()
    expect(reads.filter((read) => read.includes('parent='))).toEqual([
      '/tree?kind=artifact&parent=a2',
    ])
    await userEvent.click(within(artifacts).getByRole('button', { name: 'Expand Crown' }))
    expect(await within(artifacts).findByRole('link', { name: 'Gem' })).toBeInTheDocument()
    // Collapsing a section is remembered.
    await userEvent.click(within(artifacts).getByRole('button', { name: 'Artifacts' }))
    expect(within(artifacts).queryByRole('link', { name: 'Treasury' })).not.toBeInTheDocument()
    expect(localStorage.getItem('lore.sidebar.collapsed')).toBe('["artifact"]')
  })

  it('marks multiversal entities', async () => {
    serveVault({
      rows: [...defaultRows(), row('m1', 'artifact', 'Everblade', { dimension_id: null })],
    })
    await renderApp('/v/v1')
    const blade = await within(sidebar()).findByRole('link', { name: 'Everblade' })
    expect(
      within(blade.closest('li') ?? document.body).getByTitle('Multiversal'),
    ).toBeInTheDocument()
  })

  it('renames, pins and trashes from the context menu', async () => {
    const writes = serveVault()
    await renderApp('/v/v1')
    const treasury = await within(sidebar()).findByRole('link', { name: 'Treasury' })
    fireEvent.contextMenu(treasury)
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Rename…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Rename Treasury' })
    await userEvent.clear(within(dialog).getByLabelText('Name'))
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Vault of Ages{Enter}')
    await within(sidebar()).findByRole('link', { name: 'Vault of Ages' })
    expect(writes.at(-1)).toMatchObject({
      method: 'PATCH',
      path: '/entities/a2',
      body: { name: 'Vault of Ages', revision: 1 },
    })

    fireEvent.contextMenu(within(sidebar()).getByRole('link', { name: 'Vault of Ages' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Pin' }))
    const pinned = await within(sidebar()).findByRole('region', { name: 'Pinned' })
    expect(within(pinned).getByRole('link', { name: 'Vault of Ages' })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('lore.pinned.v1') ?? '[]')).toEqual([
      { id: 'a2', name: 'Vault of Ages', kind: 'artifact' },
    ])

    fireEvent.contextMenu(within(section('Artifacts')).getByRole('link', { name: 'Vault of Ages' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Move to trash' }))
    await waitFor(() => {
      expect(
        within(section('Artifacts')).queryByRole('link', { name: 'Vault of Ages' }),
      ).not.toBeInTheDocument()
    })
    expect(writes.at(-1)).toMatchObject({ method: 'DELETE', path: '/entities/a2' })
    // Its child is a root meanwhile.
    expect(within(section('Artifacts')).getByRole('link', { name: 'Crown' })).toBeInTheDocument()
  })

  it('creates a child of the entity it was opened on', async () => {
    const writes = serveVault()
    await renderApp('/v/v1')
    fireEvent.contextMenu(await within(sidebar()).findByRole('link', { name: 'Treasury' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'New child…' }))
    const dialog = await screen.findByRole('dialog', { name: 'New artifact' })
    expect(await within(dialog).findByRole('radio', { name: 'Treasury' })).toBeChecked()
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Scepter')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        body: { kind: 'artifact', name: 'Scepter', parent_id: 'a2', dimension_id: 'd1' },
      })
    })
  })

  it('remembers recently visited and pinned entities per vault', async () => {
    serveVault()
    const { router } = await renderApp('/v/v1/e/a1')
    await screen.findByRole('heading', { name: 'Crown' })
    await userEvent.click(screen.getByRole('button', { name: 'Pin to the sidebar' }))
    expect(screen.getByRole('button', { name: 'Unpin' })).toHaveAttribute('aria-pressed', 'true')
    await act(() =>
      router.navigate({ to: '/v/$vault/e/$entity', params: { vault: 'v1', entity: 'a3' } }),
    )
    await screen.findByRole('heading', { name: 'Gem' })
    const recent = within(sidebar()).getByRole('region', { name: 'Recent' })
    expect(
      within(recent)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Gem', 'Crown'])
    expect(
      within(section('Pinned'))
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Crown'])
    expect(JSON.parse(localStorage.getItem('lore.recent.v1') ?? '[]')).toHaveLength(2)
  })

  it('offers no editing to readers', async () => {
    serveVault()
    await renderApp('/v/v1', undefined, { readOnly: true })
    const treasury = await within(sidebar()).findByRole('link', { name: 'Treasury' })
    expect(
      within(section('Artifacts')).queryByRole('button', { name: 'New artifact' }),
    ).not.toBeInTheDocument()
    fireEvent.contextMenu(treasury)
    const menu = await screen.findByRole('menu')
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((item) => item.textContent),
    ).toEqual(['Open in a new tab', 'Open to the right', 'Pin'])
  })
})

describe('drag and drop', () => {
  // jsdom has no layout: sidebar rows (and what's inside them) stack 32 px apart.
  const ROW = 32
  beforeEach(() => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: Element,
    ) {
      // The drag overlay starts where the picked-up (focused) row is.
      const row =
        this.closest('[data-tree-row]') ?? document.activeElement?.closest('[data-tree-row]')
      if (!row) return new DOMRect(0, 0, 0, 0)
      const index = [...document.querySelectorAll('[data-tree-row]')].indexOf(row)
      return new DOMRect(0, index * ROW, 240, ROW)
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  /** Picks `name` up with Space, moves `steps` rows (negative: up) and drops it. */
  async function drag(name: string, steps: number) {
    const link = within(sidebar()).getByRole('link', { name })
    act(() => {
      link.focus()
    })
    await userEvent.keyboard(' ')
    // The keyboard sensor moves 25 px per arrow press.
    const presses = Math.round((Math.abs(steps) * ROW) / 25)
    await userEvent.keyboard((steps < 0 ? '{ArrowUp}' : '{ArrowDown}').repeat(presses))
    await userEvent.keyboard(' ')
  }

  it('moves an entity onto an allowed parent', async () => {
    const writes = serveVault()
    await renderApp('/v/v1')
    const artifacts = await within(sidebar()).findByRole('region', { name: 'Artifacts' })
    await userEvent.click(await within(artifacts).findByRole('button', { name: 'Expand Treasury' }))
    await userEvent.click(await within(artifacts).findByRole('button', { name: 'Expand Crown' }))
    await within(artifacts).findByRole('link', { name: 'Gem' })
    // Rows: Dimensions, Aetheria, Artifacts, Treasury, Crown, Gem.
    await drag('Gem', -2)
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/entities/a3',
        body: { parent_id: 'a2', revision: 1 },
      })
    })
    expect(await screen.findByText('Moved Gem into Treasury')).toBeInTheDocument()
  })

  it('refuses parents the kind doesn’t allow, and moves to the top on a section heading', async () => {
    const writes = serveVault()
    await renderApp('/v/v1')
    const artifacts = await within(sidebar()).findByRole('region', { name: 'Artifacts' })
    await userEvent.click(await within(artifacts).findByRole('button', { name: 'Expand Treasury' }))
    await within(artifacts).findByRole('link', { name: 'Crown' })
    // Rows: Dimensions, Aetheria, Artifacts, Treasury, Crown.
    await drag('Crown', -3)
    expect(await screen.findByText('An artifact can’t be inside a dimension')).toBeInTheDocument()
    expect(screen.getByText('Crown was dropped on Aetheria.')).toBeInTheDocument() // live region
    expect(writes).toEqual([])
    await drag('Crown', -2)
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ path: '/entities/a1', body: { parent_id: null } })
    })
    expect(await screen.findByText('Moved Crown to the top')).toBeInTheDocument()
  })
})

describe('entity lists', () => {
  // jsdom has no layout: give the list's scroller a size so the virtualizer renders rows.
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(640)
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(960)
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(640)
    vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(960)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists a kind with filters and sorting', async () => {
    serveVault()
    const reads = trackReads()
    await renderApp('/v/v1/k/artifact')
    const table = await screen.findByRole('table', { name: 'Artifacts' })
    await within(table).findByRole('link', { name: 'Crown' })
    const names = () =>
      within(table)
        .getAllByRole('row')
        .slice(1)
        .map((r) => within(r).getAllByRole('cell')[0]?.textContent)
    expect(names()).toEqual(['Crown', 'Gem', 'Treasury'])
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Name', 'Era', 'Origin', 'Dimension', 'Updated'])
    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'Name (Z–A)')
    await waitFor(() => {
      expect(names()).toEqual(['Treasury', 'Gem', 'Crown'])
    })
    await userEvent.type(screen.getByLabelText('Name'), 'g')
    await waitFor(() => {
      expect(names()).toEqual(['Gem'])
    })
    expect(reads.at(-1)).toBe('/entities?kind=artifact&sort=-name&limit=200&q=g')
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    expect(await screen.findByText('No artifacts match these filters.')).toBeInTheDocument()
  })

  it('virtualizes long lists and loads pages while scrolling', async () => {
    const many = Array.from({ length: 10_000 }, (_, i) =>
      row(`x${String(i).padStart(5, '0')}`, 'artifact', `Item ${String(i).padStart(5, '0')}`),
    )
    serveVault({ rows: [row('d1', 'dimension', 'Aetheria'), ...many] })
    await renderApp('/v/v1/k/artifact')
    const table = await screen.findByRole('table', { name: 'Artifacts' }, { timeout: 5000 })
    await within(table).findByRole('link', { name: 'Item 00000' }, { timeout: 5000 })
    expect(screen.getByText('200+ artifacts')).toBeInTheDocument()
    // Only the visible window (plus overscan) is rendered.
    expect(within(table).getAllByRole('row').length).toBeLessThan(50)
    const scroller = within(table).getAllByRole('rowgroup')[1] ?? table
    act(() => {
      scroller.scrollTop = 190 * 36
      fireEvent.scroll(scroller)
    })
    await within(table).findByRole('link', { name: 'Item 00195' }, { timeout: 5000 })
    expect(await screen.findByText('400+ artifacts')).toBeInTheDocument()
    expect(within(table).queryByRole('link', { name: 'Item 00000' })).not.toBeInTheDocument()
    expect(within(table).getAllByRole('row').length).toBeLessThan(50)
  }, 30_000)
})

describe('trash', () => {
  it('restores and deletes permanently', async () => {
    const writes = serveVault({
      rows: [
        ...defaultRows().map((entity) =>
          entity.id === 'a1'
            ? { ...entity, deleted_at: '2026-10-11T11:00:00.000000+00:00' }
            : entity,
        ),
        row('t2', 'artifact', 'Broken Lamp', { deleted_at: '2026-10-11T12:00:00.000000+00:00' }),
      ],
    })
    await renderApp('/v/v1/trash')
    const list = await screen.findByRole('list', { name: 'Trashed entities' })
    const crown = within(list).getByRole('link', { name: 'Crown' }).closest('li') as HTMLElement
    expect(crown).toHaveTextContent('1 child stays outside the trash')
    await userEvent.click(within(crown).getByRole('button', { name: 'Restore Crown' }))
    await waitFor(() => {
      expect(within(list).queryByRole('link', { name: 'Crown' })).not.toBeInTheDocument()
    })
    expect(writes.at(-1)).toMatchObject({ method: 'POST', path: '/entities/a1/restore' })
    await userEvent.click(
      within(list).getByRole('button', { name: 'Delete Broken Lamp permanently' }),
    )
    const confirm = await screen.findByRole('dialog', {
      name: 'Delete “Broken Lamp” permanently?',
    })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete permanently' }))
    expect(await screen.findByText('The trash is empty.')).toBeInTheDocument()
    expect(writes.at(-1)).toMatchObject({ method: 'DELETE', path: '/entities/t2?purge=true' })
  })
})
