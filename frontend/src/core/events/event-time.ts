import type { EndSpec, RecurrenceRule, TimePoint } from '@lore/chronology'

import type { Entity } from '@/data'

/** What the UI reads of an event's `ext` (time-model.md §9.1; moments are `bigint`). */
export interface EventTime {
  timelineId: string | null
  start: TimePoint | null
  end: EndSpec | null
  startT: bigint | null
  endT: bigint | null
  status: string | null
  importance: number
  category: string | null
  recurring: boolean
  /** The series' rule (`null`: not recurring, or hidden from the request). */
  recurrence: RecurrenceRule | null
  /** Materialized occurrences: their series and key. */
  seriesId: string | null
  occurrenceKey: string | null
  occurrenceState: string | null
  occurrenceNumber: number | null
}

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
const text = (value: unknown): string | null => (typeof value === 'string' ? value : null)
const moment = (value: unknown): bigint | null => (typeof value === 'bigint' ? value : null)

export function eventTime(entity: Pick<Entity, 'ext'>): EventTime {
  const ext = record(entity.ext)
  const start = record(ext.start)
  const end = record(ext.end)
  return {
    timelineId: text(ext.timeline_id),
    start: 'anchor' in start ? (start as unknown as TimePoint) : null,
    end: typeof end.kind === 'string' ? (end as unknown as EndSpec) : null,
    startT: moment(ext.start_t),
    endT: moment(ext.end_t),
    status: text(ext.time_status),
    importance: typeof ext.importance === 'number' ? ext.importance : 3,
    category: text(ext.category),
    recurring: ext.recurrence !== null && ext.recurrence !== undefined,
    recurrence:
      ext.recurrence !== null && typeof ext.recurrence === 'object'
        ? (ext.recurrence as RecurrenceRule)
        : null,
    seriesId: text(ext.series_id),
    occurrenceKey: text(ext.occurrence_key),
    occurrenceState: text(ext.occurrence_state),
    occurrenceNumber: typeof ext.occurrence_number === 'number' ? ext.occurrence_number : null,
  }
}

/** The importance scale (R-EVT-5). */
export const IMPORTANCE: Record<number, string> = {
  1: 'Minor',
  2: 'Low',
  3: 'Normal',
  4: 'High',
  5: 'Major',
}
