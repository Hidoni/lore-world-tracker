import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useMutations, useRequiredMutations } from './context'
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
