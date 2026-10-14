import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'
import type { Query } from './source'

export type GraphData = Domain<components['schemas']['Graph']>
export type GraphQuery = Omit<Query<'graph_graph'>, 'as_reader'>

/** The graph (docs/modules/graph.md): the whole vault, a dimension, or around `center`. */
export function useGraph(vault: string, query: GraphQuery, options: { enabled?: boolean } = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.graph(vault, query),
    queryFn: () => source.graph(vault, query),
    // Changing a filter keeps the drawn graph until the new one arrives.
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  })
}
