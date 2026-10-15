import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export type MapRecord = Domain<Schemas['MapRecord']>
export type MapDetail = Domain<Schemas['MapDetail']>
export type MapPin = Domain<Schemas['PinOut']>
export type EntityPins = Domain<Schemas['EntityPins']>
export type MapQuery = Omit<Query<'maps_get'>, 'as_reader'>

/** The live maps (of a location), by location then `sort_key`. */
export function useMaps(
  vault: string,
  location: string | null,
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  const query = location === null ? {} : { location }
  return useQuery({
    queryKey: keys.maps(vault, query),
    queryFn: () => source.maps(vault, query),
    enabled: options.enabled ?? true,
  })
}

/** A map with its pins (as of the cursor when `at` is given) and its breadcrumbs. */
export function useMapDetail(
  vault: string,
  map: string | null,
  query: MapQuery = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.mapDetail(vault, map ?? '', query),
    queryFn: () => source.mapDetail(vault, map ?? '', query),
    enabled: map !== null && (options.enabled ?? true),
  })
}

/** Where an entity is pinned ("show on map"). */
export function useEntityPins(vault: string, entity: string, options: { enabled?: boolean } = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entityPins(vault, entity),
    queryFn: () => source.entityPins(vault, entity),
    enabled: options.enabled ?? true,
  })
}
