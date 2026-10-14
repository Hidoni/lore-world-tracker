import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Entity, EntityWriteResult, Query } from './source'

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

/** An entity's state at the time cursor (`GET …/state`); off without a moment. */
export function useEntityState(
  vault: string,
  id: string,
  query: Query<'entities_state'> | undefined,
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entityState(vault, id, query ?? {}),
    queryFn: () => source.entityState(vault, id, query ?? { at: 'present' }),
    enabled: query !== undefined,
  })
}

/** An entity's facts (`GET …/facts`), by field, then start. */
export function useFacts(
  vault: string,
  id: string,
  query: Query<'facts_list_facts'> = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.facts(vault, id, query),
    queryFn: () => source.facts(vault, id, query),
    enabled: options.enabled ?? true,
  })
}

/** An event's "changes caused" (`GET /facts?source_event=`). */
export function useCausedFacts(vault: string, event: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.causedFacts(vault, event),
    queryFn: () => source.causedFacts(vault, event),
  })
}

export function useCreateFact(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ entity, body }: { entity: string; body: Schemas['FactCreate'] }) =>
      mutations.createFact(vault, entity, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateFact(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['FactUpdate'] }) =>
      mutations.updateFact(vault, id, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeleteFact(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.deleteFact(vault, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
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

/** Tags in use on the entities the request sees, by name, with counts (`GET /tags`). */
export function useTags(vault: string, query: Query<'tags_list'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.tags(vault, query),
    queryFn: () => source.tags(vault, query),
  })
}

/** Distinct values of a text field among a kind's entities, most used first (autocomplete). */
export function useFieldValues(
  vault: string,
  query: Query<'entities_field_values'>,
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.fieldValues(vault, query),
    queryFn: () => source.fieldValues(vault, query),
    enabled: options.enabled ?? true,
    staleTime: 30_000,
  })
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
      /** The change, or a function computing it from the latest entity (throwing refuses). */
      change:
        | Omit<Schemas['EntityUpdate'], 'revision'>
        | ((entity: Entity) => Omit<Schemas['EntityUpdate'], 'revision'>)
    }) => {
      const entity = await source.entity(vault, id)
      const body = typeof change === 'function' ? change(entity) : change
      return mutations.updateEntity(vault, id, { ...body, revision: entity.revision })
    },
    onSuccess: after,
  })
}
