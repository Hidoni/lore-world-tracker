import { fromFields, type TimePoint } from '@lore/chronology'

import type { Lens } from './calendars'
import type { Moment } from './format'

/**
 * The moment a time point's anchor denotes when the browser can tell on its own: an absolute
 * moment, or a calendar date in one of `lenses` (era and calendar rules included). `null` for
 * other anchors (relative ones resolve on the server) and dates that don't resolve.
 */
export function pointMoment(point: TimePoint, lenses: readonly Lens[]): bigint | null {
  const anchor = point.anchor
  if (anchor.kind === 'absolute') return BigInt(anchor.t)
  if (anchor.kind !== 'calendar') return null
  const calendar = lenses.find((lens) => lens.id === anchor.calendar_id)?.calendar ?? null
  if (calendar === null) return null
  try {
    return fromFields(calendar, anchor.fields, point.precision, {
      era: anchor.era ?? null,
      regime: anchor.regime ?? null,
    })
  } catch {
    return null
  }
}

/**
 * A time point's moment `t` to show, with its uncertainty range (time-model.md §5.4b) when the
 * browser can resolve both ends (`pointMoment`; relative ends resolve on the server, and the
 * moment then shows as its best estimate). `null` without `t`.
 */
export function momentOf(
  t: bigint | null,
  point: TimePoint | null | undefined,
  lenses: readonly Lens[],
): Moment | null {
  if (t === null) return null
  const moment: Moment = {
    t,
    precision: point?.precision ?? 'base',
    approximate: point?.approximate === true,
  }
  const range = point?.range
  if (range == null) return moment
  const end = (end: TimePoint): Moment | null => {
    const at = pointMoment(end, lenses)
    return at === null
      ? null
      : { t: at, precision: end.precision, approximate: end.approximate === true }
  }
  const earliest = end(range.earliest)
  const latest = end(range.latest)
  return earliest === null || latest === null ? moment : { ...moment, range: { earliest, latest } }
}
