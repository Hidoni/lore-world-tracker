import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { fixtureModule, fixtureViewLoads } from '@/test/fixture-module'
import { makeRegistry, makeVault, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const RELIC = {
  key: 'relic',
  module: 'fixture',
  label: 'Relic',
  plural: 'Relics',
  icon: 'box',
  color: '#000000',
  description: '',
  allowed_parents: [],
  capabilities: {
    has_body: true,
    can_be_multiversal: false,
    has_existence: true,
    can_have_worldline: false,
    is_time_bound: false,
    is_system: false,
  },
  fields: [],
}

function serve(enabled: boolean) {
  server.use(
    http.get('*/api/v1/vaults/:id', ({ params }) =>
      HttpResponse.json(makeVault(String(params.id), 'Atlas')),
    ),
    http.get('*/api/v1/vaults/:vault/registry', () =>
      HttpResponse.json(makeRegistry(['fixture'], enabled ? [] : ['fixture'], { kinds: [RELIC] })),
    ),
  )
}

describe('module activation', () => {
  it('shows an enabled module’s contributions, merged into the KindRegistry', async () => {
    serve(true)
    await renderApp('/v/v1', [fixtureModule])
    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' })
    const section = await within(sidebar).findByRole('region', { name: 'Relic shelf' })
    const kind = within(section).getByTestId('fixture-kind')
    expect(kind).toHaveTextContent('Relics (fixture.first,fixture.later)')
    expect(kind).toHaveAttribute('data-icon', 'gem') // the module's icon over the server's
  })

  it('drops a disabled module’s contributions and routes', async () => {
    serve(false)
    await renderApp('/v/v1/m/fixture/view', [fixtureModule])
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Relic shelf' })).not.toBeInTheDocument()
  })

  it('loads a module route lazily', async () => {
    serve(true)
    const before = fixtureViewLoads()
    await renderApp('/v/v1/m/fixture/view', [fixtureModule])
    expect(await screen.findByRole('heading', { name: 'Fixture view' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fixtureViewLoads()).toBe(before + 1)
    })
  })

  it('doesn’t load a module route until it is visited', async () => {
    serve(true)
    const before = fixtureViewLoads()
    await renderApp('/v/v1', [fixtureModule])
    expect(await screen.findByRole('region', { name: 'Relic shelf' })).toBeInTheDocument()
    expect(fixtureViewLoads()).toBe(before)
  })
})
