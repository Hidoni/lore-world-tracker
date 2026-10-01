import { useQuery } from '@tanstack/react-query'

/** Subset of `GET /api/v1/meta` used by the placeholder shell. */
export interface Meta {
  app_version: string
  api_version: string
  read_only: boolean
}

// Plain fetch until the typed openapi-fetch client and HttpDataSource land (#4).
async function fetchMeta(): Promise<Meta> {
  const response = await fetch('/api/v1/meta', { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`GET /api/v1/meta failed with ${response.status}`)
  return (await response.json()) as Meta
}

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: fetchMeta, retry: false })
}
