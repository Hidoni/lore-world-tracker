import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { useWorkspace } from '@/core/workspace'
import { serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const sidebar = () => screen.getByRole('navigation', { name: 'Vault' })
const mainPane = () => screen.getByRole('region', { name: 'Main pane' })
const pane = (n: number) => screen.getByRole('region', { name: `Pane ${String(n)}` })
const tabs = (region: HTMLElement) =>
  within(within(region).getByRole('list', { name: /^Tabs/ }))
    .getAllByRole('listitem')
    .map((item) => {
      const tab = within(item).getAllByRole('button')[0]
      return `${tab?.textContent ?? ''}${tab?.getAttribute('aria-current') === 'page' ? ' *' : ''}`
    })

describe('workspace', () => {
  it('opens pages in tabs that follow the address bar', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await waitFor(() => {
      expect(tabs(mainPane())).toEqual(['Home *'])
    })
    // The only tab can't be closed.
    expect(within(mainPane()).queryByRole('button', { name: 'Close tab' })).not.toBeInTheDocument()

    // Following a link moves the shown tab.
    await user.click(await within(sidebar()).findByRole('link', { name: 'Treasury' }))
    await within(mainPane()).findByRole('heading', { name: 'Treasury', level: 1 })
    await waitFor(() => {
      expect(tabs(mainPane())).toEqual(['Treasury *'])
    })

    // A new tab opens the vault home; showing the other tab navigates back to it.
    await user.click(within(mainPane()).getByRole('button', { name: 'New tab' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1')
    })
    expect(tabs(mainPane())).toEqual(['Treasury', 'Home *'])
    await user.click(within(mainPane()).getByRole('button', { name: 'Treasury' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/a2')
    })
    expect(tabs(mainPane())).toEqual(['Treasury *', 'Home'])

    // Back shows the tab the address went back to.
    act(() => {
      router.history.back()
    })
    await waitFor(() => {
      expect(tabs(mainPane())).toEqual(['Treasury', 'Home *'])
    })

    // Closing the shown tab shows its neighbour.
    const home = within(mainPane()).getAllByRole('listitem')[1] ?? document.body
    await user.click(within(home).getByRole('button', { name: 'Close tab' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/a2')
    })
    expect(tabs(mainPane())).toEqual(['Treasury *'])
    expect(JSON.parse(localStorage.getItem('lore.workspace.v1') ?? '{}')).toMatchObject({
      panes: [{ tabs: [{ href: '/v/v1/e/a2' }] }],
    })
  })

  it('shows pages side by side, each pane with its own router', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1/e/a2')
    await within(mainPane()).findByRole('heading', { name: 'Treasury', level: 1 })

    await user.click(within(mainPane()).getByRole('button', { name: 'Open to the right' }))
    const right = pane(2)
    await within(right).findByRole('heading', { name: 'Treasury', level: 1 })
    expect(tabs(right)).toEqual(['Treasury *'])

    // Navigating in the main pane leaves the other one where it is.
    await user.click(within(sidebar()).getByRole('link', { name: 'Search' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/search')
    })
    expect(within(right).getByRole('heading', { name: 'Treasury', level: 1 })).toBeInTheDocument()
    expect(tabs(mainPane())).toEqual(['Search *'])

    // Panes resize from their border.
    const border = screen.getByRole('separator', { name: 'Resize pane 1' })
    expect(border).toHaveAttribute('aria-valuenow', '50')
    border.focus()
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(border).toHaveAttribute('aria-valuenow', '60')

    // Closing the main pane makes the other one the main pane, and the address follows it.
    await user.click(within(mainPane()).getByRole('button', { name: 'Close pane' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/a2')
    })
    expect(screen.queryByRole('region', { name: 'Pane 2' })).not.toBeInTheDocument()
    expect(tabs(mainPane())).toEqual(['Treasury *'])
  })

  it('follows links inside a pane in that pane, and opens them elsewhere with Alt', async () => {
    serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await within(sidebar()).findByRole('link', { name: 'Treasury' })

    // Alt+Shift-click opens a link to the right; Alt-click, in a new tab.
    fireEvent.click(within(sidebar()).getByRole('link', { name: 'Treasury' }), {
      altKey: true,
      shiftKey: true,
    })
    const right = pane(2)
    await within(right).findByRole('heading', { name: 'Treasury', level: 1 })
    expect(router.state.location.pathname).toBe('/v/v1')

    fireEvent.click(within(sidebar()).getByRole('link', { name: 'Trash' }), { altKey: true })
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/trash')
    })
    expect(tabs(mainPane())).toEqual(['Home', 'Trash *'])

    // The pane's links stay in the pane.
    await user.click(within(right).getByRole('button', { name: 'New tab' }))
    const recent = await within(right).findByRole('heading', { name: 'Atlas', level: 1 })
    expect(recent).toBeInTheDocument()
    expect(tabs(right)).toEqual(['Treasury', 'Home *'])
    expect(router.state.location.pathname).toBe('/v/v1/trash')
  })

  it('opens entities from the sidebar menu and remembers the workspace', async () => {
    serveVault()
    const user = userEvent.setup()
    const first = await renderApp('/v/v1')
    fireEvent.contextMenu(await within(sidebar()).findByRole('link', { name: 'Treasury' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Open to the right' }))
    await within(pane(2)).findByRole('heading', { name: 'Treasury', level: 1 })
    // Visiting it listed it under Recent too.
    const [treasury] = within(sidebar()).getAllByRole('link', { name: 'Treasury' })
    fireEvent.contextMenu(treasury ?? document.body)
    await user.click(await screen.findByRole('menuitem', { name: 'Open in a new tab' }))
    await waitFor(() => {
      expect(first.router.state.location.pathname).toBe('/v/v1/e/a2')
    })
    first.unmount()

    // Reopened at a page the main pane has a tab for, that tab shows.
    const second = await renderApp('/v/v1')
    await waitFor(() => {
      expect(tabs(mainPane())).toEqual(['Home *', 'Treasury'])
    })
    expect(second.router.state.location.pathname).toBe('/v/v1')
    expect(tabs(pane(2))).toEqual(['Treasury *'])
    expect(useWorkspace.getState().byVault.v1?.panes).toHaveLength(2)
  })
})
