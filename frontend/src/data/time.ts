import {
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useMutations, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Entity } from './source'

const DIMENSIONS = { kind: ['dimension'], limit: 100 }

/** The vault's dimensions (summaries, by name). */
export function useDimensions(vault: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.entities(vault, DIMENSIONS),
    queryFn: () => source.entities(vault, DIMENSIONS),
  })
}

/**
 * The calendars of a dimension as full entities (`ext`: definition, revision, resolved anchors),
 * sharing the entity cache with `useEntity`. `null` skips the fetch.
 */
export function useDimensionCalendars(
  vault: string,
  dimension: string | null,
): { calendars: Entity[]; isPending: boolean } {
  const source = useDataSource()
  const query = { kind: ['calendar'], dimension: dimension ?? '', limit: 100 }
  const list = useQuery({
    queryKey: keys.entities(vault, query),
    queryFn: () => source.entities(vault, query),
    enabled: dimension !== null,
  })
  const ids = (list.data?.items ?? []).map((item) => item.id)
  const full = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.entity(vault, id, {}),
      queryFn: () => source.entity(vault, id, {}),
    })),
  })
  const calendars = full.flatMap((result) => (result.data === undefined ? [] : [result.data]))
  return {
    calendars,
    isPending: dimension !== null && (list.isPending || full.some((result) => result.isPending)),
  }
}

/** A dimension's timelines (the prime timeline and its branches, as a tree). */
export function useTimelines(vault: string, dimension: string | null) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.timelines(vault, dimension ?? ''),
    queryFn: () => source.timelines(vault, dimension ?? ''),
    enabled: dimension !== null,
  })
}

/**
 * One level of a timeline's event outline (`GET /timelines/{id}/event-tree`): the roots, or the
 * sub-events of `parent`, ordered by start, page by page.
 */
export function useEventTreeLevel(
  vault: string,
  timeline: string | null,
  parent: string | null,
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  const query = parent === null ? {} : { parent }
  return useInfiniteQuery({
    queryKey: [...keys.eventTree(vault, timeline ?? '', query), 'paged'],
    queryFn: ({ pageParam }) =>
      source.eventTree(vault, timeline ?? '', {
        ...query,
        ...(pageParam === null ? {} : { cursor: pageParam }),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: timeline !== null && (options.enabled ?? true),
  })
}

/**
 * Time points (and ends) resolved by the server (`POST /time/resolve`): previews for relative
 * anchors and end checks. Authors only (it's a `Mutations` call); `null` skips the request.
 */
export function useTimeResolution(vault: string, body: components['schemas']['ResolveIn'] | null) {
  const mutations = useMutations()
  return useQuery({
    queryKey: [vault, 'resolve', JSON.stringify(body)],
    queryFn: () => {
      if (mutations === null || body === null) throw new Error('Nothing to resolve.')
      return mutations.resolveTime(vault, body)
    },
    enabled: mutations !== null && body !== null,
    meta: { toast: false },
    placeholderData: (previous) => previous,
  })
}

/** The preset calendars (`GET /calendars/presets`), for the dimension wizard. */
export function useCalendarPresets(vault: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.calendarPresets(vault),
    queryFn: () => source.calendarPresets(vault),
    staleTime: Infinity,
  })
}

/**
 * A calendar compiled by the server without saving it (`POST /calendars/preview`): sample dates,
 * or the definition's problems. Authors only; `null` skips the request.
 */
export function useCalendarPreview(
  vault: string,
  body: components['schemas']['CalendarPreviewIn'] | null,
) {
  const mutations = useMutations()
  return useQuery({
    queryKey: [vault, 'calendarPreview', JSON.stringify(body)],
    queryFn: () => {
      if (mutations === null || body === null) throw new Error('Nothing to preview.')
      return mutations.previewCalendar(vault, body)
    },
    enabled: mutations !== null && body !== null,
    meta: { toast: false },
    retry: false,
    placeholderData: (previous) => previous,
  })
}

/** Creates a dimension with its prime timeline and first calendar (the wizard). */
export function useCreateDimension(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['DimensionWizardIn']) =>
      mutations.createDimension(vault, body),
    meta: { toast: false },
    onSuccess: () =>
      Promise.all(
        ['vault', 'entities', 'tree', 'children', 'changes', 'registry'].map((area) =>
          client.invalidateQueries({ queryKey: [vault, area] }),
        ),
      ),
  })
}

type Schemas = components['schemas']

/** A calendar edit's impact preview, moments as `bigint`. */
export type CalendarProposal = Domain<Schemas['CalendarProposalOut']>

/** A recurrence rule change's reconciliation preview, moments as `bigint`. */
export type RecurrenceProposal = Domain<Schemas['RecurrenceProposalOut']>

/** A row of the event outline, moments as `bigint`. */
export type EventTreeNode = Domain<Schemas['EventTreeNode']>

/**
 * Previews a calendar edit (`POST /calendars/{id}/proposals`, time-model.md §7.4): what moves or
 * breaks, with the strategies each item offers. Errors are the caller's to show.
 */
export function useProposeCalendarChange(vault: string) {
  const mutations = useRequiredMutations()
  return useMutation({
    mutationFn: ({ calendar, definition }: { calendar: string; definition: object }) =>
      mutations.proposeCalendarChange(vault, calendar, {
        definition: definition as Schemas['CalendarProposalIn']['definition'],
      }),
    meta: { toast: false },
  })
}

/** Applies a proposal with the chosen strategies; the change is one undoable changeset. */
export function useApplyCalendarProposal(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      calendar,
      proposal,
      body,
    }: {
      calendar: string
      proposal: string
      body: Schemas['CalendarApplyIn']
    }) => mutations.applyCalendarProposal(vault, calendar, proposal, body),
    meta: { toast: false },
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/**
 * Previews a change of a series' rule, start or end (`POST /events/{id}/recurrence/proposals`,
 * recurrence.md §8): every materialized occurrence with its status and strategies.
 */
export function useProposeRecurrenceChange(vault: string) {
  const mutations = useRequiredMutations()
  return useMutation({
    mutationFn: ({ event, body }: { event: string; body: Schemas['RecurrenceProposalIn'] }) =>
      mutations.proposeRecurrenceChange(vault, event, body),
    meta: { toast: false },
  })
}

/** Applies a recurrence proposal with a strategy per occurrence; one undoable changeset. */
export function useApplyRecurrenceProposal(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      event,
      proposal,
      body,
    }: {
      event: string
      proposal: string
      body: Schemas['RecurrenceApplyIn']
    }) => mutations.applyRecurrenceProposal(vault, event, proposal, body),
    meta: { toast: false },
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/** Materializes an occurrence (get-or-create, recurrence.md §7): the occurrence's event. */
export function useMaterializeOccurrence(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ event, key }: { event: string; key: string }) =>
      mutations.materializeOccurrence(vault, event, key),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/**
 * Deletes a materialized occurrence: it reverts to the computed one. `409
 * occurrence_has_sub_events` asks for `trashSubEvents`.
 */
export function useDeleteOccurrence(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      event,
      key,
      trashSubEvents,
    }: {
      event: string
      key: string
      trashSubEvents?: boolean
    }) => mutations.deleteOccurrence(vault, event, key, { trashSubEvents }),
    meta: { toast: false },
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/** A series' occurrences overlapping `[from, to)` (computed and materialized, merged). */
export function useOccurrences(
  vault: string,
  event: string,
  window: { from: bigint; to: bigint } | null,
  options: { includeCancelled?: boolean; limit?: number } = {},
) {
  const source = useDataSource()
  const query =
    window === null
      ? null
      : {
          from: window.from.toString(),
          to: window.to.toString(),
          limit: options.limit ?? 50,
          ...(options.includeCancelled ? { include_cancelled: true } : {}),
        }
  return useQuery({
    queryKey: keys.occurrences(vault, event, query ?? {}),
    queryFn: () => {
      if (query === null) throw new Error('No window.')
      return source.occurrences(vault, event, query)
    },
    enabled: query !== null,
    placeholderData: (previous) => previous,
  })
}
