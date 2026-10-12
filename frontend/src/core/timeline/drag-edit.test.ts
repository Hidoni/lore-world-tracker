import { fromFields, type EndSpec, type TimePoint } from '@lore/chronology'
import { describe, expect, it } from 'vitest'

import { presetLenses } from '@/test/calendars'

import { dragTime, movePoint, pointMoment } from './drag-edit'

const { lenses } = presetLenses('gregorian')
const GREG = lenses[0]?.calendar ?? null
if (GREG === null) throw new Error('gregorian')
const DAY = 86_400n

const typed = (fields: Record<string, string>, precision = 'day', era?: string): TimePoint => ({
  anchor: { kind: 'calendar', calendar_id: 'gregorian', fields, ...(era ? { era } : {}) },
  precision,
})
const absolute = (t: bigint): TimePoint => ({
  anchor: { kind: 'absolute', t: t.toString() },
  precision: 'base',
})
const at = (year: string, month: string, day: string) =>
  fromFields(GREG, { year, month, day }, 'day')

describe('drag editing', () => {
  it('types a moved date in its calendar: slot ids for months, the unit at the precision', () => {
    const point = typed({ year: '2000', month: 'jan', day: '31' })
    expect(movePoint(point, at('2000', 'jan', '31') + DAY, lenses)?.anchor).toEqual(
      typed({ year: '2000', month: 'feb', day: '1' }).anchor,
    )
    // A year-precision point moved into the middle of 2003 is 2003.
    const year = typed({ year: '2000' }, 'year')
    expect(movePoint(year, at('2003', 'jun', '15'), lenses)?.anchor).toEqual(
      typed({ year: '2003' }, 'year').anchor,
    )
    // Era years stay era years.
    const bc = typed({ year: '10', month: 'mar', day: '1' }, 'day', 'bc')
    const moved = movePoint(bc, (pointMoment(bc, lenses) ?? 0n) + 365n * DAY, lenses)
    // 9 BC (astronomical −8) is a leap year: 365 days after 1 March 10 BC is 29 February.
    expect(moved?.anchor).toMatchObject({
      era: 'bc',
      fields: { year: '9', month: 'feb', day: '29' },
    })
  })

  it('moves the whole event, keeping a duration and shifting an end date', () => {
    const start = typed({ year: '2000', month: 'jan', day: '1' })
    const duration: EndSpec = { kind: 'duration', duration: { kind: 'base', units: '100' } }
    const moved = dragTime(start, duration, 'move', 2n * DAY, lenses)
    expect(moved).toEqual({
      kind: 'ok',
      start: typed({ year: '2000', month: 'jan', day: '3' }),
      end: duration,
    })
    const until: EndSpec = { kind: 'time_point', time_point: absolute(at('2000', 'mar', '1')) }
    expect(dragTime(start, until, 'move', DAY, lenses)).toMatchObject({
      end: { time_point: { anchor: { t: (at('2000', 'mar', '1') + DAY).toString() } } },
    })
  })

  it('drags edges: a start edge keeps the end, an end edge changes it', () => {
    const start = absolute(1000n)
    const duration: EndSpec = { kind: 'duration', duration: { kind: 'base', units: '500' } }
    expect(dragTime(start, duration, 'start', 100n, lenses)).toEqual({
      kind: 'ok',
      start: absolute(1100n),
      end: { kind: 'duration', duration: { kind: 'base', units: '400' } },
    })
    expect(dragTime(start, duration, 'end', -100n, lenses)).toEqual({
      kind: 'ok',
      start,
      end: { kind: 'duration', duration: { kind: 'base', units: '400' } },
    })
    expect(dragTime(start, duration, 'end', -600n, lenses).kind).toBe('locked')
  })

  it('locks relative anchors, calendar durations and ends that are not there', () => {
    const relative: TimePoint = {
      anchor: {
        kind: 'relative',
        ref: { type: 'event', id: 'x', slot: 'start' },
        offset: { kind: 'base', units: '10' },
      },
      precision: 'base',
    }
    const instant: EndSpec = { kind: 'instant' }
    expect(dragTime(relative, instant, 'move', 10n, lenses)).toEqual({
      kind: 'locked',
      reason: expect.stringMatching(/offset/) as string,
    })
    const calendarLength: EndSpec = {
      kind: 'duration',
      duration: { kind: 'calendar', calendar_id: 'gregorian', amounts: { year: '1' }, sign: 1 },
    }
    expect(dragTime(absolute(0n), calendarLength, 'end', 10n, lenses).kind).toBe('locked')
    expect(dragTime(absolute(0n), calendarLength, 'move', 10n, lenses).kind).toBe('ok')
    expect(dragTime(absolute(0n), { kind: 'unknown' }, 'end', 10n, lenses).kind).toBe('locked')
  })
})
