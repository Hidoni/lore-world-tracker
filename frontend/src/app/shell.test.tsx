import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN } from '@/core/shell/shell-store'
import { makeVault, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

beforeEach(() => {
  server.use(
    http.get('*/api/v1/vaults/:id', ({ params }) =>
      HttpResponse.json(makeVault(String(params.id), 'Atlas')),
    ),
  )
})

describe('shell', () => {
  it('shows the vault in the top bar and its pages in the sidebar', async () => {
    await renderApp('/v/v1')
    expect(await screen.findByRole('link', { name: 'Atlas' })).toHaveAttribute(
      'href',
      '/?pick=true',
    )
    const nav = within(screen.getByRole('complementary', { name: 'Sidebar' }))
    expect(nav.getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Home',
      'Search',
      'Recent changes',
      'Consistency',
      'Trash',
      'Settings',
    ])
    expect(nav.getByRole('link', { name: 'Home' })).toHaveAttribute('data-status', 'active')
    expect(screen.getByRole('heading', { name: 'Vault home' })).toBeInTheDocument()
  })

  it('is keyboard navigable: skip link, sidebar links, panel toggles', async () => {
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await user.tab()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveFocus()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main')

    const hideSidebar = screen.getByRole('button', { name: 'Hide sidebar' })
    hideSidebar.focus()
    await user.keyboard('{Enter}')
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    await user.keyboard('{Enter}')
    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' })

    within(sidebar).getByRole('link', { name: 'Trash' }).focus()
    await user.keyboard('{Enter}')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/trash')
    })

    const showContext = screen.getByRole('button', { name: 'Show context panel' })
    showContext.focus()
    await user.keyboard(' ')
    expect(screen.getByRole('complementary', { name: 'Context' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide context panel' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('resizes the sidebar with the keyboard and remembers its width and panels', async () => {
    const user = userEvent.setup()
    const first = await renderApp('/v/v1')
    const handle = screen.getByRole('separator', { name: 'Resize sidebar' })
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_DEFAULT))
    handle.focus()
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_DEFAULT + 32))
    expect(screen.getByRole('complementary', { name: 'Sidebar' })).toHaveStyle({
      width: `${SIDEBAR_DEFAULT + 32}px`,
    })
    await user.keyboard('{End}')
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_MAX))
    await user.keyboard('{Home}{ArrowLeft}')
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_MIN))
    await user.keyboard('{ArrowRight}')
    await user.click(screen.getByRole('button', { name: 'Show context panel' }))
    first.unmount()

    await renderApp('/v/v1')
    expect(screen.getByRole('separator', { name: 'Resize sidebar' })).toHaveAttribute(
      'aria-valuenow',
      String(SIDEBAR_MIN + 16),
    )
    expect(screen.getByRole('complementary', { name: 'Context' })).toBeInTheDocument()
  })

  it('opens the navigation drawer from the menu button and closes it on navigation', async () => {
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await user.click(screen.getByRole('button', { name: 'Open navigation' }))
    const drawer = await screen.findByRole('dialog', { name: 'Navigation' })
    await user.click(within(drawer).getByRole('link', { name: 'Recent changes' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument()
    })
    expect(router.state.location.pathname).toBe('/v/v1/changes')
  })
})

describe('routes', () => {
  it.each([
    ['/v/v1/d/d1', 'Dimension'],
    ['/v/v1/d/d1/timeline', 'Timeline'],
    ['/v/v1/d/d1/events', 'Events'],
    ['/v/v1/calendars/c1/edit', 'Calendar editor'],
    ['/v/v1/search', 'Search'],
    ['/v/v1/changes', 'Recent changes'],
    ['/v/v1/trash', 'Trash'],
    ['/v/v1/consistency', 'Consistency'],
    ['/v/v1/settings', 'Settings'],
    ['/v/v1/settings/backups', 'Settings'],
  ])('%s renders its page', async (path, title) => {
    await renderApp(path)
    expect(await screen.findByRole('heading', { name: title, level: 1 })).toBeInTheDocument()
  })

  it.each(['/nowhere/at/all', '/v/v1/m/graph/view'])('shows a 404 page for %s', async (path) => {
    await renderApp(path)
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('validates the global search params and keeps moments exact', async () => {
    const huge = '123456789012345678901234567890'
    const { router } = await renderApp(`/v/v1?at=${huge}&tl=t1&cal=`)
    expect(router.state.location.search).toEqual({ at: huge, tl: 't1', cal: undefined })

    await act(() =>
      router.navigate({ to: '/v/$vault', params: { vault: 'v1' }, search: { at: '0' } }),
    )
    expect(router.state.location.searchStr).toBe('?at=0')
    await act(() =>
      router.navigate({ to: '/v/$vault', params: { vault: 'v1' }, search: { at: 'present' } }),
    )
    expect(router.state.location.search).toEqual({ at: 'present' })
  })
})
