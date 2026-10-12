import {
  BASE,
  eraOf,
  fromFields,
  toFields,
  unitBounds,
  type EndSpec,
  type TimePoint,
} from '@lore/chronology'

import type { Lens } from '@/core/time'

/** What a drag changes: the whole event, its start edge or its end edge. */
export type DragMode = 'move' | 'start' | 'end'

export type DragResult =
  { kind: 'ok'; start: TimePoint; end: EndSpec } | { kind: 'locked'; reason: string }

/** The moment a point's anchor denotes (absolute and calendar anchors), else `null`. */
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
 * `point` moved to moment `t`, in the same kind of anchor: an absolute moment, or the typed date
 * of `t`'s unit at the point's precision in the same calendar (slot ids for named units, era
 * years when the point was typed with an era). `null` when `t` can't be typed that way.
 */
export function movePoint(point: TimePoint, t: bigint, lenses: readonly Lens[]): TimePoint | null {
  const anchor = point.anchor
  if (anchor.kind === 'absolute') return { ...point, anchor: { kind: 'absolute', t: t.toString() } }
  if (anchor.kind !== 'calendar') return null
  const calendar = lenses.find((lens) => lens.id === anchor.calendar_id)?.calendar ?? null
  if (calendar === null || point.precision === BASE) return null
  const index = calendar.levelIndex(point.precision)
  if (index < 0) return null
  try {
    const found = toFields(calendar, t)
    const top = calendar.levels.at(-1)
    const fields: Record<string, string> = {}
    for (const level of calendar.levels.slice(index)) {
      const value = found.levels.get(level)
      if (value === undefined) return null
      fields[level] = value.slotId ?? (value.n === null ? '' : value.n.toString())
    }
    let era: string | null = null
    if (anchor.era != null && top !== undefined) {
      const value = eraOf(calendar, t)
      if (value !== null) {
        era = value.id
        fields[top] = value.year.toString()
      }
    }
    const moved: TimePoint = {
      ...point,
      anchor: {
        kind: 'calendar',
        calendar_id: anchor.calendar_id,
        fields,
        ...(era === null ? {} : { era }),
      },
    }
    // The typed date must denote the unit holding `t` (an ambiguous reform date doesn't).
    const back = pointMoment(moved, lenses)
    return back !== null && back === unitBounds(calendar, t, point.precision).start ? moved : null
  } catch {
    return null
  }
}

const RELATIVE = 'Its time is relative to another record: edit the offset instead.'

/**
 * The event's new start and end after a drag (frontend.md §9.4): `delta` base units added to the
 * start (`move`, `start`) and to the end (`move`, `end`), typed in the anchors' own calendars.
 * A start edge keeps the end where it was (a base duration shrinks or grows); an end edge moves
 * an end date or changes a base duration. Relative anchors, calendar durations and unknown ends
 * are locked: their editor is the event dialog.
 */
export function dragTime(
  start: TimePoint,
  end: EndSpec,
  mode: DragMode,
  delta: bigint,
  lenses: readonly Lens[],
): DragResult {
  const shift = (point: TimePoint): TimePoint | null => {
    const t = pointMoment(point, lenses)
    return t === null ? null : movePoint(point, t + delta, lenses)
  }
  const locked = (reason: string): DragResult => ({ kind: 'locked', reason })
  let newStart = start
  if (mode !== 'end') {
    if (start.anchor.kind !== 'absolute' && start.anchor.kind !== 'calendar')
      return locked(RELATIVE)
    const moved = shift(start)
    if (moved === null) return locked('The new start can’t be typed in its calendar.')
    newStart = moved
  }
  let newEnd = end
  if (end.kind === 'time_point' && mode !== 'start') {
    const point = end.time_point
    if (point.anchor.kind !== 'absolute' && point.anchor.kind !== 'calendar')
      return locked(RELATIVE)
    const moved = shift(point)
    if (moved === null) return locked('The new end can’t be typed in its calendar.')
    newEnd = { kind: 'time_point', time_point: moved }
  } else if (end.kind === 'duration' && mode !== 'move') {
    if (end.duration.kind !== 'base') {
      return locked('Its length is in calendar units: edit it in the event dialog.')
    }
    const units = BigInt(end.duration.units) + (mode === 'end' ? delta : -delta)
    if (units < 0n) return locked('It would end before it starts.')
    newEnd = { kind: 'duration', duration: { kind: 'base', units: units.toString() } }
  } else if (mode === 'end' && end.kind !== 'time_point' && end.kind !== 'duration') {
    return locked('It has no end to move.')
  }
  return { kind: 'ok', start: newStart, end: newEnd }
}

/**
 * A time point for moment `t` typed in the display calendar at `level` (the axis' minor unit:
 * the precision a double-click creates with), or an absolute moment for the Absolute calendar and
 * base units.
 */
export function pointAt(lens: Lens, t: bigint, level: string, lenses: readonly Lens[]): TimePoint {
  const absolute: TimePoint = { anchor: { kind: 'absolute', t: t.toString() }, precision: BASE }
  if (lens.calendar === null || level === BASE || lens.calendar.levelIndex(level) < 0) {
    return absolute
  }
  const typed = movePoint(
    { anchor: { kind: 'calendar', calendar_id: lens.id, fields: {} }, precision: level },
    t,
    lenses,
  )
  return typed ?? absolute
}
