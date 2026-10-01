import createClient, { type ClientOptions, type Middleware } from 'openapi-fetch'

import { toApiError } from './errors'
import type { paths } from './schema.gen'

export const CLIENT_HEADER = 'X-Lore-Client'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

/** Marks every mutating request as coming from the SPA (CSRF guard, security.md §2). */
export const clientHeaderMiddleware: Middleware = {
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method.toUpperCase())) request.headers.set(CLIENT_HEADER, 'web')
    return request
  },
}

/** Rejects every non-2xx response with an `ApiError`, so callers only ever see data. */
export const problemMiddleware: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw await toApiError(response)
    return undefined
  },
}

export const apiMiddleware: readonly Middleware[] = [clientHeaderMiddleware, problemMiddleware]

/** A typed client for the backend API. Data hooks use it through the `DataSource`, never directly. */
export function createApiClient(options: ClientOptions = {}) {
  const client = createClient<paths>(options)
  client.use(...apiMiddleware)
  return client
}

export type ApiClient = ReturnType<typeof createApiClient>

/**
 * The SPA's client: same origin, so `/api` goes to the backend (or Vite's dev proxy). `fetch` is
 * looked up per request so tests can stub the global.
 */
export const api = createApiClient({
  baseUrl: globalThis.location.origin,
  fetch: (request) => globalThis.fetch(request),
})

interface FetchResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/** Awaits a client call and returns its body. Failures were already thrown by `problemMiddleware`. */
export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await request
  if (error !== undefined || data === undefined) throw await toApiError(response)
  return data
}
