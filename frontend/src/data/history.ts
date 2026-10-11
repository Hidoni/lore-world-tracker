import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useDataSource, useRequiredMutations } from './context'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Query } from './source'

export function useChanges(vault: string, query: Query<'changes_list'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.changes(vault, query),
    queryFn: () => source.changes(vault, query),
  })
}

export function useHistory(vault: string, id: string, query: Query<'entities_history'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.history(vault, id, query),
    queryFn: () => source.history(vault, id, query),
  })
}

/** The change feed, page by page; `origin` keeps changesets of those origins. */
export function useChangesPages(vault: string, query: Query<'changes_list'> = {}) {
  const source = useDataSource()
  return useInfiniteQuery({
    queryKey: [...keys.changes(vault, query), 'paged'],
    queryFn: ({ pageParam }) =>
      source.changes(vault, { ...query, ...(pageParam === null ? {} : { cursor: pageParam }) }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

/** An entity's history, page by page. */
export function useHistoryPages(vault: string, id: string) {
  const source = useDataSource()
  return useInfiniteQuery({
    queryKey: [...keys.history(vault, id), 'paged'],
    queryFn: ({ pageParam }) =>
      source.history(vault, id, pageParam === null ? {} : { cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

/** A changeset with its row changes (`enabled: false` until it's opened). */
export function useChangeset(vault: string, id: string, options: { enabled?: boolean } = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.change(vault, id),
    queryFn: () => source.change(vault, id),
    enabled: options.enabled ?? true,
  })
}

/**
 * Undo a changeset. A `409 revert_conflict` isn't toasted: the caller shows its rows and
 * problems next to the change.
 */
export function useRevertChange(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.revertChange(vault, id),
    meta: { toast: false },
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
