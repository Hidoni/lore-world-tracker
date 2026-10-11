import {
  BASE,
  type DisplayPoint,
  diff,
  formatAbsolute,
  formatDate,
  formatInteger,
  formatSpan,
  unitBounds,
} from '@lore/chronology'

import type { DimensionTime, Lens } from './calendars'

/** A moment to show: `t` at a precision (a level of some calendar of the dimension, or `base`). */
export interface Moment {
  t: bigint
  precision: string
  approximate?: boolean
  /** The uncertainty extent `[lo, hi)` when known (API resolutions carry it). */
  extent?: { lo: bigint; hi: bigint }
}

/** How wide the moment's uncertainty is: its extent, or its precision's unit in a calendar that
 * has that level (`null`: exact). */
function width(moment: Moment, all: readonly Lens[]): bigint | null {
  if (moment.extent !== undefined) return moment.extent.hi - moment.extent.lo
  if (moment.precision === BASE) return null
  for (const lens of all) {
    if (lens.calendar !== null && lens.calendar.levelIndex(moment.precision) >= 0) {
      const bounds = unitBounds(lens.calendar, moment.t, moment.precision)
      return bounds.end - bounds.start
    }
  }
  return null
}

/**
 * The level to show a moment at in a calendar: its precision if the calendar has that level, else
 * the coarsest level whose unit (at `t`) fits in its extent, the finest if none does (the
 * backend's `display_level`, `lore.core.time.batch`).
 */
export function displayLevel(lens: Lens, moment: Moment, all: readonly Lens[]): string {
  const calendar = lens.calendar
  if (calendar === null) return BASE
  if (moment.precision === BASE || calendar.levelIndex(moment.precision) >= 0) {
    return moment.precision
  }
  const span = width(moment, all)
  if (span === null) return BASE
  let chosen = calendar.levels[0] ?? BASE
  for (const level of calendar.levels) {
    const bounds = unitBounds(calendar, moment.t, level)
    if (bounds.end - bounds.start > span) break
    chosen = level
  }
  return chosen
}

/** A moment in a display calendar (`null` when the calendar can't show it). */
export function formatIn(
  lens: Lens,
  moment: Moment,
  dimension: DimensionTime,
  all: readonly Lens[],
): string | null {
  const approximate = moment.approximate === true
  try {
    if (lens.calendar === null)
      return formatAbsolute(moment.t, dimension.baseUnit, null, { approximate })
    return formatDate(lens.calendar, moment.t, displayLevel(lens, moment, all), { approximate })
  } catch {
    return null
  }
}

/** A span in a display calendar: shared coarse parts collapse, an open end is `?`. */
export function formatSpanIn(
  lens: Lens,
  start: Moment | null,
  end: Moment | null,
  dimension: DimensionTime,
  all: readonly Lens[],
): string | null {
  try {
    const calendar = lens.calendar
    if (calendar === null) {
      const one = (moment: Moment | null) =>
        moment === null ? '?' : (formatIn(lens, moment, dimension, all) ?? '?')
      return start !== null && end !== null && start.t === end.t
        ? one(start)
        : `${one(start)} – ${one(end)}`
    }
    const point = (moment: Moment | null): DisplayPoint | null =>
      moment === null
        ? null
        : {
            t: moment.t,
            precision: displayLevel(lens, moment, all),
            approximate: moment.approximate === true,
          }
    return formatSpan(calendar, point(start), point(end))
  } catch {
    return null
  }
}

/**
 * "N years before present" in the calendar's top level (`null` without a present, a calendar,
 * or in the present's own year).
 */
export function relativeToPresent(lens: Lens, t: bigint, present: bigint | null): string | null {
  const calendar = lens.calendar
  if (calendar === null || present === null) return null
  const top = calendar.levels[calendar.levels.length - 1]
  if (top === undefined) return null
  try {
    const found = diff(calendar, t, present, top, top)
    const count = found.amounts.get(top) ?? 0n
    if (count === 0n) return null
    const level = calendar.definition.levels.find((candidate) => candidate.id === top)
    const unit = count === 1n ? (level?.label ?? top) : (level?.plural ?? top)
    const amount = formatInteger(count)
    return `${amount} ${unit.toLowerCase()} ${found.sign === 1 ? 'before' : 'after'} present`
  } catch {
    return null
  }
}
