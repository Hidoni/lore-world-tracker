import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import type { components } from '@/api'

type Vault = components['schemas']['Vault']

/** Test API server (MSW). Tests add handlers with `server.use(...)`; unhandled requests fail. */
export const server = setupServer(
  http.get('*/api/v1/meta', () =>
    HttpResponse.json({
      app_version: '1.2.3',
      api_version: 'v1',
      read_only: false,
      exposed_vaults: [],
      features: [],
    }),
  ),
)

export function makeVault(id: string, name: string, overrides: Partial<Vault> = {}): Vault {
  return {
    id,
    name,
    folder: name.toLowerCase(),
    created_at: '2026-10-01T10:00:00.000000+00:00',
    created_by_app_version: '0.1.0',
    modified_at: '2026-10-10T10:00:00.000000+00:00',
    published: false,
    schema_status: { state: 'current', revision: 'head', head: 'head' },
    ...overrides,
  }
}

export function problem(status: number, code: string, title: string, detail: string) {
  return HttpResponse.json(
    { type: 'about:blank', status, code, title, detail },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}
