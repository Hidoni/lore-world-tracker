import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export type LocationNode = Domain<Schemas['LocationNode']>
export type LocationEvent = Domain<Schemas['LocationEvent']>

/** Levels of the locations module's containment tree (`GET /m/locations/tree`). */
export function useLocationTree(
  vault: string,
  query: Query<'locations_tree'> = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.locationTree(vault, query),
    queryFn: () => source.locationTree(vault, query),
    enabled: options.enabled ?? true,
  })
}

/** Events at a location (and inside it) on a timeline, by start. */
export function useLocationEvents(
  vault: string,
  location: string,
  timeline: string | null,
  query: Omit<Query<'locations_events'>, 'timeline'> = {},
) {
  const source = useDataSource()
  const full = { ...query, timeline: timeline ?? '' }
  return useQuery({
    queryKey: keys.locationEvents(vault, location, full),
    queryFn: () => source.locationEvents(vault, location, full),
    enabled: timeline !== null,
    placeholderData: (previous) => previous,
  })
}

/** Who and what resides at a location (`locations.resides_in` links to it). */
export function useLocationResidents(vault: string, location: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.locationResidents(vault, location),
    queryFn: () => source.locationResidents(vault, location),
  })
}
