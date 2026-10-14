import type { EntityViewProps } from '@/core/modules'
import { mapper, reachableFrom, useCorrespondenceGraph } from '@/core/time'
import { useEntity } from '@/data'

/** What an event's start corresponds to in each dimension reachable from its own. */
export function useConcurrently(vault: string, entityId: string) {
  const entity = useEntity(vault, entityId)
  const graph = useCorrespondenceGraph(vault)
  const ext = (entity.data?.ext ?? {}) as { start_t?: bigint | null }
  const start = typeof ext.start_t === 'bigint' ? ext.start_t : null
  const home = entity.data?.dimension_id ?? null
  if (graph === null || start === null || home === null) return []
  return reachableFrom(graph, home).flatMap((dimension) => {
    const t = mapper(graph, home, dimension)?.(start) ?? null
    return t === null ? [] : [{ dimension, t }]
  })
}

/** Shown when the event's start maps to at least one other dimension. */
export function useConcurrentlyShown({ vault, entityId }: EntityViewProps): boolean {
  return useConcurrently(vault, entityId).length > 0
}
