import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export type MapRecord = Domain<Schemas['MapRecord']>
export type MapDetail = Domain<Schemas['MapDetail']>
export type MapPin = Domain<Schemas['PinOut']>
export type MapRegion = Domain<Schemas['RegionOut']>
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

export function useCreateMap(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['MapCreate']) => mutations.createMap(vault, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateMap(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ map, body }: { map: string; body: Schemas['MapUpdate'] }) =>
      mutations.updateMap(vault, map, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeleteMap(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (map: string) => mutations.deleteMap(vault, map),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useCreatePin(vault: string, map: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['PinCreate']) => mutations.createPin(vault, map, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdatePin(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ pin, body }: { pin: string; body: Schemas['PinUpdate'] }) =>
      mutations.updatePin(vault, pin, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeletePin(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (pin: string) => mutations.deletePin(vault, pin),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useCreateRegion(vault: string, map: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['RegionCreate']) => mutations.createRegion(vault, map, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateRegion(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ region, body }: { region: string; body: Schemas['RegionUpdate'] }) =>
      mutations.updateRegion(vault, region, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeleteRegion(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (region: string) => mutations.deleteRegion(vault, region),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
