import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { momentString, type Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'

type Schemas = components['schemas']

export type Worldline = Domain<Schemas['Worldline']>
export type WorldlineSegment = Domain<Schemas['SegmentOut']>
export type PersonalTimeline = Domain<Schemas['PersonalTimeline']>
export type PersonalItem = Domain<Schemas['PersonalItem']>
export type SegmentIn = Schemas['SegmentIn']
export type TimeTravelIn = Schemas['TimeTravelIn']

/** An entity's worldline (`timeline`: the home dimension's timeline an implicit one is read in). */
export function useWorldline(
  vault: string,
  entity: string,
  { timeline = null, enabled = true }: { timeline?: string | null; enabled?: boolean } = {},
) {
  const source = useDataSource()
  const query = timeline === null ? {} : { timeline }
  return useQuery({
    queryKey: keys.worldline(vault, entity, query),
    queryFn: () => source.worldline(vault, entity, query),
    enabled,
  })
}

/** The segments covering a moment (several: a time traveler there more than once). */
export function usePresence(
  vault: string,
  entity: string,
  at: { dimension: string; timeline: string | null; t: bigint } | null,
) {
  const source = useDataSource()
  const query =
    at === null
      ? null
      : {
          dimension: at.dimension,
          t: momentString(at.t),
          ...(at.timeline === null ? {} : { timeline: at.timeline }),
        }
  return useQuery({
    queryKey: keys.presence(vault, entity, query ?? {}),
    queryFn: () => source.presence(vault, entity, query ?? { dimension: '', t: momentString(0n) }),
    enabled: query !== null,
  })
}

/** What an entity lives through in its own order (participations, existence, jumps). */
export function usePersonalTimeline(
  vault: string,
  entity: string,
  { timeline = null, enabled = true }: { timeline?: string | null; enabled?: boolean } = {},
) {
  const source = useDataSource()
  const query = timeline === null ? {} : { timeline }
  return useQuery({
    queryKey: keys.personalTimeline(vault, entity, query),
    queryFn: () => source.personalTimeline(vault, entity, query),
    enabled,
  })
}

/** Replaces an entity's segments (an empty list: back to the implicit worldline). */
export function useReplaceSegments(vault: string, entity: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (segments: SegmentIn[]) => mutations.replaceSegments(vault, entity, { segments }),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/** The time-travel wizard's request: cut, arrive, maybe a branch and events, in one go. */
export function useTimeTravel(vault: string, entity: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: TimeTravelIn) => mutations.timeTravel(vault, entity, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
