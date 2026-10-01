import { ENGINE_VERSION } from '@lore/chronology'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HomePage } from './home-page'

function renderHomePage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <HomePage />
    </QueryClientProvider>,
  )
}

describe('HomePage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the server version from /api/v1/meta', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        app_version: '1.2.3',
        api_version: 'v1',
        read_only: false,
        exposed_vaults: [],
        features: [],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderHomePage()

    expect(await screen.findByText('1.2.3')).toBeInTheDocument()
    const [request] = fetchMock.mock.lastCall as [Request]
    expect(new URL(request.url).pathname).toBe('/api/v1/meta')
    expect(screen.getByText(ENGINE_VERSION)).toBeInTheDocument()
  })

  it('reports an unreachable backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 502 })))

    renderHomePage()

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument()
  })
})
