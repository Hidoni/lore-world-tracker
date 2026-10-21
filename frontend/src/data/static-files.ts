// What the app needs of a static export before (and without) its data source: whether this is
// one, and its downloads. The data source itself (`static.ts`) is loaded only by a static export
// (frontend.md §12).

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

/** Query parameters that only bust caches or that a static export ignores. */
const IGNORED = new Set(['as_reader', 'v'])

/** The key of a query in a reads file (`modules.py` `query_key`): sorted pairs, without `at`. */
export function queryKey(params: URLSearchParams): string {
  const pairs = [...params].filter(([name]) => name !== 'at' && !IGNORED.has(name))
  pairs.sort(([a, x], [b, y]) => (a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0))
  return JSON.stringify(pairs)
}

let files: { base: string; paths: Record<string, string> } | null = null

/** Loads the export's list of downloads (`static/files`) once, before the app renders. */
export async function loadStaticFiles(dataUrl: string, vault: string): Promise<void> {
  const base = new URL(dataUrl, globalThis.document.baseURI).href
  try {
    const response = await globalThis.fetch(new URL(`vaults/${vault}/static/files.json`, base))
    files = { base, paths: response.ok ? ((await response.json()) as Record<string, string>) : {} }
  } catch {
    files = { base, paths: {} }
  }
}

/**
 * Where a static export holds the download of `route` (`m/…`) with `params` (a missing file when
 * the export has none: not one readers can get), or `null` without a static export.
 */
export function staticFileUrl(route: string, params: Record<string, string> = {}): string | null {
  if (files === null) return null
  const found = files.paths[`${route}?${queryKey(new URLSearchParams(params))}`]
  return new URL(found ?? 'not-in-export', files.base).href
}
