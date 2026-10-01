import { useQuery } from '@tanstack/react-query'

import { api, unwrap, type components } from '@/api'

/** `GET /api/v1/meta`: server version, read-only mode, exposed vaults and features. */
export type Meta = components['schemas']['MetaResponse']

// Calls the typed client directly until the DataSource/HttpDataSource layer lands (frontend.md §5).
function fetchMeta(): Promise<Meta> {
  return unwrap(api.GET('/api/v1/meta'))
}

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: fetchMeta, retry: false })
}
