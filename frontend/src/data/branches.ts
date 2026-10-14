import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'

type Schemas = components['schemas']

/** A timeline of a dimension's tree (the prime and its branches). */
export type TimelineNode = Domain<Schemas['TimelineNode']>
export type BranchDiff = Domain<Schemas['BranchDiff']>
export type DiffRecord = Domain<Schemas['DiffRecord']>
export type OverrideRecordType = 'event' | 'fact' | 'link'
export type BranchCreate = Schemas['BranchCreate']

/**
 * What a branch created, overrode (before/after) and inherits across its branch point (`null`:
 * nothing to ask, e.g. a prime timeline).
 */
export function useBranchDiff(vault: string, timeline: string | null) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.branchDiff(vault, timeline ?? ''),
    queryFn: () => source.branchDiff(vault, timeline ?? '', { limit: 2000 }),
    enabled: timeline !== null,
  })
}

/** The diffs of several branches (compare mode), by timeline id, once loaded. */
export function useBranchDiffs(vault: string, timelines: readonly string[]) {
  const source = useDataSource()
  return useQueries({
    queries: timelines.map((timeline) => ({
      queryKey: keys.branchDiff(vault, timeline),
      queryFn: () => source.branchDiff(vault, timeline, { limit: 2000 }),
    })),
    combine: (results) => {
      const found = new Map<string, BranchDiff>()
      results.forEach((result, index) => {
        const timeline = timelines[index]
        if (result.data !== undefined && timeline !== undefined) found.set(timeline, result.data)
      })
      return found
    },
  })
}

/** Creates a branch of a timeline at a branch point (the result is the new timeline entity). */
export function useCreateBranch(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: BranchCreate) => mutations.createBranch(vault, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export interface OverrideInput {
  recordType: OverrideRecordType
  /** An event's entity id, or the root fact's or link's id. */
  rootId: string
  timelineId: string
  changes: Record<string, unknown>
}

/** Overrides (or overrides again) an inherited record in a branch (time-model.md §4.4). */
export function useSaveOverride(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: OverrideInput) =>
      mutations.saveOverride(vault, {
        record_type: input.recordType,
        root_id: input.rootId,
        timeline_id: input.timelineId,
        changes: input.changes,
      }),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/** Reverts an override: the branch sees the inherited record again. */
export function useRevertOverride(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ recordType, id }: { recordType: OverrideRecordType; id: string }) =>
      mutations.revertOverride(vault, recordType, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
