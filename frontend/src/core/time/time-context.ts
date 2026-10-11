import { formatMoment, parseMoment } from '@lore/chronology'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { create } from 'zustand'

import { useDimensionCalendars, useDimensions, useEntity } from '@/data'
import { readStored, writeStored } from '@/lib/storage'

import { ABSOLUTE, dimensionTime, lenses, type DimensionTime, type Lens } from './calendars'

/** The global search params (`app/search.ts`, frontend.md §4). */
interface TimeSearch {
  tl?: string
  at?: string
  cal?: string
}

type Remembered = TimeSearch

const dimensionKey = (vault: string) => `lore.dimension.${vault}`
const rememberedKey = (vault: string, dimension: string) => `lore.time.${vault}.${dimension}`

function readRemembered(vault: string, dimension: string): Remembered {
  try {
    const value = JSON.parse(readStored(rememberedKey(vault, dimension)) ?? '{}') as unknown
    if (value === null || typeof value !== 'object') return {}
    const record = value as Record<string, unknown>
    const pick = (key: keyof Remembered) =>
      typeof record[key] === 'string' ? { [key]: record[key] } : {}
    return { ...pick('tl'), ...pick('at'), ...pick('cal') }
  } catch {
    return {}
  }
}

interface TimeStore {
  /** Bumped when remembered values change, so readers re-render. */
  version: number
  remember: (vault: string, dimension: string, patch: Remembered) => void
  chooseDimension: (vault: string, dimension: string) => void
}

/**
 * The last time context per vault (its dimension) and per vault/dimension (timeline, cursor,
 * display calendar), kept in `localStorage` (frontend.md §4).
 */
export const useTimeStore = create<TimeStore>()((set) => ({
  version: 0,
  remember: (vault, dimension, patch) => {
    const next = { ...readRemembered(vault, dimension), ...patch }
    writeStored(rememberedKey(vault, dimension), JSON.stringify(next))
    set((state) => ({ version: state.version + 1 }))
  },
  chooseDimension: (vault, dimension) => {
    writeStored(dimensionKey(vault), dimension)
    set((state) => ({ version: state.version + 1 }))
  },
}))

/** The time cursor (time-model.md §10.6): the present, all time, or a moment. */
export type Cursor = 'present' | 'all' | bigint

function parseCursor(value: string | undefined): Cursor | undefined {
  if (value === 'present' || value === 'all') return value
  if (value === undefined) return undefined
  try {
    return parseMoment(value)
  } catch {
    return undefined
  }
}

/** A dimension's time settings and display calendars (`null` while loading or unknown). */
export function useDimensionLenses(
  vault: string,
  dimensionId: string | null,
): { dimension: DimensionTime | null; lenses: Lens[] } {
  const entity = useEntity(vault, dimensionId ?? '', {}, { enabled: dimensionId !== null })
  const dimension = entity.data?.id === dimensionId ? dimensionTime(entity.data) : null
  const { calendars } = useDimensionCalendars(vault, dimensionId)
  return { dimension, lenses: dimension === null ? [] : lenses(dimension, calendars) }
}

/** The display calendar: the wanted one if the dimension has it, else its default, else the first. */
function pickLens(all: readonly Lens[], dimension: DimensionTime | null, wanted?: string) {
  const calendarId = wanted ?? dimension?.defaultCalendarId ?? ABSOLUTE
  return (
    all.find((candidate) => candidate.id === calendarId) ??
    all.find((candidate) => candidate.id === dimension?.defaultCalendarId) ??
    all[0] ??
    null
  )
}

/**
 * The display calendar of a dimension outside the current context (the last used one, else its
 * default).
 */
export function useDisplayLens(vault: string, dimensionId: string | null) {
  useTimeStore((state) => state.version)
  const found = useDimensionLenses(vault, dimensionId)
  const search: TimeSearch = useSearch({ strict: false })
  const current = useCurrentDimension(vault)
  const wanted =
    dimensionId === null
      ? undefined
      : dimensionId === current
        ? (search.cal ?? readRemembered(vault, dimensionId).cal)
        : readRemembered(vault, dimensionId).cal
  return { ...found, lens: pickLens(found.lenses, found.dimension, wanted) }
}

/** The current dimension: the route's, else the last chosen one, else the first. */
function useCurrentDimension(vault: string): string | null {
  const params = useParams({ strict: false })
  const dimensions = useDimensions(vault)
  const known = dimensions.data?.items ?? []
  const chosen = readStored(dimensionKey(vault))
  return (
    params.dimension ??
    (chosen !== null && (dimensions.isPending || known.some((item) => item.id === chosen))
      ? chosen
      : (known[0]?.id ?? null))
  )
}

export interface TimeContext {
  dimensionId: string | null
  dimension: DimensionTime | null
  /** The dimension's display calendars (compiled ones, then Absolute). */
  lenses: Lens[]
  /** The display calendar. */
  lens: Lens | null
  timelineId: string | null
  cursor: Cursor
  /** The cursor's moment (`null`: all time, or no present set). */
  moment: bigint | null
  setDimension: (id: string) => void
  setCalendar: (id: string) => void
  setTimeline: (id: string) => void
  setCursor: (cursor: Cursor) => void
}

/**
 * The global time context of a vault (time-model.md §10.6): the dimension (the route's, else the
 * last chosen, else the first), and its timeline, cursor and display calendar from the URL (`tl`,
 * `at`, `cal`), else the last used ones, else the dimension's defaults.
 */
export function useTimeContext(vault: string): TimeContext {
  useTimeStore((state) => state.version)
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const search: TimeSearch = useSearch({ strict: false })
  const dimensionId = useCurrentDimension(vault)
  const { dimension, lenses: all } = useDimensionLenses(vault, dimensionId)
  const remembered = dimensionId === null ? {} : readRemembered(vault, dimensionId)
  const lens = pickLens(all, dimension, search.cal ?? remembered.cal)
  const cursor = parseCursor(search.at) ?? parseCursor(remembered.at) ?? 'present'
  const moment =
    cursor === 'all' ? null : cursor === 'present' ? (dimension?.present ?? null) : cursor

  const update = (patch: TimeSearch): void => {
    if (dimensionId !== null) useTimeStore.getState().remember(vault, dimensionId, patch)
    void navigate({
      to: '.',
      search: (previous: Record<string, unknown>) => ({ ...previous, ...patch }),
      replace: true,
    })
  }

  return {
    dimensionId,
    dimension,
    lenses: all,
    lens,
    timelineId: search.tl ?? remembered.tl ?? dimension?.primeTimelineId ?? null,
    cursor,
    moment,
    setDimension: (id) => {
      useTimeStore.getState().chooseDimension(vault, id)
      const cleared = { tl: undefined, at: undefined, cal: undefined }
      if (params.dimension !== undefined) {
        void navigate({
          to: '/v/$vault/d/$dimension',
          params: { vault, dimension: id },
        })
      } else {
        void navigate({
          to: '.',
          search: (previous: Record<string, unknown>) => ({ ...previous, ...cleared }),
          replace: true,
        })
      }
    },
    setCalendar: (id) => {
      update({ cal: id })
    },
    setTimeline: (id) => {
      update({ tl: id })
    },
    setCursor: (next) => {
      update({ at: typeof next === 'bigint' ? formatMoment(next) : next })
    },
  }
}
