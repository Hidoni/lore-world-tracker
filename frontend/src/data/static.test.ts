import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { createStaticDataSource, createStaticFetch, staticConfig } from './static'

const VAULT = 'v-atlas'

/** An export's files, by path under `data/`. */
const FILES: Record<string, unknown> = {
  'meta.json': { app_version: '1.0.0', read_only: true, schema_head: 'head' },
  [`vaults/${VAULT}/tags.json`]: {
    items: [
      { id: 't1', name: 'Magic', color: null, count: 3 },
      { id: 't2', name: 'Maritime', color: null, count: 1 },
      { id: 't3', name: 'War', color: null, count: 2 },
    ],
  },
  [`vaults/${VAULT}/link-types.json`]: { items: [] },
}

function files(requested: string[] = []) {
  return (url: string) => {
    requested.push(url)
    const path = new URL(url).pathname.replace(/^\/export\/data\//, '')
    const body = FILES[path]
    return Promise.resolve(
      body === undefined ? new Response('', { status: 404 }) : Response.json(body),
    )
  }
}

const get = (path: string, method = 'GET') => new Request(`http://localhost${path}`, { method })

describe('static export data source', () => {
  it('reads its configuration from index.html', () => {
    const doc = document.implementation.createHTMLDocument()
    expect(staticConfig(doc)).toBeNull()
    doc.head.innerHTML = `<meta name="lore-static" content="data/" data-vault="${VAULT}" />`
    expect(staticConfig(doc)).toEqual({ dataUrl: 'data/', vault: VAULT })
  })

  it('answers GETs from the recorded files, once per file', async () => {
    const requested: string[] = []
    const staticFetch = createStaticFetch('/export/data/', files(requested))
    const meta = await staticFetch(get('/api/v1/meta'))
    expect(meta.status).toBe(200)
    expect(await meta.json()).toEqual(FILES['meta.json'])
    // Previewing as a reader changes nothing: an export is always read as a reader.
    await staticFetch(get('/api/v1/meta?as_reader=true'))
    expect(requested).toEqual(['http://localhost:3000/export/data/meta.json'])
  })

  it('filters a recorded full answer for reads with free parameters', async () => {
    const staticFetch = createStaticFetch('/export/data/', files())
    const tags = async (query: string) =>
      (
        (await (await staticFetch(get(`/api/v1/vaults/${VAULT}/tags${query}`))).json()) as {
          items: { name: string }[]
        }
      ).items.map((tag) => tag.name)
    expect(await tags('')).toEqual(['Magic', 'Maritime', 'War'])
    expect(await tags('?q=ma')).toEqual(['Magic', 'Maritime'])
    expect(await tags('?q=MA&limit=1')).toEqual(['Magic'])
  })

  it('answers what the export lacks with not_in_export, and refuses writes', async () => {
    const staticFetch = createStaticFetch('/export/data/', files())
    const missing = await staticFetch(get(`/api/v1/vaults/${VAULT}/entities`))
    expect(missing.status).toBe(404)
    expect(await missing.json()).toMatchObject({ code: 'not_in_export' })
    // A recorded route asked with parameters it has no handler for is not guessed at.
    const filtered = await staticFetch(get(`/api/v1/vaults/${VAULT}/link-types?kind=x`))
    expect(filtered.status).toBe(404)
    const write = await staticFetch(get(`/api/v1/vaults/${VAULT}/entities`, 'POST'))
    expect(write.status).toBe(403)
    expect(await write.json()).toMatchObject({ code: 'read_only' })
  })

  it('is the HTTP data source over the files', async () => {
    const source = createStaticDataSource({ dataUrl: '/export/data/', vault: VAULT }, files())
    expect(await source.meta()).toMatchObject({ read_only: true })
    expect((await source.tags(VAULT, { q: 'w' })).items.map((tag) => tag.name)).toEqual(['War'])
    const failure = await source.entities(VAULT, {}).catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({ status: 404, code: 'not_in_export' })
  })
})
