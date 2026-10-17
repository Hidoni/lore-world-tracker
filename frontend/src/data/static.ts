import { createApiClient, PROBLEM_MEDIA_TYPE } from '@/api'

import { createHttpDataSource } from './http'
import {
  NotInExport,
  StaticProblem,
  type Handler,
  type Load,
  type ProblemError,
} from './static-core'
import { ENTITY_HANDLERS } from './static-entities'
import { MODULE_HANDLERS } from './static-modules'
import { TIME_HANDLERS } from './static-time'
import { WINDOW_HANDLERS } from './static-windows'
import type { DataSource } from './source'

/**
 * Static export (visibility-and-sharing.md §8, ADR 0016). `lore vault export-static` writes the
 * answers readers get from the API as files under `data/` (`/api/v1/<route>` →
 * `data/<route>.json`) and marks `index.html` with `<meta name="lore-static">`. The
 * `StaticDataSource` is the HTTP data source over a `fetch` that reads those files: the shapes and
 * the domain conversion are the server's by construction. Reads with free parameters (a prefix,
 * a cursor moment, a window) have a handler that answers from a recorded file; a read the export
 * doesn't hold yet answers `404 not_in_export`, which pages show like any failed read.
 */

const API_PREFIX = '/api/v1/'
/** Query parameters that don't change a static answer (a static export is always read as a reader). */
const IGNORED_PARAMS = new Set(['as_reader'])

export interface StaticConfig {
  /** Where the `data/` folder is, relative to the page (`data/`). */
  dataUrl: string
  /** The exported vault's id. */
  vault: string
}

/** The static export's configuration from `index.html`, or `null` when the app runs on a server. */
export function staticConfig(doc: Document = document): StaticConfig | null {
  const meta = doc.querySelector<HTMLMetaElement>('meta[name="lore-static"]')
  if (!meta) return null
  return { dataUrl: meta.content || 'data/', vault: meta.dataset.vault ?? '' }
}

function problem(
  status: number,
  code: string,
  title: string,
  detail: string,
  errors?: readonly ProblemError[],
): Response {
  const body = { type: `urn:lore:problem:${code}`, title, status, detail, code, errors }
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': PROBLEM_MEDIA_TYPE },
  })
}

/** The key tag names are compared by (the server's `tag_name_key`: NFKC, case-folded). */
function tagKey(name: string): string {
  return name.normalize('NFKC').toLowerCase()
}

interface TagRow {
  name: string
}

/** Reads with free parameters, by route pattern: answered from the recorded full answer. */
const HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  ...ENTITY_HANDLERS,
  ...TIME_HANDLERS,
  ...WINDOW_HANDLERS,
  [
    /^vaults\/[^/]+\/tags$/,
    async (load, route, params) => {
      const { items } = (await load(route)) as { items: TagRow[] }
      const prefix = tagKey(params.get('q') ?? '')
      const limit = Number(params.get('limit') ?? '200')
      return { items: items.filter((tag) => tagKey(tag.name).startsWith(prefix)).slice(0, limit) }
    },
  ],
  // Last: any recorded module read (`m/…`).
  ...MODULE_HANDLERS,
]

/**
 * A `fetch` answering API GETs from the export's files (`dataUrl`, resolved against the page).
 * Anything but a GET is refused like on a read-only server.
 */
export function createStaticFetch(
  dataUrl: string,
  fetchFile: (url: string) => Promise<Response> = (url) => globalThis.fetch(url),
): (request: Request) => Promise<Response> {
  const base = new URL(dataUrl, globalThis.document.baseURI)
  const cache = new Map<string, Promise<unknown>>()
  const load: Load = (route) => {
    let found = cache.get(route)
    if (!found) {
      found = fetchFile(new URL(`${route}.json`, base).href).then(async (response) => {
        if (!response.ok) throw new NotInExport(route)
        return response.json() as Promise<unknown>
      })
      found.catch(() => cache.delete(route))
      cache.set(route, found)
    }
    return found
  }

  return async (request) => {
    if (request.method !== 'GET') {
      return problem(403, 'read_only', 'Read-only', 'A static export can only be read.')
    }
    const url = new URL(request.url)
    if (!url.pathname.startsWith(API_PREFIX)) {
      return problem(404, 'not_found', 'Not found', `${url.pathname} is not an API route.`)
    }
    const route = url.pathname.slice(API_PREFIX.length)
    const params = new URLSearchParams(
      [...url.searchParams].filter(([name]) => !IGNORED_PARAMS.has(name)),
    )
    try {
      let body: unknown = undefined
      let handled = false
      for (const [pattern, handle] of HANDLERS) {
        const match = pattern.exec(route)
        if (match) {
          body = await handle(load, route, params, match.slice(1))
          handled = true
          break
        }
      }
      if (!handled) {
        if (params.size > 0) throw new NotInExport(route)
        body = await load(route)
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    } catch (error) {
      if (error instanceof StaticProblem) {
        return problem(error.status, error.code, error.title, error.message, error.errors)
      }
      if (!(error instanceof NotInExport)) throw error
      return problem(
        404,
        'not_in_export',
        'Not in this export',
        'This static export does not include this page yet.',
      )
    }
  }
}

/** The `DataSource` of a static export: the HTTP data source over `createStaticFetch`. */
export function createStaticDataSource(
  config: StaticConfig,
  fetchFile?: (url: string) => Promise<Response>,
): DataSource {
  const staticFetch = createStaticFetch(config.dataUrl, fetchFile)
  return createHttpDataSource(
    createApiClient({ baseUrl: globalThis.location.origin, fetch: staticFetch }),
  )
}
