/**
 * The vault route a link leads to (`/v/<vault>/…`, with its search), or `null` for links elsewhere,
 * to files and to anchors on the page. Hash-routed links (the static export) count by their hash.
 */
export function routeOf(anchor: HTMLAnchorElement, vault: string): string | null {
  const raw = anchor.getAttribute('href')
  if (raw === null || (raw.startsWith('#') && !raw.startsWith('#/'))) return null
  if ((anchor.target !== '' && anchor.target !== '_self') || anchor.hasAttribute('download')) {
    return null
  }
  const url = new URL(raw, window.location.href)
  if (url.origin !== window.location.origin) return null
  const route = url.hash.startsWith('#/') ? url.hash.slice(1) : url.pathname + url.search
  const base = `/v/${encodeURIComponent(vault)}`
  return route === base || route.startsWith(`${base}/`) || route.startsWith(`${base}?`)
    ? route
    : null
}
