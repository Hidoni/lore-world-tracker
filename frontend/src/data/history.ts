import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

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

/** Undo a changeset. */
export function useRevertChange(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.revertChange(vault, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
