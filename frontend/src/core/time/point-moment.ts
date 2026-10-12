import { fromFields, type TimePoint } from '@lore/chronology'

import type { Lens } from './calendars'

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
