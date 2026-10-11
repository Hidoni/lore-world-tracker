import {
  type BaseUnit,
  type CalendarDefinition,
  type CompiledCalendar,
  compileCalendar,
  formatMoment,
} from '@lore/chronology'

import type { Entity } from '@/data'

/** The virtual calendar every dimension has: raw base units (time-model.md §3). */
export const ABSOLUTE = 'absolute'

/** What the UI needs of a dimension's `ext` (moments are `bigint` after the data layer). */
export interface DimensionTime {
  id: string
  name: string
  baseUnit: BaseUnit
  duration: bigint
  defaultCalendarId: string | null
  primeTimelineId: string | null
  /** The present moment (`null`: none set, or unresolved). */
  present: bigint | null
}

/** A display calendar: a compiled calendar of the dimension, or the Absolute one. */
export interface Lens {
  id: string
  name: string
  /** `null` for the Absolute calendar. */
  calendar: CompiledCalendar | null
}

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
const text = (value: unknown): string | null => (typeof value === 'string' ? value : null)

export function dimensionTime(entity: Entity): DimensionTime | null {
  const ext = record(entity.ext)
  const unit = record(ext.base_unit)
  if (typeof ext.duration !== 'bigint') return null
  return {
    id: entity.id,
    name: entity.name,
    baseUnit: {
      singular: text(unit.singular) ?? 'unit',
      plural: text(unit.plural) ?? 'units',
      abbr: text(unit.abbr) ?? '',
    },
    duration: ext.duration,
    defaultCalendarId: text(ext.default_calendar_id),
    primeTimelineId: text(ext.prime_timeline_id),
    present: typeof ext.present_t === 'bigint' ? ext.present_t : null,
  }
}

const cache = new Map<string, CompiledCalendar | null>()

/**
 * A calendar entity compiled by `@lore/chronology` (`null` when it doesn't compile), cached by
 * calendar id, definition revision and resolved anchors (frontend.md §12), plus the dimension's
 * unit and duration it compiles against.
 */
export function compiledCalendar(
  calendar: Entity,
  dimension: DimensionTime,
): CompiledCalendar | null {
  const ext = record(calendar.ext)
  const anchors = Object.entries(record(ext.resolved_anchors))
    .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  const key = JSON.stringify([
    calendar.id,
    ext.definition_revision ?? null,
    anchors,
    dimension.baseUnit,
    formatMoment(dimension.duration),
  ])
  const cached = cache.get(key)
  if (cached !== undefined) return cached
  let compiled: CompiledCalendar | null = null
  if (ext.definition !== null && typeof ext.definition === 'object') {
    try {
      const result = compileCalendar(ext.definition as CalendarDefinition, {
        calendar_id: calendar.id,
        base_unit: dimension.baseUnit,
        dimension_duration: formatMoment(dimension.duration),
        resolved: Object.fromEntries(anchors),
      })
      compiled = Array.isArray(result) ? null : result
    } catch {
      compiled = null // A definition this engine can't read: shown in no calendar.
    }
  }
  cache.set(key, compiled)
  return compiled
}

/**
 * The display calendars of a dimension: the default first, the others by name, then Absolute.
 * Calendars that don't compile are left out.
 */
export function lenses(dimension: DimensionTime, calendars: readonly Entity[]): Lens[] {
  const compiled = calendars
    .filter((calendar) => calendar.deleted_at === null)
    .flatMap((calendar): Lens[] => {
      const found = compiledCalendar(calendar, dimension)
      return found === null ? [] : [{ id: calendar.id, name: calendar.name, calendar: found }]
    })
    .sort((a, b) =>
      a.id === dimension.defaultCalendarId
        ? -1
        : b.id === dimension.defaultCalendarId
          ? 1
          : a.name.localeCompare(b.name),
    )
  return [...compiled, { id: ABSOLUTE, name: 'Absolute', calendar: null }]
}
