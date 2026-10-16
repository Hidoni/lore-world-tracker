import type { Middleware } from 'openapi-fetch'

/**
 * "Preview as reader" (frontend.md §13): while it is on, every read carries `as_reader=true`, so
 * the server answers as it would to a reader. One flag for the app (the toggle in the top bar).
 */
let previewing = false

export function isPreviewingAsReader(): boolean {
  return previewing
}

export function setPreviewingAsReader(on: boolean): void {
  previewing = on
}

/** `url` as the current mode reads it (`as_reader=true` added while previewing). */
export function readerUrl(url: string): string {
  if (!previewing) return url
  return `${url}${url.includes('?') ? '&' : '?'}as_reader=true`
}

/** Adds `as_reader=true` to every GET while previewing as a reader. */
export const readerPreviewMiddleware: Middleware = {
  onRequest({ request }) {
    if (!previewing || request.method.toUpperCase() !== 'GET') return request
    const url = new URL(request.url)
    url.searchParams.set('as_reader', 'true')
    return new Request(url, request)
  },
}
