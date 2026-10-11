import { useQueries, useQuery } from '@tanstack/react-query'

import { useDataSource } from './context'
import { keys } from './keys'
import type { Entity } from './source'

const DIMENSIONS = { kind: ['dimension'], limit: 100 }

/** The vault's dimensions (summaries, by name). */
export function useDimensions(vault: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entities(vault, DIMENSIONS),
    queryFn: () => source.entities(vault, DIMENSIONS),
  })
}

/**
 * The calendars of a dimension as full entities (`ext`: definition, revision, resolved anchors),
 * sharing the entity cache with `useEntity`. `null` skips the fetch.
 */
export function useDimensionCalendars(
  vault: string,
  dimension: string | null,
): { calendars: Entity[]; isPending: boolean } {
  const source = useDataSource()
  const query = { kind: ['calendar'], dimension: dimension ?? '', limit: 100 }
  const list = useQuery({
    queryKey: keys.entities(vault, query),
    queryFn: () => source.entities(vault, query),
    enabled: dimension !== null,
  })
  const ids = (list.data?.items ?? []).map((item) => item.id)
  const full = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.entity(vault, id, {}),
      queryFn: () => source.entity(vault, id, {}),
    })),
  })
  const calendars = full.flatMap((result) => (result.data === undefined ? [] : [result.data]))
  return {
    calendars,
    isPending: dimension !== null && (list.isPending || full.some((result) => result.isPending)),
  }
}
