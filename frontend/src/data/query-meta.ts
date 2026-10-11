import '@tanstack/react-query'

/** Per-query options read by the app's QueryClient (see `app/query-client.ts`). */
interface LoreQueryMeta extends Record<string, unknown> {
  /** `false`: the component shows the error itself, so no toast. */
  toast?: boolean
}

declare module '@tanstack/react-query' {
  interface Register {
    queryMeta: LoreQueryMeta
    mutationMeta: LoreQueryMeta
  }
}
