import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { EntityWriteResult, Query } from './source'

type Schemas = components['schemas']

export type { Entity, EntityPage, EntityWriteResult } from './source'

/** The vault's registry (kinds, fields, link types, modules); `enabled: false` skips the fetch. */
export function useRegistry(vault: string, options: { enabled?: boolean } = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.registry(vault),
    queryFn: () => source.registry(vault),
    enabled: options.enabled ?? true,
    staleTime: 60_000,
  })
}

export function useEntities(vault: string, query: Query<'entities_list'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entities(vault, query),
    queryFn: () => source.entities(vault, query),
  })
}

export function useEntity(
  vault: string,
  id: string,
  query: Query<'entities_get'> = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entity(vault, id, query),
    queryFn: () => source.entity(vault, id, query),
    enabled: options.enabled ?? true,
  })
}

export function useChildren(vault: string, id: string, query: Query<'entities_children'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.children(vault, id, query),
    queryFn: () => source.children(vault, id, query),
  })
}

export function useTree(vault: string, query: Query<'tree_get'> = {}) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.tree(vault, query), queryFn: () => source.tree(vault, query) })
}

export function useTrash(vault: string, query: Query<'trash_list'> = {}) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.trash(vault, query), queryFn: () => source.trash(vault, query) })
}

/** After a write: invalidate what its `affected` names. */
function useAfterWrite(vault: string) {
  const client = useQueryClient()
  return (result: { affected: Schemas['Affected'] }) =>
    invalidateAffected(client, vault, result.affected)
}

export function useCreateEntity(vault: string) {
  const mutations = useRequiredMutations()
  const after = useAfterWrite(vault)
  return useMutation({
    mutationFn: (body: Schemas['EntityCreate']) => mutations.createEntity(vault, body),
    onSuccess: after,
  })
}

/**
 * Saves an entity. A `409 revision_conflict` isn't toasted: `isRevisionConflict(error)` tells the
 * caller to open the conflict dialog (#62).
 */
export function useUpdateEntity(vault: string) {
  const mutations = useRequiredMutations()
  const after = useAfterWrite(vault)
  return useMutation<EntityWriteResult, Error, { id: string; body: Schemas['EntityUpdate'] }>({
    mutationFn: ({ id, body }) => mutations.updateEntity(vault, id, body),
    onSuccess: after,
  })
}

export function useDeleteEntity(vault: string) {
  const mutations = useRequiredMutations()
  const after = useAfterWrite(vault)
  return useMutation({
    mutationFn: ({ id, purge }: { id: string; purge?: boolean }) =>
      mutations.deleteEntity(vault, id, { purge }),
    onSuccess: after,
  })
}

export function useRestoreEntity(vault: string) {
  const mutations = useRequiredMutations()
  const after = useAfterWrite(vault)
  return useMutation({
    mutationFn: (id: string) => mutations.restoreEntity(vault, id),
    onSuccess: after,
  })
}
