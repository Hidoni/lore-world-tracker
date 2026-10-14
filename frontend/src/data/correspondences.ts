import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'

type Schemas = components['schemas']

/** A correspondence between two dimensions with its resolved sync points (`a_t`/`b_t` bigint). */
export type CorrespondenceOut = Domain<Schemas['CorrespondenceOut']>
export type SyncPointOut = Domain<Schemas['SyncPointOut']>
export type CorrespondenceCreate = Schemas['CorrespondenceCreate']
export type CorrespondenceUpdate = Schemas['CorrespondenceUpdate']
export type MapOut = Domain<Schemas['MapOut']>

/**
 * The live correspondences the request sees (`dimension`: of that dimension, either side; `null`:
 * all of them), by name. `enabled: false` while the correspondences module is off.
 */
export function useCorrespondences(
  vault: string,
  dimension: string | null = null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.correspondences(vault, dimension),
    queryFn: () => source.correspondences(vault, dimension === null ? undefined : { dimension }),
    enabled,
  })
}

export function useCreateCorrespondence(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CorrespondenceCreate) => mutations.createCorrespondence(vault, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateCorrespondence(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CorrespondenceUpdate }) =>
      mutations.updateCorrespondence(vault, id, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeleteCorrespondence(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.deleteCorrespondence(vault, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
