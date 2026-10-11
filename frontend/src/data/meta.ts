import { useQuery } from '@tanstack/react-query'

import { useDataSource } from './context'
import { keys } from './keys'

export type { Meta } from './source'

/** `GET /api/v1/meta`: server version, read-only mode, exposed vaults and features. */
export function useMeta() {
  const source = useDataSource()
  return useQuery({ queryKey: keys.meta(), queryFn: () => source.meta(), retry: false })
}
