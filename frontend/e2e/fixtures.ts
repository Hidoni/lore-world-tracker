import { test as base, expect, type APIRequestContext } from '@playwright/test'

/** Mutating requests from the SPA carry this header (security.md §2); the helpers do too. */
const HEADERS = { 'X-Lore-Client': 'web' }

/** A dimension's time spec: seconds, a trillion of them (enough for any journey). */
const DIMENSION_EXT = {
  base_unit: { singular: 'second', plural: 'seconds', abbr: 's' },
  duration: '1000000000000',
}

export interface Entity {
  id: string
  name: string
  kind: string
  revision: number
  body: unknown
}

async function ok<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  if (!response.ok()) {
    throw new Error(`${response.url()} answered ${response.status()}: ${await response.text()}`)
  }
  return (await response.json()) as T
}

/**
 * Fast setup through the API (testing.md §3): a fresh vault per test, and helpers to create and
 * read entities and links in it, so journeys only drive the UI for what they check.
 */
export class Lore {
  constructor(
    private readonly request: APIRequestContext,
    readonly vault: { id: string; name: string },
  ) {}

  /** The vault's API base (`/api/v1/vaults/<id>`). */
  get base(): string {
    return `/api/v1/vaults/${this.vault.id}`
  }

  /** The vault's page, or an entity's. */
  url(entityId?: string): string {
    return entityId === undefined ? `/v/${this.vault.id}` : `/v/${this.vault.id}/e/${entityId}`
  }

  async createEntity(
    kind: string,
    name: string,
    extra: Record<string, unknown> = {},
  ): Promise<Entity> {
    const body = { kind, name, ...(kind === 'dimension' ? { ext: DIMENSION_EXT } : {}), ...extra }
    const result = await ok<{ entity: Entity }>(
      await this.request.post(`${this.base}/entities`, { data: body, headers: HEADERS }),
    )
    return result.entity
  }

  /** A dimension: the one kind every vault has with a body (other kinds come with modules). */
  createDimension(name: string, extra: Record<string, unknown> = {}): Promise<Entity> {
    return this.createEntity('dimension', name, extra)
  }

  entity(id: string): Promise<Entity> {
    return this.request.get(`${this.base}/entities/${id}`).then((response) => ok<Entity>(response))
  }

  /** Changes an entity at its current revision. */
  async updateEntity(id: string, change: Record<string, unknown>): Promise<Entity> {
    const { revision } = await this.entity(id)
    const result = await ok<{ entity: Entity }>(
      await this.request.patch(`${this.base}/entities/${id}`, {
        data: { ...change, revision },
        headers: HEADERS,
      }),
    )
    return result.entity
  }

  async link(
    linkType: string,
    sourceId: string,
    targetId: string,
    extra: Record<string, unknown> = {},
  ): Promise<{ id: string }> {
    const result = await ok<{ link: { id: string } }>(
      await this.request.post(`${this.base}/links`, {
        data: { link_type: linkType, source_id: sourceId, target_id: targetId, ...extra },
        headers: HEADERS,
      }),
    )
    return result.link
  }

  /** The entities linking to or mentioning `id`. */
  async backlinks(id: string): Promise<{ entity: { id: string; name: string } }[]> {
    const result = await ok<{ items: { entity: { id: string; name: string } }[] }>(
      await this.request.get(`${this.base}/entities/${id}/backlinks`),
    )
    return result.items
  }
}

/**
 * `test` with a `lore` fixture: a new vault per test (moved to the data trash afterwards), and
 * the API helpers above. Journeys skip when no app runs (`E2E_BASE_URL`, set by `make e2e`).
 */
export const test = base.extend<{ lore: Lore }>({
  lore: async ({ request }, provide, testInfo) => {
    const name = `e2e ${testInfo.title}`.slice(0, 80)
    const vault = await ok<{ id: string; name: string }>(
      await request.post('/api/v1/vaults', { data: { name }, headers: HEADERS }),
    )
    await provide(new Lore(request, vault))
    await request.delete(`/api/v1/vaults/${vault.id}`, { headers: HEADERS })
  },
})

test.skip(!process.env.E2E_BASE_URL, 'E2E_BASE_URL is not set')

export { expect }
