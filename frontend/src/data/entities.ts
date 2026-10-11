import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

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

/** Every page of a cursor-paged list, fetched as needed (`fetchNextPage`): long lists, trees. */
function usePaged<P extends { next_cursor: string | null }>(
  queryKey: readonly unknown[],
  fetchPage: (cursor: string | null) => Promise<P>,
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: [...queryKey, 'paged'],
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  })
}

/** All entities matching `query`, page by page (entity lists). */
export function useEntityList(vault: string, query: Query<'entities_list'> = {}) {
  const source = useDataSource()
  return usePaged(keys.entities(vault, query), (cursor) =>
    source.entities(vault, { ...query, ...(cursor === null ? {} : { cursor }) }),
  )
}

/** One level of the navigation tree (roots, or `parent`'s children), page by page. */
export function useTreeLevel(
  vault: string,
  query: Query<'tree_get'> = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return usePaged(
    keys.tree(vault, query),
    (cursor) => source.tree(vault, { ...query, ...(cursor === null ? {} : { cursor }) }),
    options.enabled ?? true,
  )
}

/** The trash, page by page. */
export function useTrashList(vault: string, query: Query<'trash_list'> = {}) {
  const source = useDataSource()
  return usePaged(keys.trash(vault, query), (cursor) =>
    source.trash(vault, { ...query, ...(cursor === null ? {} : { cursor }) }),
  )
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

/**
 * Changes an entity at its current revision, read first: for places that don't hold the entity
 * (tree nodes, list rows: rename, reparent). Last write wins, like a fresh page. `toast: false`
 * when the caller shows the error itself.
 */
export function useUpdateLatest(vault: string, options: { toast?: boolean } = {}) {
  const mutations = useRequiredMutations()
  const source = useDataSource()
  const after = useAfterWrite(vault)
  return useMutation({
    meta: { toast: options.toast ?? true },
    mutationFn: async ({
      id,
      change,
    }: {
      id: string
      change: Omit<Schemas['EntityUpdate'], 'revision'>
    }) => {
      const entity = await source.entity(vault, id)
      return mutations.updateEntity(vault, id, { ...change, revision: entity.revision })
    },
    onSuccess: after,
  })
}
