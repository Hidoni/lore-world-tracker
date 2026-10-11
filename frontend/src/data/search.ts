import { useQuery } from '@tanstack/react-query'

import { useDataSource } from './context'
import { keys } from './keys'
import type { Query } from './source'

export function useSearch(vault: string, query: Query<'search_search'>) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.search(vault, query),
    queryFn: () => source.search(vault, query),
    enabled: query.q.trim() !== '',
  })
}

export function useQuickSearch(vault: string, query: Query<'search_quick'>) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.quickSearch(vault, query),
    queryFn: () => source.quickSearch(vault, query),
    enabled: query.q.trim() !== '',
  })
}
