import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { defineModule } from '@/core/modules'
import { useTheme } from '@/lib/theme'
import { expectAccessible } from '@/test/axe'
import { defaultRows, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const palette = () => screen.findByRole('dialog', { name: 'Command palette' })
const options = (dialog: HTMLElement) =>
  within(dialog)
    .getAllByRole('option')
    .map((option) => option.textContent)

describe('command palette', () => {
  it('opens with Ctrl+K, shows recent entities and finds others by name', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1/e/a3')
    await screen.findByRole('heading', { name: 'Gem' })
    await user.keyboard('{Control>}k{/Control}')
    const dialog = await palette()
    // Recent first (Gem was just visited), then the commands.
    expect(options(dialog)[0]).toBe('Gem')
    expect(options(dialog)).toContain('New artifact…')
    expect(
      await within(dialog).findByRole('option', { name: /^Go to Aetheria/ }),
    ).toBeInTheDocument()
    await user.type(within(dialog).getByRole('combobox'), 'cro')
    await within(dialog).findByRole('option', { name: /^Crown/ })
    expect(options(dialog)[0]).toMatch(/^Crown/)
    expect(options(dialog)).toContain('Search everything for “cro”')
    // The first entry is selected: Enter opens it.
    await user.keyboard('{Enter}')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/a1')
    })
    expect(screen.queryByRole('dialog', { name: 'Command palette' })).not.toBeInTheDocument()
  })

  it('navigates with the arrow keys and runs commands', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await user.click(await screen.findByRole('button', { name: /Search/ }))
    const dialog = await palette()
    await user.type(within(dialog).getByRole('combobox'), 'trash')
    expect(options(dialog)).toEqual(['Go to trash', 'Search everything for “trash”'])
    const selected = () => within(dialog).getByRole('option', { selected: true }).textContent
    expect(selected()).toBe('Go to trash')
    await user.keyboard('{ArrowDown}')
    expect(selected()).toBe('Search everything for “trash”')
    await user.keyboard('{ArrowUp}{Enter}')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/trash')
    })

    await user.keyboard('{Control>}k{/Control}')
    await user.type(within(await palette()).getByRole('combobox'), 'new art')
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('dialog', { name: 'New artifact' })).toBeInTheDocument()
  })

  it('opens the search page and toggles the theme', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    useTheme.getState().setPreference('light')
    await user.keyboard('{Control>}k{/Control}')
    await user.type(within(await palette()).getByRole('combobox'), 'dark')
    await user.click(screen.getByRole('option', { name: 'Switch to the dark theme' }))
    expect(useTheme.getState().resolved).toBe('dark')

    await user.keyboard('{Control>}k{/Control}')
    await user.type(within(await palette()).getByRole('combobox'), 'crown')
    await user.click(screen.getByRole('option', { name: 'Search everything for “crown”' }))
    await waitFor(() => {
      expect(router.state.location.href).toBe('/v/v1/search?q=crown')
    })
    useTheme.getState().setPreference('system')
  })

  it('runs module commands', async () => {
    serveVault({ modules: ['maps'] })
    const run = vi.fn(({ navigate }: { navigate: (to: string) => void }) => {
      navigate('/v/v1/changes')
    })
    const maps = defineModule({
      id: 'maps',
      commands: [{ id: 'maps.open', title: 'Open the world map', keywords: ['atlas'], run }],
    })
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1', [maps])
    await user.keyboard('{Control>}k{/Control}')
    await user.type(within(await palette()).getByRole('combobox'), 'atlas')
    await user.click(screen.getByRole('option', { name: 'Open the world map' }))
    expect(run).toHaveBeenCalledWith(expect.objectContaining({ vault: 'v1' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/changes')
    })
  })
})

describe('shortcuts sheet', () => {
  it('opens with ? outside text fields', async () => {
    serveVault()
    const user = userEvent.setup()
    await renderApp('/v/v1/k/artifact')
    await user.type(await screen.findByLabelText('Name'), '?')
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('heading', { name: 'Artifacts' }))
    await user.keyboard('?')
    const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' })
    expect(sheet).toHaveTextContent('Ctrl/⌘ K')
    // Grouped by where they work, the timeline's and the outline's included.
    const timeline = within(sheet).getByRole('region', { name: 'Timeline (when focused)' })
    expect(within(timeline).getByText('Go to a date')).toBeInTheDocument()
    expect(within(sheet).getByRole('region', { name: 'Event outline' })).toBeInTheDocument()
    await expectAccessible(sheet)
  })
})

describe('search page', () => {
  const vault = () =>
    serveVault({
      rows: [
        ...defaultRows(),
        row('w1', 'artifact', 'Writer', {
          body: {
            type: 'doc',
            content: [
              { type: 'paragraph', content: [{ type: 'text', text: 'Of crowns and gems' }] },
            ],
          },
        }),
        row('d2', 'dimension', 'Borealis'),
        row('b1', 'artifact', 'Crown of Borealis', { dimension_id: 'd2' }),
      ],
    })
  const results = () =>
    within(screen.getByRole('list', { name: 'Results' }))
      .getAllByRole('link')
      .map((link) => link.textContent)

  it('searches with highlighted snippets and URL filters', async () => {
    vault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1/search?q=crown')
    await screen.findByRole('list', { name: 'Results' })
    expect(results()).toEqual(['Crown', 'Writer', 'Crown of Borealis'])
    const writer = screen.getByRole('link', { name: 'Writer' }).closest('li') as HTMLElement
    expect(within(writer).getByText('crown').tagName).toBe('MARK')
    expect(writer).toHaveTextContent('Of crowns and gems(in the body)')

    await user.selectOptions(screen.getByLabelText('Dimension'), 'Borealis')
    await waitFor(() => {
      expect(results()).toEqual(['Crown of Borealis'])
    })
    expect(router.state.location.search).toEqual({ q: 'crown', dimension: 'd2' })

    await user.selectOptions(screen.getByLabelText('Dimension'), 'All dimensions')
    await user.selectOptions(screen.getByLabelText('Kind'), 'Dimensions')
    await user.clear(screen.getByLabelText('Search for'))
    await user.type(screen.getByLabelText('Search for'), 'bor{Enter}')
    await waitFor(() => {
      expect(results()).toEqual(['Borealis'])
    })
    expect(router.state.location.search).toEqual({ q: 'bor', kind: 'dimension' })
  })

  it('loads more results', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        ...Array.from({ length: 25 }, (_, i) =>
          row(`x${String(i).padStart(2, '0')}`, 'artifact', `Relic ${String(i).padStart(2, '0')}`),
        ),
      ],
    })
    const user = userEvent.setup()
    await renderApp('/v/v1/search?q=relic')
    await screen.findByRole('list', { name: 'Results' })
    expect(results()).toHaveLength(20)
    await user.click(screen.getByRole('button', { name: 'Show more results' }))
    await waitFor(() => {
      expect(results()).toHaveLength(25)
    })
    expect(screen.queryByRole('button', { name: 'Show more results' })).not.toBeInTheDocument()
  })

  it('renders module documents with their module’s renderer', async () => {
    serveVault({ modules: ['lexicon'] })
    server.use(
      http.get('*/api/v1/vaults/v1/search', () =>
        HttpResponse.json({
          items: [
            {
              doc_type: 'lexicon.word',
              doc_id: 'w9',
              entity_id: 'a1',
              kind: 'artifact',
              name: 'kael',
              icon: null,
              color: null,
              dimension_id: 'd1',
              visibility: 'public',
              snippet: null,
            },
          ],
          next_cursor: null,
        }),
      ),
    )
    const lexicon = defineModule({
      id: 'lexicon',
      searchResultRenderers: {
        'lexicon.word': ({ hit }) => <span>Word: {String(hit.name)}</span>,
      },
    })
    await renderApp('/v/v1/search?q=kael', [lexicon])
    expect(await screen.findByText('Word: kael')).toBeInTheDocument()
  })

  it('says when nothing matches', async () => {
    vault()
    await renderApp('/v/v1/search?q=zzz')
    expect(await screen.findByText('Nothing matches “zzz”.')).toBeInTheDocument()
  })
})
