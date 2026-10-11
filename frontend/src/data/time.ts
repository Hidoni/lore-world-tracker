import { useQueries, useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useMutations } from './context'
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

/** A dimension's timelines (the prime timeline and its branches, as a tree). */
export function useTimelines(vault: string, dimension: string | null) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.timelines(vault, dimension ?? ''),
    queryFn: () => source.timelines(vault, dimension ?? ''),
    enabled: dimension !== null,
  })
}

/**
 * Time points (and ends) resolved by the server (`POST /time/resolve`): previews for relative
 * anchors and end checks. Authors only (it's a `Mutations` call); `null` skips the request.
 */
export function useTimeResolution(vault: string, body: components['schemas']['ResolveIn'] | null) {
  const mutations = useMutations()
  return useQuery({
    queryKey: [vault, 'resolve', JSON.stringify(body)],
    queryFn: () => {
      if (mutations === null || body === null) throw new Error('Nothing to resolve.')
      return mutations.resolveTime(vault, body)
    },
    enabled: mutations !== null && body !== null,
    meta: { toast: false },
    placeholderData: (previous) => previous,
  })
}
