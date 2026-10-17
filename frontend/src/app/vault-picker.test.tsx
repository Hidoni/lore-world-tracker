import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { lastVault, rememberVault } from '@/core/shell'
import { makeVault, problem, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const ATLAS = makeVault('v-atlas', 'Atlas')
const BOREAS = makeVault('v-boreas', 'Boreas')

/** An in-memory vault list served by MSW; returns the requests it saw. */
function serveVaults(initial = [ATLAS, BOREAS]) {
  let vaults = [...initial]
  const requests: { method: string; url: string; body: unknown; client: string | null }[] = []
  const record = async (request: Request) => {
    requests.push({
      method: request.method,
      url: new URL(request.url).pathname,
      body: request.method === 'GET' || request.method === 'DELETE' ? null : await request.json(),
      client: request.headers.get('X-Lore-Client'),
    })
  }
  server.use(
    http.get('*/api/v1/vaults', () => HttpResponse.json({ items: vaults, problems: [] })),
    http.get('*/api/v1/vaults/:id', ({ params }) => {
      const found = vaults.find((vault) => vault.id === params.id)
      return found ? HttpResponse.json(found) : problem(404, 'not_found', 'Not found', 'No vault.')
    }),
    http.post('*/api/v1/vaults', async ({ request }) => {
      await record(request)
      const { name } = requests.at(-1)?.body as { name: string }
      const created = makeVault(`v-${name.toLowerCase()}`, name)
      vaults = [created, ...vaults]
      return HttpResponse.json(created, { status: 201 })
    }),
    http.patch('*/api/v1/vaults/:id', async ({ request, params }) => {
      await record(request)
      const { name } = requests.at(-1)?.body as { name: string }
      vaults = vaults.map((vault) => (vault.id === params.id ? { ...vault, name } : vault))
      return HttpResponse.json(vaults.find((vault) => vault.id === params.id))
    }),
    http.delete('*/api/v1/vaults/:id', async ({ request, params }) => {
      await record(request)
      vaults = vaults.filter((vault) => vault.id !== params.id)
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return requests
}

describe('vault picker', () => {
  it('lists the vaults with the server version and opens one', async () => {
    serveVaults()
    const { router } = await renderApp('/')
    const list = await screen.findByRole('list', { name: 'Vaults' })
    expect(
      within(list)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Atlas', 'Boreas'])
    expect(await screen.findByTestId('server-version')).toHaveTextContent('1.2.3')

    await userEvent.click(within(list).getByRole('link', { name: 'Boreas' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v-boreas')
    })
    expect(lastVault()).toBe('v-boreas')
  })

  it('creates a vault', async () => {
    const requests = serveVaults()
    await renderApp('/')
    await userEvent.type(await screen.findByLabelText('New vault'), '  Cygnus ')
    await userEvent.click(screen.getByRole('button', { name: 'Create vault' }))

    expect(await screen.findByRole('link', { name: 'Cygnus' })).toBeInTheDocument()
    expect(requests).toEqual([
      { method: 'POST', url: '/api/v1/vaults', body: { name: 'Cygnus' }, client: 'web' },
    ])
    expect(screen.getByLabelText('New vault')).toHaveValue('')
  })

  it('shows API errors as toasts', async () => {
    serveVaults()
    server.use(
      http.post('*/api/v1/vaults', () =>
        problem(422, 'validation_error', 'Invalid input', 'The name is too long.'),
      ),
    )
    await renderApp('/')
    await userEvent.type(await screen.findByLabelText('New vault'), 'Dorado')
    await userEvent.click(screen.getByRole('button', { name: 'Create vault' }))

    expect(await screen.findByText('Invalid input')).toBeInTheDocument()
    expect(screen.getByText('The name is too long.')).toBeInTheDocument()
  })

  it('renames a vault', async () => {
    const requests = serveVaults()
    await renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Atlas' }))
    const dialog = await screen.findByRole('dialog', { name: 'Rename vault' })
    const input = within(dialog).getByLabelText('Name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Atlas Prime{Enter}')

    expect(await screen.findByRole('link', { name: 'Atlas Prime' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(requests).toEqual([
      {
        method: 'PATCH',
        url: '/api/v1/vaults/v-atlas',
        body: { name: 'Atlas Prime' },
        client: 'web',
      },
    ])
  })

  it('moves a vault to the trash after confirmation', async () => {
    const requests = serveVaults()
    rememberVault('v-atlas')
    await renderApp('/?pick=true')
    await userEvent.click(await screen.findByRole('button', { name: 'Move Atlas to the trash' }))
    let dialog = await screen.findByRole('dialog', { name: 'Move “Atlas” to the trash?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(requests).toEqual([])

    await userEvent.click(screen.getByRole('button', { name: 'Move Atlas to the trash' }))
    dialog = await screen.findByRole('dialog', { name: 'Move “Atlas” to the trash?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move to trash' }))

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Atlas' })).not.toBeInTheDocument()
    })
    expect(requests).toEqual([
      { method: 'DELETE', url: '/api/v1/vaults/v-atlas', body: null, client: 'web' },
    ])
    expect(lastVault()).toBeNull()
  })

  it('reopens the last-opened vault unless asked to pick', async () => {
    serveVaults()
    rememberVault('v-boreas')
    const { router } = await renderApp('/')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v-boreas')
    })

    const picking = await renderApp('/?pick=true')
    expect(
      await within(picking.container).findByRole('list', { name: 'Vaults' }),
    ).toBeInTheDocument()
    expect(picking.router.state.location.pathname).toBe('/')
  })

  it('forgets a last-opened vault that no longer exists', async () => {
    serveVaults()
    rememberVault('v-gone')
    const { router } = await renderApp('/')
    expect(await screen.findByRole('list', { name: 'Vaults' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
    expect(lastVault()).toBeNull()
  })

  it('migrates a vault whose schema is behind', async () => {
    const stale = {
      ...BOREAS,
      schema_status: { state: 'needs_migration', revision: 'old', head: 'head' },
    }
    let vaults = [ATLAS, stale]
    let migrated: string | null = null
    server.use(
      http.get('*/api/v1/vaults', () => HttpResponse.json({ items: vaults, problems: [] })),
      http.post('*/api/v1/vaults/:id/migrate', ({ params }) => {
        migrated = params.id as string
        vaults = [ATLAS, BOREAS]
        return HttpResponse.json({
          vault: BOREAS,
          from_revision: 'old',
          to_revision: 'head',
          backup: null,
        })
      }),
    )
    await renderApp('/')
    const list = await screen.findByRole('list', { name: 'Vaults' })
    expect(within(list).getAllByRole('button', { name: 'Migrate' })).toHaveLength(1)
    await userEvent.click(within(list).getByRole('button', { name: 'Migrate' }))
    expect(await screen.findByText('Boreas is up to date')).toBeInTheDocument()
    expect(migrated).toBe('v-boreas')
    await waitFor(() => {
      expect(within(list).queryByRole('button', { name: 'Migrate' })).not.toBeInTheDocument()
    })
  })

  it('shows folders that cannot be opened, the empty state and load errors', async () => {
    server.use(
      http.get('*/api/v1/vaults', () =>
        HttpResponse.json({
          items: [],
          problems: [
            { folder: 'broken', code: 'manifest_invalid', detail: 'vault.json is invalid' },
          ],
        }),
      ),
    )
    const first = await renderApp('/')
    expect(await screen.findByText(/No vaults yet/)).toBeInTheDocument()
    expect(screen.getByText('broken')).toBeInTheDocument()
    expect(screen.getByText(/vault\.json is invalid/)).toBeInTheDocument()
    first.unmount()

    server.use(http.get('*/api/v1/vaults', () => problem(500, 'internal', 'Server error', 'Boom.')))
    await renderApp('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t load the vaults: Boom.')
    expect(screen.queryByText('Server error')).not.toBeInTheDocument() // no toast: shown inline
  })
})
