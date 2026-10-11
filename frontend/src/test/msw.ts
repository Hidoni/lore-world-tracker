import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import type { components } from '@/api'

type Vault = components['schemas']['Vault']

type Registry = components['schemas']['Registry']

/** A vault registry: the core module and `modules` (enabled unless listed in `disabled`). */
export function makeRegistry(
  modules: readonly string[] = [],
  disabled: readonly string[] = [],
  extra: Partial<Registry> = {},
): Registry {
  return {
    kinds: [],
    field_types: [],
    link_types: [],
    consistency_rules: [],
    referenceable_slots: [
      { record_type: 'timeline', module: 'core', slots: ['branch_point'] },
      { record_type: 'event', module: 'core', slots: ['start', 'end'] },
    ],
    modules: ['core', ...modules].map((id) => ({
      id,
      name: id,
      description: '',
      depends_on: [],
      default_enabled: true,
      enabled: !disabled.includes(id),
    })),
    ...extra,
  }
}

/** Test API server (MSW). Tests add handlers with `server.use(...)`; unhandled requests fail. */
export const server = setupServer(
  http.get('*/api/v1/vaults/:vault/registry', () => HttpResponse.json(makeRegistry())),
  // The sidebar's kind trees: empty unless a test serves a vault (`serveVault`).
  http.get('*/api/v1/vaults/:vault/tree', () =>
    HttpResponse.json({ items: [], next_cursor: null }),
  ),
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
