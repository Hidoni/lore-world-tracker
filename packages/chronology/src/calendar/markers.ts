/**
 * Annual markers: named parts of every year, e.g. seasons (chronology-engine.md §3.12, §8). The
 * Python twin is backend/src/lore/chronology/calendar/markers.py.
 *
 * A marker's range in year `Y` is `[a, b)`: `a` is the start of its `from` fields in `Y`, `b` the
 * start of its `to` fields in `Y`, or in `Y + 1` when that is not after `a` (the range wraps into
 * the next year). Both sides are resolved with `fromFields(…, overflow: 'constrain')`; a year
 * where either can't be resolved has no range. Markers never affect the date structure.
 */
import type { Marker } from '../schema.gen'
import { activeRegime, type CompiledCalendar, DateError, defined } from './compiled'
import { fromFields } from './convert'

/** The marker with `markerId`; `unknown_marker` if the calendar has none. */
export function markerOf(calendar: CompiledCalendar, markerId: string): Marker {
  const found = (calendar.definition.markers ?? []).find((item) => item.id === markerId)
  if (found === undefined) throw new DateError('unknown_marker', `no marker ${markerId}`)
  return found
}

function side(
  calendar: CompiledCalendar,
  fields: Readonly<Record<string, string | undefined>>,
  year: bigint,
  regime: string | null,
): bigint | null {
  const levels = calendar.levels
  const precision = defined(
    Object.keys(fields).sort((a, b) => levels.indexOf(a) - levels.indexOf(b))[0],
  )
  try {
    return fromFields(
      calendar,
      { ...fields, [defined(levels.at(-1))]: String(year) },
      precision,
      { overflow: 'constrain', ...(regime === null ? {} : { regime }) },
    )
  } catch (error) {
    if (error instanceof DateError) return null
    throw error
  }
}

/** `[a, b)` of `item` in `year`, or `null` when that year has none. With `regime`, the year is
 * reckoned in that regime (recurrence rules: the series start's, extended proleptically); else
 * `fromFields` picks the regime in force. */
export function rangeOf(
  calendar: CompiledCalendar,
  item: Marker,
  year: bigint,
  regime: string | null = null,
): readonly [bigint, bigint] | null {
  const start = side(calendar, item.from, year, regime)
  if (start === null) return null
  let end = side(calendar, item.to, year, regime)
  if (end === null || end <= start) end = side(calendar, item.to, year + 1n, regime)
  if (end === null || end <= start) return null
  return [start, end]
}

/** §8 `markerRange`: the marker's range in `year` (`null`: none that year). */
export function markerRange(
  calendar: CompiledCalendar,
  markerId: string,
  year: bigint,
): { start: bigint; end: bigint } | null {
  const found = rangeOf(calendar, markerOf(calendar, markerId), year)
  return found === null ? null : { start: found[0], end: found[1] }
}

/** §8 `markersAt`: the ids of the markers whose range contains `t`, in definition order (the range
 * of `t`'s year, or the previous year's running into it), reckoned in the regime in force at `t`. */
export function markersAt(calendar: CompiledCalendar, t: bigint): string[] {
  const regime = activeRegime(calendar, t)
  const year = regime.yearOf(t)
  return (calendar.definition.markers ?? [])
    .filter((item) =>
      [year, year - 1n].some((candidate) => {
        const bounds = rangeOf(calendar, item, candidate, regime.id)
        return bounds !== null && bounds[0] <= t && t < bounds[1]
      }),
    )
    .map((item) => item.id)
}
